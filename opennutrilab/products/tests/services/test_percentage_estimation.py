from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.utils import translation

from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.derived_nutrients import ensure_derivations
from opennutrilab.products.services.percentage_estimation import NUTRIENTS
from opennutrilab.products.services.percentage_estimation import Interval
from opennutrilab.products.services.percentage_estimation import Node
from opennutrilab.products.services.percentage_estimation import PercentageEstimate
from opennutrilab.products.services.percentage_estimation import Problem
from opennutrilab.products.services.percentage_estimation import Range
from opennutrilab.products.services.percentage_estimation import (
    _macronutrients,  # pyright: ignore[reportPrivateUsage]
)
from opennutrilab.products.services.percentage_estimation import estimate
from opennutrilab.products.services.percentage_estimation import estimate_percentages
from opennutrilab.products.services.reference_composition import Estimate

D = Decimal
CONSTITUENTS_FILE = Path(__file__).parents[1] / "data" / "ciqual_const_2025.xml"
# The cents the intervals are given in.
CENT = 0.011


def node(
    key: int,
    parent: int | None = None,
    declared: str | None = None,
    protein: Range | None = None,
) -> Node:
    return Node(
        key=key,
        parent=parent,
        name=f"ingredient {key}",
        declared=None if declared is None else D(declared),
        composition=None if protein is None else {"proteins": protein},
    )


def span(interval: Interval) -> tuple[float, float]:
    return float(interval.low), float(interval.high)


def shares(result: PercentageEstimate, *keys: int) -> list[tuple[float, float]]:
    return [span(result.percentages[key]) for key in keys]


def assert_spans(
    result: PercentageEstimate, expected: Mapping[int, tuple[float, float]]
) -> None:
    for key, (low, high) in expected.items():
        found = span(result.percentages[key])
        assert abs(found[0] - low) <= CENT, (key, found, (low, high))
        assert abs(found[1] - high) <= CENT, (key, found, (low, high))


# ----------------------------------------------------------------------------
# What a list of ingredients says on its own
# ----------------------------------------------------------------------------
def test_a_declared_percentage_is_known_to_its_rounding():
    result = estimate([node(1, declared="60"), node(2, declared="40")], {})

    assert_spans(result, {1: (59.5, 60.5), 2: (39.5, 40.5)})


def test_declared_percentages_need_not_add_up_to_100_when_all_are_declared():
    result = estimate([node(1, declared="60"), node(2, declared="39.4")], {})

    assert_spans(result, {1: (59.5, 60.5), 2: (39.35, 39.45)})


def test_with_no_percentage_the_order_is_all_there_is():
    result = estimate([node(1), node(2)], {})

    assert_spans(result, {1: (50, 100), 2: (0, 50)})
    # The mean of the two extreme combinations, (50, 50) and (100, 0).
    assert (result.percentages[1].point, result.percentages[2].point) == (D(75), D(25))


def test_what_is_left_after_the_declared_ones_is_for_the_others():
    result = estimate([node(1, declared="60"), node(2), node(3, declared="10")], {})

    assert_spans(result, {2: (29, 31)})


def test_the_sub_ingredients_add_up_to_their_parent():
    result = estimate([node(1, declared="40"), node(2, 1), node(3, 1)], {})

    assert_spans(result, {2: (19.75, 40.5), 3: (0, 20.25)})


def test_a_sub_ingredients_percentage_is_a_share_of_its_parent():
    """Dattes 50 % (dattes, farine de riz 20 %): the flour is a fifth of the 50.

    So it is 19.5 % of 49.5 at least and 20.5 % of 50.5 at most, not 20 +- 0.5 of
    the whole product.
    """
    result = estimate(
        [node(1, declared="50"), node(2, 1), node(3, 1, declared="20")], {}
    )

    assert_spans(result, {3: (9.65, 10.36), 2: (39.35, 40.66)})


def test_a_declared_percentage_keeps_its_own_figure_as_the_point():
    result = estimate([node(1, declared="31"), node(2), node(3), node(4)], {})

    assert result.percentages[1].point == D(31)


