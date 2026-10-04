from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.derived_nutrients import ensure_derivations
from opennutrilab.products.services.nutrient_estimation import NutrientAmount
from opennutrilab.products.services.nutrient_estimation import estimate_nutrients
from opennutrilab.products.services.nutrient_estimation import nutrients_of
from opennutrilab.products.services.percentage_estimation import Node
from opennutrilab.products.services.percentage_estimation import Problem
from opennutrilab.products.services.percentage_estimation import Range
from opennutrilab.products.services.percentage_estimation import solve_shares
from opennutrilab.products.services.reference_composition import Estimate

D = Decimal
EXACT = SourceFoodNutrient.Qualifier.EXACT
TRACES = SourceFoodNutrient.Qualifier.TRACES
CONSTITUENTS_FILE = Path(__file__).parents[1] / "data" / "ciqual_const_2025.xml"


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


def content(amount: str | None, low: str, high: str | None) -> Estimate:
    return Estimate(
        amount=None if amount is None else D(amount),
        low=D(low),
        high=None if high is None else D(high),
        qualifier=EXACT if amount is not None else TRACES,
        grades=(),
        foods=(),
    )


def worked_out(
    nodes: list[Node],
    compositions: list[dict[str, Estimate]],
    label: dict[str, Range] | None = None,
) -> dict[str, NutrientAmount]:
    return nutrients_of(solve_shares(nodes, label or {}), compositions)


def near(value: Decimal, expected: float, tolerance: float = 0.2) -> bool:
    return abs(float(value) - expected) <= tolerance


def figures(amount: NutrientAmount) -> tuple[Decimal, Decimal, Decimal | None]:
    return amount.amount, amount.low, amount.high


# Two ingredients, in this order and with nothing else said: the first is between
# half and all of the product, the second between none and half, and the mean of
# the extreme combinations, (50, 50) and (100, 0), is 75 and 25.
ORDER_ONLY = [node(1, protein=(0, 0)), node(2, protein=(0, 0))]


# ----------------------------------------------------------------------------
# How the shares and the contents combine
# ----------------------------------------------------------------------------
def test_a_nutrient_is_what_each_ingredient_brings_over_the_combinations_allowed():
    vitamin_c = [
        {"vitamin_c": content("10", "9", "11")},
        {"vitamin_c": content("20", "18", "22")},
    ]

    result = worked_out(ORDER_ONLY, vitamin_c)["vitamin_c"]

    # 75 % of 10 and 25 % of 20. At the least, all of the first at its lowest
    # (9); at the most, half and half at their highest (5.5 + 11).
    assert figures(result) == (D("12.5"), D(9), D("16.5"))
    assert result.coverage == (D(100), D(100), D(100))


def test_the_ends_are_not_the_ends_of_the_shares_taken_one_by_one():
    """The shares add up: the first at its most (100) is not the second at its
    most (50) too, so 100 x 11 + 50 x 22 over 100 is not the highest."""
    vitamin_c = [
        {"vitamin_c": content("10", "9", "11")},
        {"vitamin_c": content("20", "18", "22")},
    ]

    result = worked_out(ORDER_ONLY, vitamin_c)["vitamin_c"]

    assert result.high is not None
    assert result.high == D("16.5")
    assert result.high < D(22)


def test_the_nutrition_of_the_product_narrows_what_a_nutrient_can_be():
    # With 15 g of protein per 100 g, from 20 and 10, the first is 50 to 55 %.
    nodes = [node(1, protein=(20, 20)), node(2, protein=(10, 10))]
    vitamin_c = [
        {"vitamin_c": content("10", "10", "10")},
        {"vitamin_c": content("20", "20", "20")},
    ]

    result = worked_out(nodes, vitamin_c, {"proteins": (14.5, 15.5)})["vitamin_c"]

    # 10 A + 20 B over 100, with A between 50 and 55 and A + B = 100.
    assert figures(result) == (D("14.75"), D("14.5"), D("15"))


