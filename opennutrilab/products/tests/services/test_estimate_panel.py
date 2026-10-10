from decimal import Decimal

import pytest
from django.utils import translation

from opennutrilab.products.api.schemas.outbound import AdditiveOut
from opennutrilab.products.api.schemas.outbound import CheckOut
from opennutrilab.products.api.schemas.outbound import ConfidenceOut
from opennutrilab.products.api.schemas.outbound import DeclaredOut
from opennutrilab.products.api.schemas.outbound import EstimateOut
from opennutrilab.products.api.schemas.outbound import IngredientEstimateOut
from opennutrilab.products.api.schemas.outbound import IngredientNutrientOut
from opennutrilab.products.api.schemas.outbound import NutrientEstimateOut
from opennutrilab.products.api.schemas.outbound import PreparationOut
from opennutrilab.products.api.schemas.outbound import RangeOut
from opennutrilab.products.api.schemas.outbound import ReferenceOut
from opennutrilab.products.models import Nutrient
from opennutrilab.products.services.estimate_panel import estimate_panel
from opennutrilab.products.services.estimate_panel import ingredient_name
from opennutrilab.products.services.estimate_panel import walk_ingredients

D = Decimal


def catalogue(code: str, group: str, unit: str = "mg") -> None:
    """A nutrient of the catalogue: the tests' database has only the label's."""
    Nutrient.objects.get_or_create(
        code=code,
        defaults={"name_en": code, "name_fr": code, "unit": unit, "group": group},
    )


def rng(low: str, point: str, high: str | None) -> RangeOut:
    return RangeOut(low=D(low), point=D(point), high=None if high is None else D(high))


def ingredient(
    name: str,
    *,
    declared: str | None = None,
    estimated: RangeOut | None = None,
    parts: list[IngredientEstimateOut] | None = None,
) -> IngredientEstimateOut:
    return IngredientEstimateOut(
        reference=ReferenceOut.model_construct(id=1, name=name, status="curated"),
        declared=None if declared is None else D(declared),
        estimated=estimated,
        sub_ingredients=parts or [],
    )


def estimate_of(
    nutrients: list[NutrientEstimateOut] | None = None,
    ingredients: list[IngredientEstimateOut] | None = None,
    **fields: object,
) -> EstimateOut:
    return EstimateOut(
        barcode="1",
        used_nutrition=False,
        nutrients=nutrients or [],
        ingredients=ingredients or [],
        caveat="",
        **fields,  # pyright: ignore[reportArgumentType]
    )


def test_the_ingredients_are_one_list_in_the_order_of_the_label_with_their_depth():
    tree = [
        ingredient(
            "chocolate",
            declared="20",
            estimated=rng("19", "20", "21"),
            parts=[ingredient("cocoa", estimated=rng("5", "8", "10"))],
        ),
        ingredient("sugar", estimated=None),
    ]

    panel = estimate_panel(estimate_of(ingredients=tree))

    assert panel["ingredients"] == [
        {
            "name": "chocolate",
            "depth": 0,
            "declared": "20",
            "estimated": {"low": "19", "point": "20", "high": "21"},
            "added": None,
            "added_unit": None,
        },
        {
            "name": "cocoa",
            "depth": 1,
            "declared": None,
            "estimated": {"low": "5", "point": "8", "high": "10"},
            "added": None,
            "added_unit": None,
        },
        {
            "name": "sugar",
            "depth": 0,
            "declared": None,
            "estimated": None,
            "added": None,
            "added_unit": None,
        },
    ]


def test_an_ingredient_that_is_a_nutrient_comes_with_what_it_adds_and_its_unit():
    vitamin = IngredientEstimateOut(
        nutrient=IngredientNutrientOut.model_construct(
            code="vitamin_c", name="Vit C", unit="mg"
        ),
        added=rng("0", "20", "25.5"),
    )

    (row,) = estimate_panel(estimate_of(ingredients=[vitamin]))["ingredients"]

    assert row["added"] == {"low": "0", "point": "20", "high": "25.5"}
    assert row["added_unit"] == "mg"


def test_an_ingredient_is_named_whatever_kind_it_is():
    food = ingredient("sugar")
    preparation = IngredientEstimateOut(
        preparation=PreparationOut.model_construct(
            id=1, name="praline", status="curated"
        )
    )
    additive = IngredientEstimateOut(
        additive=AdditiveOut.model_construct(
            id=1,
            name="lecithins",
            code="E322",
            function="emulsifier",
            status="curated",
        )
    )
    nutrient = IngredientEstimateOut(
        nutrient=IngredientNutrientOut.model_construct(
            code="vitamin_d", name="Vit D", unit="µg"
        )
    )
    nothing = IngredientEstimateOut()

    assert [
        ingredient_name(i) for i in (food, preparation, additive, nutrient, nothing)
    ] == ["sugar", "praline", "lecithins", "Vit D", ""]


def test_the_tree_is_walked_depth_first():
    tree = [
        ingredient("a", parts=[ingredient("b", parts=[ingredient("c")])]),
        ingredient("d"),
    ]

    walked = [
        (depth, ingredient_name(found)) for depth, found in walk_ingredients(tree)
    ]

    assert walked == [(0, "a"), (1, "b"), (2, "c"), (0, "d")]