def test_an_ingredient_without_a_composition_does_not_stop_the_shares():
    result = estimate([node(1), node(2)], {"proteins": (14.5, 15.5)})

    assert_spans(result, {1: (50, 100), 2: (0, 50)})
    assert [w.problem for w in result.warnings] == [Problem.NO_COMPOSITION]
    assert result.warnings[0].detail == "ingredient 1, ingredient 2"
    assert not result.used_nutrition


def test_a_product_that_declares_no_nutrition_is_estimated_without_it():
    result = estimate([node(1, protein=(20, 20)), node(2, protein=(10, 10))], {})

    assert [w.problem for w in result.warnings] == [Problem.NO_NUTRITION]
    assert not result.used_nutrition


def test_declared_percentages_that_cannot_all_hold_give_no_estimate():
    result = estimate([node(1, declared="70"), node(2, declared="50"), node(3)], {})

    assert result.percentages == {}
    assert Problem.IMPOSSIBLE in [w.problem for w in result.warnings]


def test_an_order_the_declared_percentages_contradict_gives_no_estimate():
    result = estimate([node(1, declared="10"), node(2, declared="30"), node(3)], {})

    assert result.percentages == {}
    assert Problem.IMPOSSIBLE in [w.problem for w in result.warnings]


def test_a_product_with_no_ingredient_has_nothing_to_estimate():
    assert estimate([], {"proteins": (14.5, 15.5)}) == PercentageEstimate(
        {}, [], used_nutrition=False
    )


# ----------------------------------------------------------------------------
# What the nutrition of the product adds
# ----------------------------------------------------------------------------
def test_the_nutrition_of_the_product_narrows_the_shares():
    # 20 g of protein per 100 g in the first, 10 in the second; the product has
    # 15, so they are about half each, the first being the larger.
    result = estimate(
        [node(1, protein=(20, 20)), node(2, protein=(10, 10))],
        {"proteins": (14.5, 15.5)},
    )

    assert_spans(result, {1: (50, 55), 2: (45, 50)})
    assert result.used_nutrition
    assert result.warnings == []


def test_the_interval_of_a_composition_is_used_and_not_only_its_amount():
    result = estimate(
        [node(1, protein=(18, 22)), node(2, protein=(10, 10))],
        {"proteins": (14.5, 15.5)},
    )

    # At the lowest protein of the first, it can be 68.75 % of the product, and at
    # the highest, 37.5 % is enough, but it is the larger of the two.
    assert_spans(result, {1: (50, 68.75), 2: (31.25, 50)})


def test_the_composition_that_counts_is_the_coarsest_that_there_is():
    # The parent has 10 g of protein, its sub-ingredient 50: a label of 15 g is
    # possible with the parent's (50 % x 10 + 50 % x 20) and not with the other's.
    nodes = [
        node(1, declared="50", protein=(10, 10)),
        node(2, 1, protein=(50, 50)),
        node(3, protein=(20, 20)),
    ]

    result = estimate(nodes, {"proteins": (14.5, 15.5)})

    assert result.used_nutrition
    assert result.warnings == []


def test_the_sub_ingredients_are_used_when_the_parent_has_no_composition():
    nodes = [
        node(1, declared="50"),
        node(2, 1, protein=(10, 10)),
        node(3, protein=(20, 20)),
    ]

    result = estimate(nodes, {"proteins": (14.5, 15.5)})

    assert result.used_nutrition
    assert result.warnings == []


def test_a_sub_ingredient_with_no_composition_blocks_a_parent_with_none():
    nodes = [node(1, declared="50"), node(2, 1, protein=(10, 10)), node(3, 1)]

    result = estimate([*nodes, node(4, protein=(20, 20))], {"proteins": (14.5, 15.5)})

    assert [w.problem for w in result.warnings] == [Problem.NO_COMPOSITION]
    assert result.warnings[0].detail == "ingredient 3"


def test_a_nutrition_the_compositions_cannot_give_is_set_aside_and_named():
    result = estimate(
        [node(1, protein=(20, 20)), node(2, protein=(10, 10))],
        {"proteins": (40, 41)},
        {"proteins": "Protéines"},
    )

    assert [w.problem for w in result.warnings] == [Problem.LABEL_DISAGREES]
    assert result.warnings[0].detail == "Protéines"
    assert not result.used_nutrition
    # What the list says is still there.
    assert_spans(result, {1: (50, 100), 2: (0, 50)})