def test_declared_percentages_give_the_amount_and_the_rounding_around_it():
    nodes = [
        node(1, declared="60", protein=(0, 0)),
        node(2, declared="40", protein=(0, 0)),
    ]
    vitamin_c = [
        {"vitamin_c": content("10", "9", "11")},
        {"vitamin_c": content("20", "18", "22")},
    ]

    result = worked_out(nodes, vitamin_c)["vitamin_c"]

    # 60 x 10 + 40 x 20 is 14. At the least, 59.5 % of 9 and 39.5 % of 18.
    assert near(result.amount, 14, 0.1)
    assert (result.low, result.high) == (D("12.465"), D("15.565"))


def test_the_amount_is_always_within_its_interval():
    nodes = [node(i, protein=(0, 0)) for i in (1, 2, 3)]
    compositions = [
        {"zinc": content(str(amount), str(amount - 1), str(amount + 3))}
        for amount in (5, 12, 40)
    ]

    result = worked_out(nodes, compositions)["zinc"]

    assert result.high is not None
    assert result.low <= result.amount <= result.high


# ----------------------------------------------------------------------------
# Which composition counts
# ----------------------------------------------------------------------------
def test_the_coarsest_composition_of_a_branch_counts():
    nodes = [
        node(1, declared="50", protein=(0, 0)),
        node(2, 1, protein=(0, 0)),
        node(3, declared="50", protein=(0, 0)),
    ]
    compositions = [
        {"vitamin_c": content("10", "10", "10")},
        {"vitamin_c": content("1000", "1000", "1000")},  # The parent's say wins.
        {"vitamin_c": content("20", "20", "20")},
    ]

    result = worked_out(nodes, compositions)["vitamin_c"]

    assert near(result.amount, 15)
    assert result.high is not None
    assert result.high < D(20)
    assert near(result.coverage.point, 100, 1)


def test_sub_ingredients_count_when_their_parent_has_no_composition():
    nodes = [
        node(1, declared="50"),
        node(2, 1, protein=(0, 0)),
        node(3, 1, protein=(0, 0)),
        node(4, declared="50", protein=(0, 0)),
    ]
    compositions: list[dict[str, Estimate]] = [
        {},
        {"vitamin_c": content("10", "10", "10")},
        {"vitamin_c": content("30", "30", "30")},
        {"vitamin_c": content("20", "20", "20")},
    ]

    result = worked_out(nodes, compositions)["vitamin_c"]

    # The two children share the 50 in order, the larger first: 37.5 and 12.5 at
    # the point, with the 50 of the last.
    assert near(result.amount, 0.375 * 10 + 0.125 * 30 + 0.5 * 20)
    assert near(result.coverage.point, 100, 1)


# ----------------------------------------------------------------------------
# What is not known
# ----------------------------------------------------------------------------
def test_a_nutrient_one_ingredient_lacks_is_a_minimum_with_its_coverage():
    compositions: list[dict[str, Estimate]] = [
        {"vitamin_c": content("10", "9", "11")},
        {},
    ]

    result = worked_out(ORDER_ONLY, compositions)["vitamin_c"]

    # Only the first brings it, 75 % of the product at the point, 50 to 100 %.
    assert result.amount == D("7.5")
    assert result.low == D("4.5")
    assert result.high is None
    assert result.coverage == (D(50), D(75), D(100))


def test_a_nutrient_an_ingredient_lacks_is_at_most_the_one_it_is_part_of():
    compositions = [
        {"sugars": content("6", "5", "7"), "carbohydrates": content("30", "30", "30")},
        {"carbohydrates": content("20", "20", "20")},
    ]
    shares = solve_shares(ORDER_ONLY, {})

    result = nutrients_of(shares, compositions, {"sugars": "carbohydrates"})["sugars"]

    # The second brings at most its 20 g of carbohydrates, at 50 % of the product
    # at most with the first: 0.07 x 50 + 0.20 x 50. What it brings at least is
    # nothing.
    assert result.low == D("2.5")
    assert result.high == D("13.5")
    assert result.coverage == (D(50), D(75), D(100))


def test_a_nutrient_lacked_with_nothing_to_bound_it_has_no_highest_end():
    compositions = [{"sugars": content("6", "5", "7")}, {}]

    result = nutrients_of(
        solve_shares(ORDER_ONLY, {}), compositions, {"sugars": "carbohydrates"}
    )["sugars"]

    assert result.high is None


