"""
The only code that writes products.

The API routes and the product form both describe the change as a
ProductCreate or ProductUpdate (products.api.schemas.inbound) and hand it here,
so a product saved from either ends up exactly the same.
"""

import io
import logging
from pathlib import PurePath
from typing import NamedTuple
from typing import cast
from urllib.parse import urlparse

import requests
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError
from django.db import models
from django.db import transaction
from django.db.models.functions import Lower

from opennutrilab.products.api.openfoodfacts.services import OFF_HEADERS
from opennutrilab.products.api.schemas.inbound import OFF_IMAGE_HOSTS
from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.api.schemas.inbound import MacronutrientInput
from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.api.schemas.inbound import ProductUpdate
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import IngredientRef
from opennutrilab.products.models import Macronutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductMacronutrient

logger = logging.getLogger(__name__)

IMAGE_DOWNLOAD_TIMEOUT = 10  # seconds


class ProductAlreadyExistsError(Exception):
    """A product with this barcode is already stored."""


class UnknownMacronutrientError(Exception):
    """The payload names a macronutrient the database does not know."""


class ProductWrite(NamedTuple):
    product: Product
    # True when a photo was asked for by URL and could not be downloaded. The
    # product itself is saved either way.
    image_fetch_failed: bool = False


# -------------------------
# High-level create / update
# -------------------------
def create_product(
    data: ProductCreate, *, image: UploadedFile | None = None
) -> ProductWrite:
    """
    Create a product with its macronutrients and ingredients.

    `image` is a file the user uploaded; it wins over `data.image_url`.
    """
    with transaction.atomic():
        try:
            # create() forces an INSERT. Product(...).save() with an existing
            # primary key would silently UPDATE that product instead.
            product = Product.objects.create(
                barcode=data.barcode,
                name=data.name,
                description=data.description,
                group_level_1=data.group_level_1,
                group_level_2=data.group_level_2,
                energy_kj=data.nutritional_values.energy_kj,
            )
        except IntegrityError as e:
            raise ProductAlreadyExistsError(data.barcode) from e

        _replace_macronutrients(product, data.nutritional_values.macronutrients)
        _replace_ingredients(product, data.ingredients)

    # Outside the transaction: a slow or failed download must not hold it
    # open, nor roll the product back.
    image_ok = _attach_image(product, upload=image, url=data.image_url)
    return ProductWrite(product, image_fetch_failed=not image_ok)


def update_product(
    product: Product, data: ProductUpdate, *, image: UploadedFile | None = None
) -> ProductWrite:
    """
    Apply a partial update: what `data` leaves out (None) is not touched.

    A macronutrient or ingredient list that is given replaces the stored one.
    """
    with transaction.atomic():
        _apply_fields(product, data)

        nutritional_values = data.nutritional_values
        if nutritional_values and nutritional_values.macronutrients is not None:
            _replace_macronutrients(product, nutritional_values.macronutrients)

        if data.ingredients is not None:
            _replace_ingredients(product, data.ingredients)

    image_ok = _attach_image(product, upload=image, url=data.image_url)
    return ProductWrite(product, image_fetch_failed=not image_ok)


# -------------------------
# Fields and relations
# -------------------------
def _apply_fields(product: Product, data: ProductUpdate) -> None:
    update_fields: list[str] = []

    for field in ("name", "description", "group_level_1", "group_level_2"):
        value = getattr(data, field)
        if value is not None:
            setattr(product, field, value)
            update_fields.append(field)

    if data.nutritional_values and data.nutritional_values.energy_kj is not None:
        product.energy_kj = data.nutritional_values.energy_kj
        update_fields.append("energy_kj")

    if update_fields:
        product.save(update_fields=update_fields)


def _replace_macronutrients(product: Product, items: list[MacronutrientInput]) -> None:
    """
    Make `items` the product's complete set of macronutrient amounts.

    One left out is removed; an amount of 0 is a measurement and is kept.
    """
    names = [item.name for item in items]
    known = {m.name: m for m in Macronutrient.objects.filter(name__in=names)}
    unknown = sorted(set(names) - known.keys())
    if unknown:
        msg = f"Unknown macronutrients: {', '.join(unknown)}"
        raise UnknownMacronutrientError(msg)

    ProductMacronutrient.objects.filter(product=product).exclude(
        macronutrient__in=names
    ).delete()
    for item in items:
        ProductMacronutrient.objects.update_or_create(
            product=product,
            macronutrient=known[item.name],
            defaults={"amount_g": item.amount_g},
        )