@pytest.mark.django_db
def test_a_nutrient_comes_with_its_group_its_figures_and_the_verdict_on_the_label():
    catalogue("iron", Nutrient.Group.MINERAL)
    found = NutrientEstimateOut(
        code="iron",
        name="Fer",
        unit="mg",
        estimated=rng("3", "4", "5"),
        coverage=rng("90", "95", "100"),
        confidence=ConfidenceOut(
            score=D("0.5"),
            coverage=D("0.95"),
            quality=D("0.8"),
            uncertainty=D("0.2"),
            agreement=None,
        ),
        declared=DeclaredOut(amount=D("1.5"), low=D("1.4"), high=D("1.6")),
        check=CheckOut(verdict="declared_below", gap=D("1.4"), constrained=False),
    )

    with translation.override("en"):
        panel = estimate_panel(estimate_of(nutrients=[found]))

    assert panel["nutrients"] == [
        {
            "code": "iron",
            "name": "Fer",
            "unit": "mg",
            "group": "mineral",
            "group_label": "Mineral",
            "estimated": {"low": "3", "point": "4", "high": "5"},
            "narrowed": False,
            "coverage": "95",
            "confidence": {
                "score": "0.5",
                "coverage": "0.95",
                "quality": "0.8",
                "uncertainty": "0.2",
                "agreement": None,
            },
            "declared": {
                "amount": "1.5",
                "low": "1.4",
                "high": "1.6",
                "tolerance_low": None,
                "tolerance_high": None,
            },
            "verdict": "declared_below",
            "constrained": False,
            "tolerated": False,
        }
    ]


@pytest.mark.django_db
def test_a_nutrient_the_label_declares_and_no_ingredient_gives_has_no_estimate():
    found = NutrientEstimateOut(
        code="salt",
        name="Sel",
        unit="g",
        declared=DeclaredOut(amount=D("0.107"), low=D("0.1065"), high=D("0.1075")),
        check=CheckOut(verdict="not_estimated", gap=D(0), constrained=False),
    )

    (nutrient,) = estimate_panel(estimate_of(nutrients=[found]))["nutrients"]

    assert nutrient["estimated"] is None
    assert nutrient["coverage"] is None
    assert nutrient["confidence"] is None
    assert nutrient["verdict"] == "not_estimated"
    # Salt is no vitamin nor mineral: the catalogue puts it with the others.
    assert nutrient["group"] == Nutrient.objects.get(code="salt").group == "other"


@pytest.mark.django_db
def test_a_nutrient_with_no_label_has_no_verdict_and_one_the_estimate_used_is_marked():
    catalogue("vitamin_c", Nutrient.Group.VITAMIN)
    plain = NutrientEstimateOut(
        code="vitamin_c", name="C", unit="mg", estimated=rng("1", "2", None)
    )
    used = NutrientEstimateOut(
        code="fat",
        name="Fat",
        unit="g",
        estimated=rng("1", "2", "3"),
        check=CheckOut(verdict="agrees", gap=D(0), constrained=True),
    )

    found = estimate_panel(estimate_of(nutrients=[plain, used]))["nutrients"]

    assert (found[0]["verdict"], found[0]["constrained"]) == (None, False)
    assert found[0]["estimated"]["high"] is None
    assert (found[1]["verdict"], found[1]["constrained"]) == ("agrees", True)


@pytest.mark.django_db
def test_a_nutrient_read_with_the_tolerance_is_marked_with_the_bounds_it_stands_for():
    found = NutrientEstimateOut(
        code="saturated_fat",
        name="Saturés",
        unit="g",
        estimated=rng("13.7", "13.8", "13.9"),
        declared=DeclaredOut(
            amount=D("13"),
            low=D("12.5"),
            high=D("13.5"),
            tolerance_low=D("9.9"),
            tolerance_high=D("16.1"),
        ),
        check=CheckOut(verdict="agrees", gap=D(0), constrained=True, tolerated=True),
    )

    (nutrient,) = estimate_panel(estimate_of(nutrients=[found]))["nutrients"]

    assert nutrient["tolerated"] is True
    assert nutrient["declared"]["tolerance_low"] == "9.9"
    assert nutrient["declared"]["tolerance_high"] == "16.1"


@pytest.mark.django_db
def test_the_unit_of_the_label_and_the_density_that_converts_it_come_with_the_panel():
    panel = estimate_of(label_unit="ml", density=rng("0.908", "0.9115", "0.915"))

    found = estimate_panel(panel)

    assert found["label_unit"] == "ml"
    assert found["density"] == {"low": "0.908", "point": "0.9115", "high": "0.915"}


@pytest.mark.django_db
def test_a_panel_with_no_density_says_so():
    found = estimate_panel(estimate_of())

    assert (found["label_unit"], found["density"]) == ("g", None)


@pytest.mark.django_db
def test_a_nutrient_that_is_not_in_the_catalogue_goes_with_the_others():
    found = NutrientEstimateOut(code="mystery", name="?", unit="g")

    (nutrient,) = estimate_panel(estimate_of(nutrients=[found]))["nutrients"]

    assert nutrient["group"] == "other"


@pytest.mark.django_db
def test_the_nutrients_keep_the_order_they_are_given_in():
    catalogue("iron", Nutrient.Group.MINERAL)
    catalogue("vitamin_c", Nutrient.Group.VITAMIN)
    found = [
        NutrientEstimateOut(code=code, name=code, unit="g")
        for code in ("iron", "fat", "vitamin_c")
    ]

    names = [
        n["code"] for n in estimate_panel(estimate_of(nutrients=found))["nutrients"]
    ]

    assert names == ["iron", "fat", "vitamin_c"]
