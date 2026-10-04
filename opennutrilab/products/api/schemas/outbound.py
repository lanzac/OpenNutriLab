from datetime import datetime
from decimal import Decimal

from django.db.models import Prefetch
from django.db.models import QuerySet
from ninja import ModelSchema
from ninja import Schema

from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.models import ReferenceIngredient

# More information on : Regulation (EU) No 1169/2011
# https://eur-lex.europa.eu/eli/reg/2011/1169/oj?locale=fr


class ReferenceOut(ModelSchema):
    """The reference ingredient an ingredient is, named in the language served."""

    name: str

    class Meta:
        model = ReferenceIngredient
        fields: list[str] = ["id", "status"]


# How many levels of sub-ingredients a product's tree is loaded with in one go.
SUB_INGREDIENT_LEVELS = 3


class IngredientOut(Schema):
    # As declared on the label.
    percentage: Decimal | None = None
    reference: ReferenceOut

    # https://django-ninja.dev/guides/response/?h=self#self-referencing-schemes
    # Read from the related manager, with no resolver: below the first level
    # ninja hands a resolver an object it has already wrapped, and the
    # AttributeError that follows reads as "field missing", so the children
    # would silently be [] (see ProductOut.resolve_ingredients for how they
    # are loaded).
    sub_ingredients: list["IngredientOut"] = []


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
        """
        The top-level ingredients, with their references and sub-ingredients.

        A tree is read one level per query, however many ingredients it has,
        down to the depth labels reach in practice; anything deeper is loaded
        lazily.
        """
        path = "sub_ingredients"
        levels: list[Prefetch[Ingredient]] = [
            Prefetch(
                "__".join([path] * depth),
                queryset=Ingredient.objects.select_related("reference"),
            )
            for depth in range(1, SUB_INGREDIENT_LEVELS + 1)
        ]
        return (
            obj.ingredients.filter(parent__isnull=True)
            .select_related("reference")
            .prefetch_related(*levels)
        )

    @staticmethod
    def resolve_nutrients(obj: Product) -> QuerySet[ProductNutrient]:
        return obj.declared_nutrients.select_related("nutrient")
