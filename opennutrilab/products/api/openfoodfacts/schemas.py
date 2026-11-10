# https://world.openfoodfacts.org/files/redocly/api-v3.redoc-static.html#schema/shape
from enum import StrEnum
from typing import Any

from ninja import Field
from ninja import Schema
from pydantic import ConfigDict


class OFFProductSchema(Schema):
    model_config = ConfigDict(
        from_attributes=True,  # allows to create from Django objects
        populate_by_name=True,  # allow us to use names even with alias defined
        extra="ignore",  # ignore _state, id, product_id, etc
    )

    barcode: str = Field(validation_alias="code")
    name: str = Field(default="", validation_alias="product_name")
    image_url: str | None = Field(default=None, validation_alias="image_small_url")
    description: str | None = Field(default=None, validation_alias="categories")
    # Label values, raw: `<key>_100g` in grams for masses, `energy_100g` in kJ.
    # Read through each Nutrient's off_key (see services.declared_nutrients_from_off).
    nutriments: dict[str, Any] = Field(
        default_factory=dict, validation_alias="nutriments"
    )
    # What the nutrition table is given per: "100g", "100ml" or "serving". For a
    # table per 100 ml the `_100g` values above are that table as it is printed, not
    # converted to grams (see services.nutrition_unit_from_off).
    nutrition_data_per: str | None = Field(
        default=None, validation_alias="nutrition_data_per"
    )
    # The ingredient list as the label prints it, and its language. The only
    # thing read of an ingredient: OpenFoodFacts' own parsing of it drops what its
    # taxonomy has no word for (see services.label_parser), so its `ingredients`
    # are not read at all. Not stored.
    ingredients_text: str | None = Field(
        default=None, validation_alias="ingredients_text"
    )
    ingredients_lc: str | None = Field(default=None, validation_alias="ingredients_lc")
    # The serving as its contributors typed it ("35.7 g (1 tranche)"), read by
    # services.servings. OFF's own reading of it, `serving_quantity`, is not read.
    serving_size: str | None = Field(default=None, validation_alias="serving_size")
    # What the package holds, as typed from the packaging ("500 g", "6 x 125 g"), read
    # by services.packages. OFF's own reading of it, `product_quantity`, is not read.
    quantity: str | None = Field(default=None, validation_alias="quantity")
    group_level_1: str | None = Field(default=None, validation_alias="pnns_groups_1")
    group_level_2: str | None = Field(default=None, validation_alias="pnns_groups_2")


class OFFSearchHitSchema(Schema):
    """A product as a search of OpenFoodFacts lists it: enough to tell it apart."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    barcode: str = Field(validation_alias="code")
    name: str | None = Field(default=None, validation_alias="product_name")
    brands: list[str] = Field(default_factory=list)
    # What the package holds, as typed from the packaging ("500 g").
    quantity: str | None = None
    image_url: str | None = Field(default=None, validation_alias="image_small_url")


# ---- ENUMS ----


class StatusEnum(StrEnum):
    success = "success"
    success_with_warnings = "success_with_warnings"
    success_with_errors = "success_with_errors"
    failure = "failure"


# ---- BLOCK: message ----


class Message(Schema):
    id: str
    name: str
    lc_name: str | None = None
    description: str | None = None
    lc_description: str | None = None


# ---- BLOCK: field ----


class FieldInfo(Schema):
    id: str
    value: str


# ---- BLOCK: impact ----


class Impact(Schema):
    id: str
    name: str
    lc_name: str | None = None
    description: str | None = None
    lc_description: str | None = None


# ---- BLOCK: warning/error entry ----


class WarningOrError(Schema):
    message: Message
    field: FieldInfo
    impact: Impact


# ---- BLOCK: result ----


class Result(Schema):
    id: str
    name: str
    lc_name: str | None = None


# ---- ROOT RESPONSE ----


class OFFProductAPIResponseSchema(Schema):
    status: StatusEnum
    result: Result
    warnings: list[WarningOrError] | None = None
    errors: list[WarningOrError] | None = None
    product: OFFProductSchema | None = None


class OFFWriteAnswerSchema(Schema):
    """What the write API of OpenFoodFacts answers: 1 when it saved, else why not."""

    status: int
    status_verbose: str | None = None
