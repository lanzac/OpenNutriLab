"""
The only code that writes products.

The API routes and the product form both describe the change as a
ProductCreate or ProductUpdate (products.api.schemas.inbound) and hand it here,
so a product saved from either ends up exactly the same.
"""

import io
import logging
from collections.abc import Mapping
from decimal import Decimal
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
from django.utils.translation import gettext as _

from opennutrilab.products.api.openfoodfacts.services import OFF_HEADERS
from opennutrilab.products.api.openfoodfacts.services import (
    ingredient_inputs_from_label,
)
from opennutrilab.products.api.schemas.inbound import OFF_IMAGE_HOSTS
from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.api.schemas.inbound import ProductUpdate
from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.services.label_parser import LabelWarning
from opennutrilab.products.services.preparation_services import (
    make_preparations_of_listed_parts,
)
from opennutrilab.products.services.reference_services import Item
from opennutrilab.products.services.reference_services import name_key
from opennutrilab.products.services.reference_services import resolve_references

logger = logging.getLogger(__name__)

IMAGE_DOWNLOAD_TIMEOUT = 10  # seconds


class ProductAlreadyExistsError(Exception):
    """A product with this barcode is already stored."""


class UnknownNutrientError(Exception):
    """The payload names a nutrient code the catalogue does not know."""


