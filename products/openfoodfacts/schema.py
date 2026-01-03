# https://world.openfoodfacts.org/files/redocly/api-v3.redoc-static.html#schema/shape
from ninja import Field
from ninja import Schema
from pydantic import AliasPath
from pydantic import ConfigDict

from products.base_schema import IngredientRef
from products.base_schema import IngredientSchema
from products.base_schema import IngredientType
from products.base_schema import MacronutrientsSchema
from products.base_schema import MacronutrientsType
from products.base_schema import ProductSchema

# OpenFoodFacts data mapping -------------------------------------------------


class OFFIngredientSchema(IngredientSchema["OFFIngredientSchema"]):
    model_config = ConfigDict(
        from_attributes=True,  # allows to create from Django objects
        populate_by_name=True,  # allow us to use names even with alias defined
        extra="ignore",  # ignore _state, id, product_id, etc
    )

    name: str = Field(default="", alias="text")
    percentage: float | None = Field(default=None, alias="percent")
    # https://django-ninja.dev/guides/response/?h=self#self-referencing-schemes
    ingredients: list["OFFIngredientSchema"] | None = Field(
        default=None, alias="ingredients"
    )
    reference: IngredientRef | None = Field(default=None)
    has_reference: bool = False


OFFIngredientSchema.model_rebuild()


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


class OFFProductSchema(ProductSchema[OFFMacronutrientsSchema, OFFIngredientSchema]):
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
    product: ProductSchema[MacronutrientsType, IngredientType] | OFFProductSchema,
) -> ProductFormSchema:
    return ProductFormSchema.model_validate(product, by_alias=True)
