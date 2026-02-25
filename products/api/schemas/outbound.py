from datetime import datetime

from django.db.models import QuerySet
from ninja import Field
from ninja import ModelSchema
from ninja import Schema
from pydantic import AliasPath

from products.api.types import QuantityType
from products.models import Ingredient
from products.models import IngredientRef
from products.models import Product
from products.models import ProductMacronutrient

# More information on : Regulation (EU) No 1169/2011
# https://eur-lex.europa.eu/eli/reg/2011/1169/oj?locale=fr


# --- Ingredient Reference Schemas ---


class IngredientRefOut(ModelSchema):
    class Meta:
        model = IngredientRef
        fields = ["name"]


class IngredientOut(ModelSchema):
    name: str
    percentage: QuantityType | None = None

    # https://django-ninja.dev/guides/response/?h=self#self-referencing-schemes
    sub_ingredients: list["IngredientOut"] = []
    reference: IngredientRefOut | None = None

    class Meta:
        model = Ingredient
        fields: list[str] = ["name", "percentage", "reference", "has_reference"]


IngredientOut.model_rebuild()  # Important for self-referencing schemas


class ProductMacronutrientOut(ModelSchema):
    # We tell Pydantic to look deep into the related 'macronutrient' object
    name: str = Field(validation_alias=AliasPath("macronutrient", "name"))
    description: str | None = Field(
        default=None, validation_alias=AliasPath("macronutrient", "description")
    )

    # Ici, amount est bien présent dans le modèle ProductMacronutrient
    amount: QuantityType | None = None

    class Meta:
        model = ProductMacronutrient
        fields = ["amount"]  # amount vient de ProductMacronutrient


class NutritionalValuesOut(Schema):
    """
    A simple wrapper schema to group energy and macronutrients together.
    """

    energy: QuantityType
    macronutrients: list[ProductMacronutrientOut] = []


class ProductOut(ModelSchema):
    # Issue field ordering : https://github.com/vitalik/django-ninja/issues/1504
    # So we manually define the fields in the desired order, instead of relying on
    # ModelSchema's automatic field generation.
    barcode: str
    name: str
    image: str | None = None
    description: str
    created_at: datetime
    group_level_1: str
    group_level_2: str

    nutritional_values: NutritionalValuesOut

    # Field name is exactly the same as the related_name in the Product model,
    # so that Django Ninja can automatically resolve it.
    ingredients: list[IngredientOut] = []

    class Meta:
        model = Product
        fields: list[str] = [
            "barcode",
            "name",
            "image",
            "description",
            "created_at",
            "group_level_1",
            "group_level_2",
        ]

    @staticmethod
    def resolve_ingredients(obj: Product) -> QuerySet[Ingredient]:
        return obj.ingredients.filter(parent__isnull=True).all()

    @staticmethod
    def resolve_nutritional_values(obj: Product) -> NutritionalValuesOut:
        """
        Combines the energy field from Product and the prefetched macronutrients.
        """
        return {  # pyright: ignore[reportUnknownVariableType, reportReturnType]
            "energy": obj.energy,  # pyright: ignore[reportUnknownMemberType]
            "macronutrients": list[ProductMacronutrient](
                obj.productmacronutrient_set.all()
            ),
        }