def test_an_ingredient_with_no_composition_is_a_part_of_the_product_not_covered():
    nodes = [node(1, protein=(0, 0)), node(2)]
    compositions: list[dict[str, Estimate]] = [
        {"vitamin_c": content("10", "10", "10")},
        {},
    ]

    result = worked_out(nodes, compositions)["vitamin_c"]

    assert result.high is None
    assert result.coverage == (D(50), D(75), D(100))


def test_traces_count_as_nothing_and_leave_the_highest_end_open():
    compositions = [
        {"iodine": content("10", "9", "11")},
        {"iodine": content(None, "0", None)},
    ]

    result = worked_out(ORDER_ONLY, compositions)["iodine"]

    assert result.amount == D("7.5")
    assert result.high is None
    # Both have a value for it, so the whole product is covered.
    assert result.coverage == (D(100), D(100), D(100))


def test_nothing_is_worked_out_when_the_shares_are_impossible():
    nodes = [node(1, declared="70"), node(2, declared="50"), node(3)]
    compositions = [{"zinc": content("1", "1", "1")}] * 3

    assert worked_out(nodes, compositions) == {}


def test_nothing_is_worked_out_when_no_ingredient_has_a_composition():
    nodes = [node(1), node(2)]

    assert worked_out(nodes, [{}, {}]) == {}


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
    values = {"fat": "0", "carbohydrates": "0", "proteins": "0", **amounts}
    for nutrient, amount in values.items():
        SourceFoodNutrient.objects.create(
            food=food,
            nutrient=Nutrient.objects.get(code=nutrient),
            amount=D(amount),
            confidence="A",
        )
    ref = ReferenceIngredient.objects.create(
        name_en=f"reference {code}", name_fr=f"fiche {code}"
    )
    ref.source_foods.add(food)
    return ref


def product_of(*refs: ReferenceIngredient, proteins: str | None = None) -> Product:
    product = Product.objects.create(barcode="3229820794556", name="Muesli")
    if proteins is not None:
        ProductNutrient.objects.create(
            product=product,
            nutrient=Nutrient.objects.get(code="proteins"),
            amount=D(proteins),
        )
    for ref in refs:
        Ingredient.objects.create(product=product, reference=ref)
    return product


def test_the_nutrients_of_a_product_are_worked_out_from_its_ingredients(
    source: Source,
):
    first = reference(source, "1", proteins="20", vitamin_c="10")
    second = reference(source, "2", proteins="10", vitamin_c="20")
    product = product_of(first, second, proteins="15")

    result = estimate_nutrients(product)

    vitamin_c = result.nutrients["vitamin_c"]
    assert vitamin_c.low <= vitamin_c.amount <= (vitamin_c.high or vitamin_c.amount)
    # Between 50 and 60 % of the first, from the protein of the label.
    assert D("14.5") <= vitamin_c.amount <= D("15.5")
    assert vitamin_c.coverage.point == D(100)
    assert result.percentages.used_nutrition
    # What the foods give of the label's nutrients comes out as well.
    assert {"proteins", "fat", "carbohydrates"} <= result.nutrients.keys()


def test_the_warnings_of_the_shares_come_with_the_nutrients(source: Source):
    product = product_of(reference(source, "1"), reference(source, "2"))

    result = estimate_nutrients(product)

    assert [w.problem for w in result.percentages.warnings] == [Problem.NO_NUTRITION]
    assert result.nutrients["fat"].coverage.point == D(100)


def test_a_product_without_ingredients_has_no_nutrients(source: Source):
    result = estimate_nutrients(product_of())

    assert result.nutrients == {}
    assert result.percentages.percentages == {}


def test_a_product_is_estimated_in_a_few_queries_however_many_ingredients(
    source: Source, django_assert_max_num_queries: Any
):
    refs = [reference(source, str(i), vitamin_c=str(i + 1)) for i in range(6)]
    product = product_of(*refs, proteins="15")

    # What the shares take, and no query more for the nutrients.
    with django_assert_max_num_queries(5 + 6):
        estimate_nutrients(product)