def test_only_the_nutrients_that_disagree_are_named():
    nodes = [
        Node(1, None, "one", None, {"proteins": (20, 20), "fat": (5, 5)}),
        Node(2, None, "two", None, {"proteins": (10, 10), "fat": (5, 5)}),
    ]

    result = estimate(nodes, {"proteins": (14.5, 15.5), "fat": (30, 31)})

    assert result.warnings[0].problem == Problem.LABEL_DISAGREES
    assert result.warnings[0].detail == "fat"
    # The codes come with the names, for what reads them (estimate_validation).
    assert result.warnings[0].codes == ("fat",)


# ----------------------------------------------------------------------------
# A composition as the nutrition rules take it
# ----------------------------------------------------------------------------
def _estimate(low: str, high: str | None) -> Estimate:
    return Estimate(
        amount=D(low),
        low=D(low),
        high=None if high is None else D(high),
        qualifier=SourceFoodNutrient.Qualifier.EXACT,
        grades=(),
        foods=(),
    )


def _composition(**codes: Estimate) -> dict[str, Estimate]:
    return {"fat": _estimate("1", "2"), "carbohydrates": _estimate("40", "50"), **codes}


def test_a_composition_without_the_main_nutrients_has_none():
    assert _macronutrients({"fat": _estimate("1", "2")}, {}) is None


def test_a_nutrient_a_food_lacks_is_at_most_the_one_it_is_part_of():
    composition = _composition(proteins=_estimate("10", "12"))
    parents = {"sugars": Nutrient(code="sugars", parent_id="carbohydrates")}

    ranges = _macronutrients(composition, parents)

    assert ranges is not None
    assert ranges["sugars"] == (0, 50)
    assert ranges["fiber"] == (0, 100)
    assert set(ranges) == set(NUTRIENTS)


def test_traces_are_somewhere_from_nothing_to_the_100_g_given_for():
    composition = _composition(proteins=_estimate("0", None))

    ranges = _macronutrients(composition, {})

    assert ranges is not None
    assert ranges["proteins"] == (0, 100)


# ----------------------------------------------------------------------------
# From a product in the database
# ----------------------------------------------------------------------------
@pytest.fixture
def source(db: None) -> Source:
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    ensure_derivations()
    return Source.objects.create(code="ciqual-2025", name="Ciqual", version="2025")


def reference(source: Source, code: str, **amounts: str) -> ReferenceIngredient:
    food = SourceFood.objects.create(
        source=source, code=code, name_fr=f"Aliment {code}"
    )
    for nutrient in ("fat", "carbohydrates", "proteins"):
        SourceFoodNutrient.objects.create(
            food=food,
            nutrient=Nutrient.objects.get(code=nutrient),
            amount=D(amounts.get(nutrient, "0")),
            confidence="A",
        )
    ref = ReferenceIngredient.objects.create(
        name_en=f"reference {code}", name_fr=f"fiche {code}"
    )
    ref.source_foods.add(food)
    return ref


def product_with(*, proteins: str | None) -> Product:
    product = Product.objects.create(barcode="3229820794556", name="Muesli")
    if proteins is not None:
        ProductNutrient.objects.create(
            product=product,
            nutrient=Nutrient.objects.get(code="proteins"),
            amount=D(proteins),
        )
    return product


def add(
    product: Product,
    ref: ReferenceIngredient,
    parent: Ingredient | None = None,
    percentage: str | None = None,
) -> Ingredient:
    return Ingredient.objects.create(
        product=product,
        reference=ref,
        parent=parent,
        percentage=None if percentage is None else D(percentage),
    )


def test_the_shares_of_a_product_are_read_from_its_ingredients_and_its_label(
    source: Source,
):
    oats = reference(source, "1", proteins="20")
    rice = reference(source, "2", proteins="10")
    product = product_with(proteins="15")
    first, second = add(product, oats), add(product, rice)

    result = estimate_percentages(product)

    # Each protein is itself known to its rounding: 19.5-20.5 and 9.5-10.5.
    assert_spans(result, {first.id: (50, 60), second.id: (40, 50)})
    assert result.used_nutrition
    assert result.warnings == []