def _replace_ingredients(product: Product, items: list[IngredientInput]) -> None:
    """Replace the product's ingredient tree with `items`."""
    product.ingredients.all().delete()
    references = references_by_lowercase_name(items)
    _create_ingredients(product, items, parent=None, references=references)


def _create_ingredients(
    product: Product,
    items: list[IngredientInput],
    parent: Ingredient | None,
    references: dict[str, IngredientRef],
) -> None:
    for item in items:
        name = item.name.strip()
        # update_or_create rather than create: OpenFoodFacts sometimes lists
        # the same ingredient twice under one parent, which the unique
        # constraints on Ingredient would reject. The last occurrence wins.
        ingredient, _created = Ingredient.objects.update_or_create(
            product=product,
            parent=parent,
            name=name,
            defaults={
                "percentage": item.percentage,
                "reference": references.get(name.lower()),
            },
        )
        _create_ingredients(product, item.sub_ingredients, ingredient, references)


def references_by_lowercase_name(
    items: list[IngredientInput],
) -> dict[str, IngredientRef]:
    """
    Reference ingredients for every name in the tree, in one query.

    Matched without regard to case. The product form's "recognized" column
    uses this same function (products.views), so what it shows as recognized
    is what gets linked.
    """
    names: set[str] = set()
    stack = list(items)
    while stack:
        item = stack.pop()
        names.add(item.name.strip().lower())
        stack.extend(item.sub_ingredients)

    if not names:
        return {}
    matches = IngredientRef.objects.annotate(lower_name=Lower("name")).filter(
        lower_name__in=names
    )
    return {ref.lower_name: ref for ref in matches}  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


# -------------------------
# Image handling
# -------------------------
def _attach_image(
    product: Product, *, upload: UploadedFile | None, url: str | None
) -> bool:
    """
    Store the uploaded photo, or else download the one at `url`.

    Returns False only when a download was needed and failed.
    """
    if upload is not None:
        suffix = PurePath(upload.name or "").suffix.lower() or ".jpg"
        upload.name = f"{product.barcode}{suffix}"
        save_image_overwrite(product, upload)
        return True

    if url:
        downloaded = download_image(url, filename=f"{product.barcode}.jpg")
        if downloaded is None:
            return False
        save_image_overwrite(product, downloaded)

    return True


def download_image(url: str, filename: str) -> InMemoryUploadedFile | None:
    """
    Download a product photo from OpenFoodFacts, or None if that fails.

    OpenFoodFacts serves images from a different host than its API, which can
    be unreachable while the API answers; a failure here must not lose the
    rest of the product.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in OFF_IMAGE_HOSTS:
        # The inbound schemas already reject such URLs; this keeps the function
        # safe on its own.
        msg = f"Refusing to download an image from {url}"
        raise ValueError(msg)

    try:
        response = requests.get(
            url, timeout=IMAGE_DOWNLOAD_TIMEOUT, headers=OFF_HEADERS
        )
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to download product image from %s: %s", url, e)
        return None

    content = response.content
    return InMemoryUploadedFile(
        file=io.BytesIO(content),
        field_name="image",
        name=filename,
        content_type=response.headers.get("Content-Type", "image/jpeg"),
        size=len(content),
        charset=None,
    )


def save_image_overwrite(product: Product, uploaded_file: UploadedFile | None) -> None:
    """
    Save an uploaded file to the Product's image field, overwriting any existing file.

    Handles both create and update cases:
    - Deletes the storage file if it exists at the target path
    - Deletes any file currently attached to the Product instance
    - Saves the new file to the same field

    Args:
        product: Product instance (unsaved or existing)
        uploaded_file: The file to store. If None, does nothing.
    """
    if not uploaded_file:
        return

    # Cast to FileField to satisfy type checker
    field = cast("models.FileField", product._meta.get_field("image"))  # noqa: SLF001

    # Compute the storage path Django will actually use
    final_path = field.generate_filename(product, uploaded_file.name)

    # Delete any existing file at that path
    if default_storage.exists(final_path):
        default_storage.delete(final_path)

    # Delete current image on the instance (if any)
    if product.image:
        product.image.delete(save=False)

    # Assign and save
    product.image.save(uploaded_file.name, uploaded_file, save=True)
