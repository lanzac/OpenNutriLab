from typing import Generic
from typing import TypeVar

from ninja import Field
from ninja import Schema

MacronutrientsType = TypeVar("MacronutrientsType", bound="MacronutrientsSchema")
IngredientType = TypeVar("IngredientType", bound="IngredientSchema")  # pyright: ignore[reportMissingTypeArgument]


# More information on : Regulation (EU) No 1169/2011
# https://eur-lex.europa.eu/eli/reg/2011/1169/oj?locale=fr
class MacronutrientsSchema(Schema):
    fat: float | None = None
    saturated_fat: float | None = None
    carbohydrates: float | None = None
    sugars: float | None = None
    fiber: float | None = None
    proteins: float | None = None


T = TypeVar("T")


class IngredientRef(Schema):
    name: str


# need to rename ingredients to ingredient
class IngredientSchema(Schema, Generic[T]):  # noqa: UP046
    name: str = Field(default="", alias="text")
    # https://django-ninja.dev/guides/response/?h=self#self-referencing-schemes
    ingredients: list[T] | None = Field(default=None, alias="ingredients")
    reference: IngredientRef | None = Field(default=None)


IngredientSchema.model_rebuild()


class ProductSchema(Schema, Generic[MacronutrientsType, IngredientType]):  # noqa: UP046
    barcode: str
    name: str
    image_url: str | None = None
    description: str | None = None
    energy: int | None = None
    macronutrients: MacronutrientsType | None = None
    ingredients: list[IngredientType] | None = None
