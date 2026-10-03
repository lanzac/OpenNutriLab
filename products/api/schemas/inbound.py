"""
What a client sends to create or change a product.

The API routes and the product form both build these, and
products.services.product_services is the only code that writes them to the
database. Bounds mirror the model fields' validators and max_length, which the
ORM does not enforce on its own.
"""

from decimal import Decimal
from urllib.parse import urlparse

from django.core.exceptions import ValidationError as DjangoValidationError
from ninja import Field
from ninja import Schema
from pydantic import field_validator

from products.fields import validate_ean13

# The only hosts a product photo is downloaded from. The URL comes from the
# client (an API payload, a hidden field of the product form), so without this
# the server would fetch any URL it is handed - internal services included.
OFF_IMAGE_HOSTS = frozenset({"images.openfoodfacts.org", "static.openfoodfacts.org"})


def _check_off_image_url(url: str | None) -> str | None:
    if url:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in OFF_IMAGE_HOSTS:
            msg = "Product images can only be downloaded from OpenFoodFacts."
            raise ValueError(msg)
    return url


def _check_unique_names(
    items: list["MacronutrientInput"],
) -> list["MacronutrientInput"]:
    names = [item.name for item in items]
    if len(names) != len(set(names)):
        msg = "Each macronutrient can only be given once."
        raise ValueError(msg)
    return items


class MacronutrientInput(Schema):
    """One macronutrient amount, per 100 g of product."""

    name: str
    amount_g: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class NutritionalValuesInput(Schema):
    energy_kj: int = Field(ge=0, le=100_000)
    macronutrients: list[MacronutrientInput] = []

    @field_validator("macronutrients")
    @classmethod
    def unique_names(cls, items: list[MacronutrientInput]) -> list[MacronutrientInput]:
        return _check_unique_names(items)


class IngredientInput(Schema):
    name: str = Field(min_length=1, max_length=255)
    percentage: Decimal | None = Field(default=None, ge=0, le=100)

    # https://django-ninja.dev/guides/response/?h=self#self-referencing-schemes
    sub_ingredients: list["IngredientInput"] = []


IngredientInput.model_rebuild()


class ProductCreate(Schema):
    barcode: str
    name: str = Field(min_length=1, max_length=100)
    image_url: str | None = None
    description: str = ""
    group_level_1: str = Field(default="", max_length=100)
    group_level_2: str = Field(default="", max_length=100)
    nutritional_values: NutritionalValuesInput
    ingredients: list[IngredientInput] = []

    @field_validator("barcode")
    @classmethod
    def validate_barcode_format(cls, barcode: str) -> str:
        # Same rule as the model field (products.fields.EAN13Field).
        try:
            validate_ean13(value=barcode)
        except DjangoValidationError as e:
            msg = f"Invalid barcode {barcode}: {' '.join(e.messages)}"
            raise ValueError(msg) from e
        return barcode

    @field_validator("image_url")
    @classmethod
    def image_from_off(cls, url: str | None) -> str | None:
        return _check_off_image_url(url)


# -------------------------------------------------------------
# UPDATE SCHEMAS (PATCH) - every field is optional, for partial updates.
# A field left out (None) is not touched. A list that is given replaces the
# stored one entirely: an empty macronutrient list clears them all.
# -------------------------------------------------------------


class NutritionalValuesUpdate(Schema):
    energy_kj: int | None = Field(default=None, ge=0, le=100_000)
    macronutrients: list[MacronutrientInput] | None = None

    @field_validator("macronutrients")
    @classmethod
    def unique_names(
        cls, items: list[MacronutrientInput] | None
    ) -> list[MacronutrientInput] | None:
        return None if items is None else _check_unique_names(items)


class ProductUpdate(Schema):
    # No barcode: it is the primary key and never changes.
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    image_url: str | None = None
    group_level_1: str | None = Field(default=None, max_length=100)
    group_level_2: str | None = Field(default=None, max_length=100)
    nutritional_values: NutritionalValuesUpdate | None = None
    ingredients: list[IngredientInput] | None = None

    @field_validator("image_url")
    @classmethod
    def image_from_off(cls, url: str | None) -> str | None:
        return _check_off_image_url(url)
