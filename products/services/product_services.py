from typing import cast

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db import models
from django.db import transaction

from products.api.schemas.inbound import IngredientInput
from products.api.schemas.inbound import MacronutrientInput
from products.api.schemas.inbound import ProductCreate
from products.api.schemas.inbound import ProductUpdate
from products.models import Ingredient
from products.models import IngredientRef
from products.models import Macronutrient
from products.models import Product
from products.models import ProductMacronutrient
from products.utils import fetch_image_as_uploaded_file

DEFAULT_IMAGE_NAME = "{barcode}.jpg"


# -------------------------
# Field application helpers
# -------------------------
def apply_product_update_fields(product: Product, data: ProductUpdate) -> None:
    """
    Apply partial updates from ProductUpdate.
    Only provided fields are written to DB.
    """
    simple_fields: list[str] = [
        "name",
        "description",
        "group_level_1",
        "group_level_2",
    ]

    update_fields: list[str] = []

    for field in simple_fields:
        value = getattr(data, field)
        if value is not None:
            setattr(product, field, value)
            update_fields.append(field)

    # Handle nested nutritional values separately
    if data.nutritional_values and data.nutritional_values.energy is not None:
        product.energy = data.nutritional_values.energy
        update_fields.append("energy")

    if update_fields:
        product.save(update_fields=update_fields)


# -------------------------------------
# Relations sync helpers (create/update)
# -------------------------------------
def upsert_product_macronutrients(
    product: Product, macronutrients_list: list[MacronutrientInput]
) -> None:
    """Simple upsert loop suitable for small lists (create & update)."""
    for item in macronutrients_list:
        macro_obj = Macronutrient.objects.get(name=item.name)
        ProductMacronutrient.objects.update_or_create(
            product=product, macronutrient=macro_obj, defaults={"amount": item.amount}
        )


def sync_product_macronutrients_update(
    product: Product, macronutrients_list: list[MacronutrientInput] | None
) -> None:
    """
    Sync macronutrients on update: if list is provided, perform upsert.
    If None -> do nothing (partial update won't touch existing macronutrients).
    If you want to clear all macronutrients, pass an empty list (then delete).
    """
    if macronutrients_list is None:
        return

    # If the client provided an empty list, that likely means "clear"
    if not macronutrients_list:
        ProductMacronutrient.objects.filter(product=product).delete()
        return

    # Otherwise upsert the provided ones
    upsert_product_macronutrients(product, macronutrients_list)


def upsert_product_ingredients(
    product: Product,
    ingredients_list: list[IngredientInput],
    parent: Ingredient | None = None,
) -> None:
    """
    Create or update ingredients recursively (used on create and when recreating).
    """
    for ing in ingredients_list or []:
        name = ing.name.strip()
        reference = IngredientRef.objects.filter(name=name).first()
        ingredient, _created = Ingredient.objects.update_or_create(
            product=product,
            parent=parent,
            name=name,
            defaults={
                "percentage": getattr(ing, "percentage", None),
                "reference": reference,
            },
        )
        subingredients: list[IngredientInput] = (
            getattr(ing, "sub_ingredients", []) or []
        )
        if subingredients:
            upsert_product_ingredients(product, subingredients, parent=ingredient)


def sync_product_ingredients_update(
    product: Product, ingredients_list: list[IngredientInput] | None
) -> None:
    """
    Sync ingredients on update. If None -> don't touch. If empty list -> delete all.
    Simpler approach: when client provides ingredients, we delete existing and recreate.
    """
    if ingredients_list is None:
        return

    # Delete existing (clean slate), then recreate (keeps the logic simple)
    Ingredient.objects.filter(product=product).delete()
    if ingredients_list:
        upsert_product_ingredients(product, ingredients_list)


# -------------------------
# Image handling helpers
# -------------------------
def save_image_overwrite(
    product: Product, uploaded_file: InMemoryUploadedFile | None
) -> None:
    """
    Save an uploaded file to the Product's image field, overwriting any existing file.

    Handles both create and update cases:
    - Deletes the storage file if it exists at the target path
    - Deletes any file currently attached to the Product instance
    - Saves the new file to the same field

    Args:
        product: Product instance (unsaved or existing)
        uploaded_file: InMemoryUploadedFile or None. If None, does nothing.
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


def sync_product_image(product: Product, image_url: str | None, barcode: str) -> None:
    """Download image if provided and save it, overwriting existing image cleanly."""
    if not image_url:
        return

    filename = DEFAULT_IMAGE_NAME.format(barcode=barcode)
    uploaded_file = fetch_image_as_uploaded_file(image_url=image_url, filename=filename)
    save_image_overwrite(product, uploaded_file)


# -------------------------
# High-level create / update
# -------------------------
def create_product(data: ProductCreate) -> Product:
    with transaction.atomic():
        # create minimal product to ensure PK exists (upload_to might need it)
        product = Product(
            barcode=data.barcode,
            name=data.name,
            description=data.description,
            group_level_1=data.group_level_1,
            group_level_2=data.group_level_2,
            energy=data.nutritional_values.energy,
        )

        product.save()

        # relations (create semantics)
        upsert_product_macronutrients(product, data.nutritional_values.macronutrients)
        upsert_product_ingredients(product, data.ingredients)

    # image outside tx (download can fail without rolling back DB)
    sync_product_image(product, getattr(data, "image_url", None), data.barcode)
    return product


def update_product(product: Product, data: ProductUpdate) -> Product:
    with transaction.atomic():
        # partial field update
        apply_product_update_fields(product, data)

        # relations: only touch those provided by the client
        sync_product_macronutrients_update(
            product,
            getattr(data.nutritional_values, "macronutrients", None)
            if data.nutritional_values
            else None,
        )
        sync_product_ingredients_update(product, data.ingredients)

    # image handling (outside tx)
    sync_product_image(product, getattr(data, "image_url", None), product.barcode)
    return product
