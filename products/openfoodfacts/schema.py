from ninja import Field
from ninja import Schema
from pydantic import AliasPath

from products.base_schema import IngredientsSchema
from products.base_schema import IngredientsType
from products.base_schema import MacronutrientsSchema
from products.base_schema import MacronutrientsType
from products.base_schema import ProductSchema

# OpenFoodFacts data mapping -------------------------------------------------


class OFFIngredientsSchema(IngredientsSchema["OFFIngredientsSchema"]):
    name: str = Field(default="", alias="text")
    # https://django-ninja.dev/guides/response/?h=self#self-referencing-schemes
    ingredients: list["OFFIngredientsSchema"] | None = Field(
        default=None, alias="ingredients"
    )


OFFIngredientsSchema.model_rebuild()


class OFFMacronutrientsSchema(MacronutrientsSchema):
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


class OFFProductSchema(ProductSchema[OFFMacronutrientsSchema, OFFIngredientsSchema]):
    barcode: str = Field(validation_alias="_id")
    name: str = Field(default="", validation_alias="product_name")
    image_url: str | None = Field(default=None, validation_alias="image_small_url")
    description: str | None = Field(default=None, validation_alias="categories")
    energy: int | None = Field(
        default=None, validation_alias=AliasPath("nutriments", "energy_100g")
    )
    macronutrients: OFFMacronutrientsSchema | None = Field(
        default=None, validation_alias="nutriments"
    )
    ingredients: list[OFFIngredientsSchema] | None = Field(
        default=None, validation_alias="ingredients"
    )


# Form -----------------------------------------------------------------------
class MacronutrientsFormSchema(MacronutrientsSchema):
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

    model_config = {
        # Allow validating only by alias names
        "validate_by_name": False,
        "validate_by_alias": True,
        "extra": "ignore",
    }


def product_schema_to_form_data(
    product: ProductSchema[MacronutrientsType, IngredientsType] | OFFProductSchema,
) -> ProductFormSchema:
    return ProductFormSchema.model_validate(product, by_alias=True)
