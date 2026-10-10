"""
What a client sends to create or change a product.

The API routes and the product form both build these, and
products.services.product_services is the only code that writes them to the
database. Bounds mirror the model fields' validators and max_length, which the
ORM does not enforce on its own.
"""

from decimal import Decimal
from typing import Annotated
from typing import Literal
from urllib.parse import urlparse

from django.core.exceptions import ValidationError as DjangoValidationError
from ninja import Field
from ninja import Schema
from pydantic import AfterValidator
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


def _is_a_place(place: tuple[int, int]) -> tuple[int, int]:
    start, end = place
    if start < 0 or end <= start:
        msg = f"{place} is not a place of a text: from 0 or more, and to after it."
        raise ValueError(msg)
    return place


# A place of the label's text: where it starts, and where it ends (not in it).
Place = Annotated[tuple[int, int], AfterValidator(_is_a_place)]


class IngredientInput(Schema):
    name: str = Field(min_length=1, max_length=255)
    # The language the name is in ("fr"), when it is known: it says which of the
    # reference's two names a name that is new belongs in.
    language: str = Field(default="", max_length=10)
    # As declared on the label; never an estimate.
    percentage: Decimal | None = Field(default=None, ge=0, le=100)
    # What the label says it is, when it does: the functional class that headed it
    # ("acidifiant : acide citrique", a value of Additive.Function) and the E number
    # written next to its name. Either one makes it an additive.
    function: str = Field(default="", max_length=30)
    code: str = Field(default="", max_length=10)
    # Raw OpenFoodFacts data, stored for reference only.
    off_id: str = Field(default="", max_length=255)
    off_ciqual_food_code: str = Field(default="", max_length=10)
    off_ciqual_proxy_food_code: str = Field(default="", max_length=10)

    # https://django-ninja.dev/guides/response/?h=self#self-referencing-schemes
    sub_ingredients: list["IngredientInput"] = []


IngredientInput.model_rebuild()


class ReadLabelIn(Schema):
    """A label's text to read again, without the places a person marked."""

    text: str = Field(max_length=20_000)
    language: str = Field(default="", max_length=10)
    ignored: list[Place] = Field(default=[], max_length=500)


class ServingInput(Schema):
    """A product's serving (see Product.serving_quantity)."""

    quantity: Decimal = Field(gt=0, max_digits=8, decimal_places=2)
    unit: Literal["g", "ml"] = "g"
    name: str = Field(default="", max_length=100)


class PackageInput(Schema):
    """What a product's package holds (see Product.package_quantity)."""

    quantity: Decimal = Field(gt=0, max_digits=9, decimal_places=2)
    unit: Literal["g", "ml"] = "g"


class StockInput(Schema):
    """How much of a product is at hand now (see InventoryItem.stock_quantity)."""

    # Null says it is not counted. Nothing is below nothing: 0 is used up.
    quantity: Decimal | None = Field(default=None, ge=0, max_digits=9, decimal_places=2)
    # The unit it was counted in, or the one it would be counted in when it was not
    # counted yet. Servings are whole, and the product has a serving.
    unit: Literal["g", "ml", "serving"] | None = None


class ProductCreate(Schema):
    barcode: str
    name: str = Field(min_length=1, max_length=100)
    image_url: str | None = None
    description: str = ""
    group_level_1: str = Field(default="", max_length=100)
    group_level_2: str = Field(default="", max_length=100)
    # Values declared on the nutrition label, keyed by Nutrient.code, and what the
    # table is given per 100 of (see Product.nutrition_unit).
    nutrients: dict[str, NutrientAmount] = {}
    nutrition_unit: Literal["g", "ml"] = "g"
    ingredients: list[IngredientInput] = []
    # The label's list those ingredients were read from, when there is one, and the
    # places of it (start, end) that were left out of the reading.
    ingredients_text: str = ""
    ingredients_language: str = Field(default="", max_length=10)
    ingredients_ignored: list[Place] = []
    serving: ServingInput | None = None
    package: PackageInput | None = None

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
# ingredients that is given replaces the stored tree. The serving and the package
# are the fields a null clears: left out they are not touched, given as null they
# are removed.
# -------------------------------------------------------------


class ProductUpdate(Schema):
    # No barcode: it is the primary key and never changes.
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    image_url: str | None = None
    group_level_1: str | None = Field(default=None, max_length=100)
    group_level_2: str | None = Field(default=None, max_length=100)
    nutrients: dict[str, NutrientAmount | None] | None = None
    nutrition_unit: Literal["g", "ml"] | None = None
    ingredients: list[IngredientInput] | None = None
    ingredients_text: str | None = None
    ingredients_language: str | None = Field(default=None, max_length=10)
    ingredients_ignored: list[Place] | None = None
    serving: ServingInput | None = None
    package: PackageInput | None = None

    @property
    def clears_serving(self) -> bool:
        """Whether the serving was given as null, which removes it."""
        return "serving" in self.model_fields_set and self.serving is None

    @property
    def clears_package(self) -> bool:
        """Whether the package was given as null, which removes it."""
        return "package" in self.model_fields_set and self.package is None

    @field_validator("image_url")
    @classmethod
    def image_from_off(cls, url: str | None) -> str | None:
        return validate_off_image_url(url)
