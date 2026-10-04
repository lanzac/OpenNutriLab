# https://world.openfoodfacts.org/files/redocly/api-v3.redoc-static.html#schema/shape
from enum import StrEnum
from typing import Any

from ninja import Field
from ninja import Schema
from pydantic import ConfigDict


class OFFIngredientSchema(Schema):
    model_config = ConfigDict(
        from_attributes=True,  # allows to create from Django objects
        populate_by_name=True,  # allow us to use names even with alias defined
        extra="ignore",  # ignore _state, id, product_id, etc
    )

    name: str = Field(default="", validation_alias="text")
    # `percent` is a candidate for the share the label declares: OFF rescales
    # the label's percentages when they do not add up to 100, and does not say
    # so. It is checked against the label's text (see label_percentages)
    # before it is used. OFF's own `percent_estimate` is deliberately not read:
    # estimates are computed in-house.
    percentage: float | None = Field(default=None, validation_alias="percent")
    off_id: str = Field(default="", validation_alias="id")
    ciqual_food_code: str | None = Field(
        default=None, validation_alias="ciqual_food_code"
    )
    ciqual_proxy_food_code: str | None = Field(
        default=None, validation_alias="ciqual_proxy_food_code"
    )
    # https://django-ninja.dev/guides/response/?h=self#self-referencing-schemes
    ingredients: list["OFFIngredientSchema"] | None = Field(
        default=None, validation_alias="ingredients"
    )


OFFIngredientSchema.model_rebuild()


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
    ingredients: list[OFFIngredientSchema] | None = Field(
        default=None, validation_alias="ingredients"
    )
    # The product's main ingredient list, the text `ingredients` was parsed
    # from (in `ingredients_lc`; other languages are translations that may
    # describe another version of the recipe). Not stored: it only serves to
    # check the percentages, see label_percentages.
    ingredients_text: str | None = Field(
        default=None, validation_alias="ingredients_text"
    )
    group_level_1: str | None = Field(default=None, validation_alias="pnns_groups_1")
    group_level_2: str | None = Field(default=None, validation_alias="pnns_groups_2")


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