def test_a_reference_with_no_composition_is_named_in_the_warning(source: Source):
    oats = reference(source, "1", proteins="20")
    unknown = ReferenceIngredient.objects.create(name_fr="fiche vide", name_en="empty")
    product = product_with(proteins="15")
    add(product, oats)
    add(product, unknown)

    result = estimate_percentages(product)

    assert [w.problem for w in result.warnings] == [Problem.NO_COMPOSITION]
    assert result.warnings[0].detail == "empty"


def test_a_product_with_no_declared_macronutrient_is_estimated_without_them(
    source: Source,
):
    product = product_with(proteins=None)
    add(product, reference(source, "1", proteins="20"))
    add(product, reference(source, "2", proteins="10"))

    result = estimate_percentages(product)

    assert [w.problem for w in result.warnings] == [Problem.NO_NUTRITION]


def test_a_disagreeing_label_is_named_in_the_language_served(source: Source):
    product = product_with(proteins="40")
    add(product, reference(source, "1", proteins="20"))
    add(product, reference(source, "2", proteins="10"))

    with translation.override("fr"):
        result = estimate_percentages(product)

    assert result.warnings[0].problem == Problem.LABEL_DISAGREES
    assert result.warnings[0].detail == Nutrient.objects.get(code="proteins").name_fr


def test_a_product_is_estimated_in_a_few_queries_however_many_ingredients(
    source: Source, django_assert_max_num_queries: Any
):
    product = product_with(proteins="15")
    for index in range(6):
        add(product, reference(source, str(index), proteins=str(10 + index)))

    # The ingredients, the nutrients, the derivations (two), the label, and a read
    # of the foods' values for each reference.
    with django_assert_max_num_queries(5 + 6):
        estimate_percentages(product)


def preparation(
    source: Source, code: str, pk: int | None = None, **amounts: str
) -> Preparation:
    """A preparation that draws on a food with these amounts, like `reference`."""
    food = SourceFood.objects.create(source=source, code=code)
    for nutrient in ("fat", "carbohydrates", "proteins"):
        SourceFoodNutrient.objects.create(
            food=food,
            nutrient=Nutrient.objects.get(code=nutrient),
            amount=D(amounts.get(nutrient, "0")),
            confidence="A",
        )
    prepared = Preparation.objects.create(pk=pk, name_en=f"preparation {code}")
    prepared.source_foods.add(food)
    return prepared


def test_a_preparation_counts_by_its_source_foods_as_a_reference_does(source: Source):
    oats = reference(source, "1", proteins="20")
    mozzarella = preparation(source, "2", proteins="10")
    product = product_with(proteins="15")
    first = add(product, oats)
    second = Ingredient.objects.create(product=product, preparation=mozzarella)

    result = estimate_percentages(product)

    assert_spans(result, {first.id: (50, 60), second.id: (40, 50)})
    assert result.used_nutrition
    assert result.warnings == []


def test_a_preparation_with_no_composition_is_named_in_the_warning(source: Source):
    product = product_with(proteins="15")
    add(product, reference(source, "1", proteins="20"))
    Ingredient.objects.create(
        product=product, preparation=Preparation.objects.create(name_en="gnocchi")
    )

    result = estimate_percentages(product)

    assert [w.problem for w in result.warnings] == [Problem.NO_COMPOSITION]
    assert result.warnings[0].detail == "gnocchi"


def test_a_preparation_and_a_reference_with_the_same_id_are_not_confused(
    source: Source,
):
    """Their compositions are looked up by kind and id, not by id alone."""
    reference_row = reference(source, "1", proteins="20")
    preparation_row = preparation(source, "2", pk=reference_row.pk, proteins="10")
    assert reference_row.pk == preparation_row.pk
    product = product_with(proteins="15")
    first = add(product, reference_row)
    second = Ingredient.objects.create(product=product, preparation=preparation_row)

    result = estimate_percentages(product)

    assert_spans(result, {first.id: (50, 60), second.id: (40, 50)})
