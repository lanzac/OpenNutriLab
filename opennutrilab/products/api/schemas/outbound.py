from datetime import datetime
from decimal import Decimal

from django.db.models import Prefetch
from django.db.models import QuerySet
from ninja import ModelSchema
from ninja import Schema

from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Preparation
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


class PreparationOut(ModelSchema):
    """The preparation an ingredient is, named in the language served."""

    name: str

    class Meta:
        model = Preparation
        fields: list[str] = ["id", "status"]


# How many levels of sub-ingredients a product's tree is loaded with in one go.
SUB_INGREDIENT_LEVELS = 3


class IngredientOut(Schema):
    # As declared on the label.
    percentage: Decimal | None = None
    # One of the two: a true ingredient, or what is made of several.
    reference: ReferenceOut | None = None
    preparation: PreparationOut | None = None

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


class RangeOut(Schema):
    """
    An estimated figure with its range: `point` is within `low` and `high`.

    Percentages of the product, per 100 g amounts and coverage all come this way.
    `high` is None when no upper end is known, which happens for a nutrient only
    some of the ingredients give.
    """

    low: Decimal
    point: Decimal
    high: Decimal | None = None


class DeclaredOut(Schema):
    """What the label declares of a nutrient, with the rounding it is written with."""

    amount: Decimal
    low: Decimal
    high: Decimal


class CheckOut(Schema):
    """The declared figure set against the estimate (see estimate_validation)."""

    # agrees, declared_below, declared_above or not_estimated.
    verdict: str
    # How far apart the two intervals are, in the nutrient's unit: 0 when they meet.
    gap: Decimal
    # The label's figure was one of the rules the shares were worked out with, so
    # it agrees by construction and confirms nothing.
    constrained: bool
    # What it was compared with. For a nutrient read more than one way (vitamin A)
    # this holds all the readings, so it is wider than `estimated`.
    compared_low: Decimal | None = None
    compared_high: Decimal | None = None


class ConfidenceOut(Schema):
    """
    How far to trust an estimated nutrient: four parts between 0 and 1, and
    their product.
    """

    score: Decimal
    coverage: Decimal
    quality: Decimal
    uncertainty: Decimal
    # None when no independent check could have failed.
    agreement: Decimal | None = None


class ReadingOut(Schema):
    """Another way to read a nutrient, which a label's figure may follow."""

    name: str
    estimated: RangeOut


class NutrientEstimateOut(Schema):
    """One nutrient of the product, per 100 g, in `unit`."""

    code: str
    name: str
    unit: str
    # None for a nutrient the label declares and no ingredient gives.
    estimated: RangeOut | None = None
    # The share of the product, in percent, whose ingredients give a value.
    coverage: RangeOut | None = None
    confidence: ConfidenceOut | None = None
    declared: DeclaredOut | None = None
    check: CheckOut | None = None
    other_readings: list[ReadingOut] = []


class IngredientEstimateOut(Schema):
    # One of the two, as in IngredientOut.
    reference: ReferenceOut | None = None
    preparation: PreparationOut | None = None
    # As on the label: None when it gives none. Never estimated.
    declared: Decimal | None = None
    # The share of the whole product, a sub-ingredient's included. For a declared
    # one it is the declared interval, narrowed by what the rest says. None only
    # when the label contradicts itself and nothing could be estimated.
    estimated: RangeOut | None = None
    sub_ingredients: list["IngredientEstimateOut"] = []


IngredientEstimateOut.model_rebuild()


class WarningOut(Schema):
    """Something to say of the estimate that is not a figure. Never blocking."""

    problem: str
    message: str
    # The nutrients it is about, by code.
    nutrients: list[str] = []


class SourceOut(Schema):
    """A source of composition data the estimate draws on, and how to credit it."""

    code: str
    name: str
    version: str
    url: str
    # What the licence requires to be shown wherever its data is used.
    attribution: str


class EstimateOut(Schema):
    """
    What a product's ingredients say of its nutrients, with how far to trust it.

    Every figure is an interval, and the label's own are never changed: the
    declared and the estimated are different fields.
    """

    barcode: str
    # Whether the nutrition of the label narrowed the shares of the ingredients.
    used_nutrition: bool
    warnings: list[WarningOut] = []
    # Catalogue order. The nutrients the label declares come with it, estimated
    # or not.
    nutrients: list[NutrientEstimateOut] = []
    # The top-level ingredients, in the order of the label.
    ingredients: list[IngredientEstimateOut] = []
    sources: list[SourceOut] = []
    # What the estimate does not account for.
    caveat: str


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
    # The label's list of ingredients, as it was when the ingredients were loaded.
    ingredients_text: str

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
            "ingredients_text",
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
                queryset=Ingredient.objects.select_related("reference", "preparation"),
            )
            for depth in range(1, SUB_INGREDIENT_LEVELS + 1)
        ]
        return (
            obj.ingredients.filter(parent__isnull=True)
            .select_related("reference", "preparation")
            .prefetch_related(*levels)
        )

    @staticmethod
    def resolve_nutrients(obj: Product) -> QuerySet[ProductNutrient]:
        return obj.declared_nutrients.select_related("nutrient")