class Reread(NamedTuple):
    """What reading a product's stored label again did."""

    # Whether the ingredients were replaced.
    done: bool
    before: int
    after: int
    warnings: list[LabelWarning]


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
    Create a product with its declared nutrients and ingredients.

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
                ingredients_text=data.ingredients_text,
            )
        except IntegrityError as e:
            raise ProductAlreadyExistsError(data.barcode) from e

        _set_declared_nutrients(product, dict(data.nutrients))
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

    In `data.nutrients`, a code left out is not touched and a code set to None
    clears that value. An ingredient list that is given replaces the tree.
    """
    with transaction.atomic():
        _apply_fields(product, data)

        if data.nutrients is not None:
            _set_declared_nutrients(product, data.nutrients)

        if data.ingredients is not None:
            _replace_ingredients(product, data.ingredients)

    image_ok = _attach_image(product, upload=image, url=data.image_url)
    return ProductWrite(product, image_fetch_failed=not image_ok)


def reread_ingredients(product: Product, language: str) -> Reread:
    """
    Read the label text stored with a product again, and replace its ingredients
    with what it says, as saving does.

    The ingredients come from that text and nothing else (see label_parser), so
    this loses nothing a person entered. A product with no text, or whose text looks
    badly read (the reading stops), is left as it is. `language` is the one the
    label is in: it says where the names of what is new go.
    """
    before = product.ingredients.count()
    if not product.ingredients_text.strip():
        return Reread(done=False, before=before, after=before, warnings=[])
    inputs, warnings = ingredient_inputs_from_label(product.ingredients_text, language)
    if not inputs or any(w.stops_reading for w in warnings):
        return Reread(done=False, before=before, after=before, warnings=warnings)
    with transaction.atomic():
        _replace_ingredients(product, inputs)
    return Reread(
        done=True,
        before=before,
        after=product.ingredients.count(),
        warnings=warnings,
    )


# -------------------------
# Fields and relations
# -------------------------
def _apply_fields(product: Product, data: ProductUpdate) -> None:
    update_fields: list[str] = []

    for field in (
        "name",
        "description",
        "group_level_1",
        "group_level_2",
        "ingredients_text",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(product, field, value)
            update_fields.append(field)

    if update_fields:
        product.save(update_fields=update_fields)


def _set_declared_nutrients(
    product: Product, values: Mapping[str, Decimal | None]
) -> None:
    """
    Store the label values given, keyed by Nutrient.code.

    None clears a value; an amount of 0 is a measurement and is kept. Codes
    left out are not touched.
    """
    known = {n.code: n for n in Nutrient.objects.filter(code__in=values)}
    unknown = sorted(set(values) - known.keys())
    if unknown:
        msg = f"Unknown nutrients: {', '.join(unknown)}"
        raise UnknownNutrientError(msg)

    for code, amount in values.items():
        if amount is None:
            ProductNutrient.objects.filter(
                product=product, nutrient=known[code]
            ).delete()
        else:
            ProductNutrient.objects.update_or_create(
                product=product, nutrient=known[code], defaults={"amount": amount}
            )


def _replace_ingredients(product: Product, items: list[IngredientInput]) -> None:
    """
    Replace the product's ingredient tree with `items`.

    Each ingredient is the reference ingredient, the preparation or the additive
    that has its name, a reference being created when none has, and an additive
    for an E number (see reference_services). One whose parts the label lists is
    a preparation, whichever it was found to be (see preparation_services).
    Nothing of the old tree needs carrying over: the name finds the same one
    again. A preparation takes the parts the label lists for it as its children,
    as any ingredient does.
    """
    linked = make_preparations_of_listed_parts(items, resolve_references(items))
    product.ingredients.all().delete()
    _create_ingredients(product, items, parent=None, linked=linked)


def _create_ingredients(
    product: Product,
    items: list[IngredientInput],
    parent: Ingredient | None,
    linked: dict[str, Item],
) -> None:
    for item in items:
        found = linked[name_key(item.name)]
        # Only the one it is is given: the others stay null, as the check says.
        link = (
            "preparation"
            if isinstance(found, Preparation)
            else "additive"
            if isinstance(found, Additive)
            else "reference"
        )
        # update_or_create rather than create: an ingredient can be listed
        # twice under one parent (OpenFoodFacts sometimes does), which the
        # unique constraints on Ingredient would reject. The last occurrence
        # wins.
        ingredient, _created = Ingredient.objects.update_or_create(
            product=product,
            parent=parent,
            **{link: found},
            defaults={"percentage": item.percentage},
        )
        _create_ingredients(product, item.sub_ingredients, ingredient, linked)


# -------------------------
# Consistency of declared values
# -------------------------
def declared_value_warnings(values: Mapping[str, Decimal]) -> list[str]:
    """
    Inconsistencies in label values, as messages for the user.

    Warnings only, never errors: the label is the reference, and its own
    rounding can make a value slightly exceed another. An inconsistency is
    still worth a look - a typo, or a label to correct on OpenFoodFacts.
    """
    nutrients = {n.code: n for n in Nutrient.objects.filter(code__in=values)}
    warnings: list[str] = []

    for code, amount in values.items():
        nutrient = nutrients[code]
        parent_amount = values.get(nutrient.parent_id or "")
        if parent_amount is not None and amount > parent_amount:
            parent = nutrients[cast("str", nutrient.parent_id)]
            warnings.append(
                _(
                    "%(part)s (%(part_amount)s %(unit)s) exceed "
                    "%(whole)s (%(whole_amount)s %(unit)s)."
                )
                % {
                    "part": nutrient.name,
                    "part_amount": plain_amount(amount),
                    "whole": parent.name,
                    "whole_amount": plain_amount(parent_amount),
                    "unit": nutrient.unit,
                }
            )

    total = sum(
        (
            amount
            for code, amount in values.items()
            if Nutrient.Unit(nutrients[code].unit) is Nutrient.Unit.GRAM
            and nutrients[code].parent_id is None
        ),
        Decimal(0),
    )
    if total > 100:  # noqa: PLR2004
        warnings.append(
            _(
                "The amounts add up to %(total)s g, "
                "more than the 100 g they are given for."
            )
            % {"total": plain_amount(total)}
        )
    return warnings


def plain_amount(amount: Decimal) -> str:
    """9.4000 as "9.4", 100 as "100" (normalize() alone gives "1E+2")."""
    return format(amount.normalize(), "f")


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
