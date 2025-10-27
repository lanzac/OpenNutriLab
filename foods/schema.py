from ninja import Field
from ninja import Schema


class MacronutrientsSchema(Schema):
    fat: float | None = None
    saturated_fat: float | None = None
    carbohydrates: float | None = None
    sugars: float | None = None
    fiber: float | None = None
    proteins: float | None = None


class ProductSchema(Schema):
    barcode: str
    name: str
    image_url: str | None = None
    description: str | None = None
    energy: int | None = None
    macronutrients: MacronutrientsSchema


class ProductFormSchema(Schema):
    """Schema used to map product data into FoodForm initial data."""

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


def product_schema_to_form_data(product: ProductSchema) -> ProductFormSchema:
    return ProductFormSchema.model_validate(product, by_alias=True)
