from datetime import datetime
from decimal import Decimal

from django.db.models import QuerySet
from ninja import ModelSchema
from ninja import Schema

from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductNutrient

# More information on : Regulation (EU) No 1169/2011
# https://eur-lex.europa.eu/eli/reg/2011/1169/oj?locale=fr


class IngredientOut(ModelSchema):
    name: str
    # As declared on the label.
    percentage: Decimal | None = None
    off_id: str
    off_ciqual_food_code: str
    off_ciqual_proxy_food_code: str
    # The curated reference ingredient it is linked to, by name.
    reference: str | None = None

    # https://django-ninja.dev/guides/response/?h=self#self-referencing-schemes
    sub_ingredients: list["IngredientOut"] = []

    class Meta:
        model = Ingredient
        fields: list[str] = [
            "name",
            "percentage",
            "off_id",
            "off_ciqual_food_code",
            "off_ciqual_proxy_food_code",
        ]

    @staticmethod
    def resolve_reference(obj: Ingredient) -> str | None:
        return obj.reference.name_fr if obj.reference else None


IngredientOut.model_rebuild()  # Important for self-referencing schemas


class DeclaredNutrientOut(Schema):
    """One value of the nutrition label, per 100 g."""

    code: str
    name: str
    unit: str
    amount: Decimal

    @staticmethod
    def resolve_code(obj: ProductNutrient) -> str:
        return obj.nutrient.code

    @staticmethod
    def resolve_name(obj: ProductNutrient) -> str:
        return obj.nutrient.name

    @staticmethod
    def resolve_unit(obj: ProductNutrient) -> str:
        return obj.nutrient.unit


class ProductListItemOut(ModelSchema):
    """A product as a list shows it."""

    class Meta:
        model = Product
        fields: list[str] = ["barcode", "name", "created_at"]


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

    # Values declared on the label, in catalogue order.
    nutrients: list[DeclaredNutrientOut] = []

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
        return obj.ingredients.filter(parent__isnull=True).select_related("reference")

    @staticmethod
    def resolve_nutrients(obj: Product) -> QuerySet[ProductNutrient]:
        return obj.declared_nutrients.select_related("nutrient")
