"""
What a client sends to create or change a product.

The API routes and the product form both build these, and
products.services.product_services is the only code that writes them to the
database. Bounds mirror the model fields' validators and max_length, which the
ORM does not enforce on its own.
"""

from decimal import Decimal
from typing import Annotated
from urllib.parse import urlparse

from django.core.exceptions import ValidationError as DjangoValidationError
from ninja import Field
from ninja import Schema
from pydantic import field_validator

from opennutrilab.products.fields import validate_ean13

# The only hosts a product photo is downloaded from. The URL comes from the
# client (an API payload, a hidden field of the product form), so without this
# the server would fetch any URL it is handed - internal services included.
OFF_IMAGE_HOSTS = frozenset({"images.openfoodfacts.org", "static.openfoodfacts.org"})


def validate_off_image_url(url: str | None) -> str | None:
    if url:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in OFF_IMAGE_HOSTS:
            msg = "Product images can only be downloaded from OpenFoodFacts."
            raise ValueError(msg)
    return url


# An amount per 100 g, in its nutrient's unit (Nutrient.unit), with the
# precision the database keeps.
NutrientAmount = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=4)]


class IngredientInput(Schema):
    name: str = Field(min_length=1, max_length=255)
    # As declared on the label; never an estimate.
    percentage: Decimal | None = Field(default=None, ge=0, le=100)
    # Raw OpenFoodFacts data, stored for reference only.
    off_id: str = Field(default="", max_length=255)
    off_ciqual_food_code: str = Field(default="", max_length=10)
    off_ciqual_proxy_food_code: str = Field(default="", max_length=10)

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
    # Values declared on the nutrition label, keyed by Nutrient.code.
    nutrients: dict[str, NutrientAmount] = {}
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
        return validate_off_image_url(url)


# -------------------------------------------------------------
# UPDATE SCHEMA (PATCH) - every field is optional, for partial updates.
# A field left out (None) is not touched. In `nutrients`, a code left out is
# not touched either, and a code set to null clears that value. A list of
# ingredients that is given replaces the stored tree.
# -------------------------------------------------------------


class ProductUpdate(Schema):
    # No barcode: it is the primary key and never changes.
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    image_url: str | None = None
    group_level_1: str | None = Field(default=None, max_length=100)
    group_level_2: str | None = Field(default=None, max_length=100)
    nutrients: dict[str, NutrientAmount | None] | None = None
    ingredients: list[IngredientInput] | None = None

    @field_validator("image_url")
    @classmethod
    def image_from_off(cls, url: str | None) -> str | None:
        return validate_off_image_url(url)
