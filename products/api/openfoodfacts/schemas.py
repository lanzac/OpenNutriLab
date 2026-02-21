# https://world.openfoodfacts.org/files/redocly/api-v3.redoc-static.html#schema/shape
# https://world.openfoodfacts.org/files/redocly/api-v3.redoc-static.html#schema/shape
from enum import Enum

from ninja import Field
from ninja import Schema
from pydantic import AliasPath
from pydantic import ConfigDict


class OFFIngredientSchema(Schema):
    model_config = ConfigDict(
        from_attributes=True,  # allows to create from Django objects
        populate_by_name=True,  # allow us to use names even with alias defined
        extra="ignore",  # ignore _state, id, product_id, etc
    )

    name: str = Field(default="", validation_alias="text")
    percentage: float | None = Field(default=None, validation_alias="percent")
    # https://django-ninja.dev/guides/response/?h=self#self-referencing-schemes
    ingredients: list["OFFIngredientSchema"] | None = Field(
        default=None, validation_alias="ingredients"
    )


OFFIngredientSchema.model_rebuild()


class OFFMacronutrientsSchema(Schema):
    model_config = ConfigDict(
        from_attributes=True,  # allows to create from Django objects
        populate_by_name=True,  # allow us to use names even with alias defined
        extra="ignore",  # ignore _state, id, product_id, etc
    )

    fat: float | None = Field(default=None, validation_alias="fat_100g")
    saturated_fat: float | None = Field(
        default=None, validation_alias="saturated-fat_100g"
    )
    carbohydrates: float | None = Field(
        default=None, validation_alias="carbohydrates_100g"
    )
    sugars: float | None = Field(default=None, validation_alias="sugars_100g")
    fiber: float | None = Field(default=None, validation_alias="fiber_100g")
    proteins: float | None = Field(default=None, validation_alias="proteins_100g")


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
    energy: int | None = Field(
        default=None, validation_alias=AliasPath("nutriments", "energy_100g")
    )
    macronutrients: OFFMacronutrientsSchema | None = Field(
        default=None, validation_alias="nutriments"
    )
    ingredients: list[OFFIngredientSchema] | None = Field(
        default=None, validation_alias="ingredients"
    )
    group_level_1: str | None = Field(default=None, validation_alias="pnns_groups_1")
    group_level_2: str | None = Field(default=None, validation_alias="pnns_groups_2")


# ---- ENUMS ----


class StatusEnum(str, Enum):
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


# If API returns an error (e.g., 500), we return this schema
class OFFAPIErrorSchema(Schema):
    error: str


# Form -----------------------------------------------------------------------
class MacronutrientsFormSchema(Schema):
    fat: float | None = Field(default=None, alias="macronutrients_fat_0")
    saturated_fat: float | None = Field(
        default=None,
        alias="macronutrients_saturated_fat_0",
    )
    carbohydrates: float | None = Field(
        default=None,
        alias="macronutrients_carbohydrates_0",
    )
    sugars: float | None = Field(
        default=None,
        alias="macronutrients_sugars_0",
    )
    fiber: float | None = Field(
        default=None,
        alias="macronutrients_fiber_0",
    )
    proteins: float | None = Field(
        default=None,
        alias="macronutrients_proteins_0",
    )


class ProductFormSchema(Schema):
    """Schema used to map product data into ProductForm initial data."""

    barcode: str
    name: str
    image_url: str | None = None
    description: str | None = None
    energy: int | None = None
    macronutrients_fat: float | None = Field(default=None, alias="macronutrients.fat")
    macronutrients_saturated_fat: float | None = Field(
        default=None,
        alias="macronutrients.saturated_fat",
    )
    macronutrients_carbohydrates: float | None = Field(
        default=None,
        alias="macronutrients.carbohydrates",
    )
    macronutrients_sugars: float | None = Field(
        default=None,
        alias="macronutrients.sugars",
    )
    macronutrients_fiber: float | None = Field(
        default=None,
        alias="macronutrients.fiber",
    )
    macronutrients_proteins: float | None = Field(
        default=None,
        alias="macronutrients.proteins",
    )
    group_level_1: str | None = None
    group_level_2: str | None = None

    model_config = {
        # Allow validating only by alias names
        "validate_by_name": False,
        "validate_by_alias": True,
        "extra": "ignore",
    }


def product_schema_to_form_data(
    product: OFFProductSchema,
) -> ProductFormSchema:
    return ProductFormSchema.model_validate(product, by_alias=True)
