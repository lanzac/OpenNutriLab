from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from opennutrilab.products.models import Additive
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.derived_nutrients import ensure_derivations
from opennutrilab.products.services.reference_composition import components_composition
from opennutrilab.products.services.reference_composition import reference_composition

CONSTITUENTS_FILE = Path(__file__).parents[1] / "data" / "ciqual_const_2025.xml"
EXACT = SourceFoodNutrient.Qualifier.EXACT
LESS_THAN = SourceFoodNutrient.Qualifier.LESS_THAN
TRACES = SourceFoodNutrient.Qualifier.TRACES
D = Decimal


@pytest.fixture
def source(db: None) -> Source:
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    ensure_derivations()
    return Source.objects.create(code="ciqual-2025", name="Ciqual", version="2025")


def food(source: Source, code: str = "1") -> SourceFood:
    return SourceFood.objects.create(
        source=source, code=code, name_fr=f"Aliment {code}"
    )


def value(  # noqa: PLR0913
    food: SourceFood,
    nutrient: str,
    amount: str | None,
    *,
    qualifier: SourceFoodNutrient.Qualifier = EXACT,
    grade: str = "A",
    minimum: str | None = None,
    maximum: str | None = None,
) -> None:
    SourceFoodNutrient.objects.create(
        food=food,
        nutrient=Nutrient.objects.get(code=nutrient),
        amount=None if amount is None else D(amount),
        minimum=None if minimum is None else D(minimum),
        maximum=None if maximum is None else D(maximum),
        qualifier=qualifier,
        confidence=grade,
    )


def reference_of(*foods: SourceFood) -> ReferenceIngredient:
    reference = ReferenceIngredient.objects.create(
        name_en=f"reference {ReferenceIngredient.objects.count()}"
    )
    reference.source_foods.add(*foods)
    return reference


def composition(*foods: SourceFood) -> dict[str, Any]:
    return reference_composition(reference_of(*foods))


# ----------------------------------------------------------------------------
# One food: the reference is that food
# ----------------------------------------------------------------------------
def test_a_reference_of_one_food_is_that_foods_values_and_range(source: Source):
    carrot = food(source)
    value(carrot, "vitamin_c", "9.3", grade="B", minimum="7.1", maximum="11.9")

    estimate = composition(carrot)["vitamin_c"]

    assert (estimate.amount, estimate.low, estimate.high) == (
        D("9.3"),
        D("7.1"),
        D("11.9"),
    )
    assert estimate.qualifier == EXACT
    assert estimate.grades == ("B",)
    assert estimate.foods == (carrot,)


@pytest.mark.parametrize(
    ("amount", "low", "high"),
    [
        ("9.3", "9.25", "9.35"),  # Half of the last decimal it is written with.
        ("9.30", "9.25", "9.35"),  # Trailing zeros say nothing.
        ("1100", "1099.5", "1100.5"),  # Zeros before the point count.
        ("0.083", "0.0825", "0.0835"),
        ("0", "0", "0"),  # A measured zero has no margin to read.
    ],
)
def test_a_value_with_no_range_is_known_to_its_rounding(
    source: Source, amount: str, low: str, high: str
):
    aliment = food(source)
    value(aliment, "vitamin_c", amount)

    estimate = composition(aliment)["vitamin_c"]

    assert (estimate.low, estimate.high) == (D(low), D(high))


def test_a_nutrient_in_grams_cannot_exceed_the_100_g_it_is_given_for(source: Source):
    oil = food(source)
    value(oil, "fat", "100")
    value(oil, "vitamin_c", "100")  # In mg: no such limit.

    result = composition(oil)

    assert (result["fat"].low, result["fat"].high) == (D("99.5"), D(100))
    assert result["vitamin_c"].high == D("100.5")


def test_the_range_always_holds_the_amount(source: Source):
    aliment = food(source)
    value(aliment, "vitamin_c", "5", minimum="6", maximum="7")

    estimate = composition(aliment)["vitamin_c"]

    assert (estimate.low, estimate.amount, estimate.high) == (D(5), D(5), D(7))


# ----------------------------------------------------------------------------
# What a value can mean
# ----------------------------------------------------------------------------
def test_below_the_detection_limit_is_somewhere_from_zero_to_the_limit(source: Source):
    aliment = food(source)
    value(aliment, "salt", "0.02", qualifier=LESS_THAN)

    estimate = composition(aliment)["salt"]

    assert (estimate.low, estimate.amount, estimate.high) == (
        D(0),
        D("0.01"),
        D("0.02"),
    )
    assert estimate.qualifier == LESS_THAN


def test_traces_are_there_but_not_quantified(source: Source):
    aliment = food(source)
    value(aliment, "iodine", None, qualifier=TRACES, grade="C")

    estimate = composition(aliment)["iodine"]

    assert (estimate.amount, estimate.low, estimate.high) == (None, D(0), None)
    assert estimate.qualifier == TRACES


def test_a_nutrient_that_was_not_measured_is_not_in_the_composition(source: Source):
    aliment = food(source)
    value(aliment, "vitamin_d", None, grade="")
    value(aliment, "vitamin_c", "9.3")

    assert set(composition(aliment)) == {"vitamin_c"}


def test_a_reference_with_no_source_food_has_no_composition(source: Source):
    assert reference_composition(ReferenceIngredient.objects.create(name_en="x")) == {}


# ----------------------------------------------------------------------------
# Several foods: weighted by grade, the range holds them all
# ----------------------------------------------------------------------------
def test_foods_are_combined_by_the_mean_weighted_by_their_grade(source: Source):
    sure, unsure = food(source, "1"), food(source, "2")
    value(sure, "vitamin_c", "10", grade="A", minimum="9", maximum="11")
    value(unsure, "vitamin_c", "20", grade="D", minimum="15", maximum="25")

    estimate = composition(sure, unsure)["vitamin_c"]

    # (10 x 4 + 20 x 1) / 5: the grade A food counts four times as much.
    assert estimate.amount == D(12)
    assert (estimate.low, estimate.high) == (D(9), D(25))
    assert estimate.grades == ("A", "D")
    assert set(estimate.foods) == {sure, unsure}


def test_a_value_with_no_grade_weighs_as_the_lowest(source: Source):
    graded, ungraded = food(source, "1"), food(source, "2")
    value(graded, "vitamin_c", "10", grade="D")
    value(ungraded, "vitamin_c", "20", grade="")

    estimate = composition(graded, ungraded)["vitamin_c"]

    assert estimate.amount == D(15)
    assert estimate.grades == ("D",)


def test_a_food_that_did_not_measure_a_nutrient_does_not_count_for_it(source: Source):
    one, two = food(source, "1"), food(source, "2")
    value(one, "vitamin_c", "10")
    value(two, "vitamin_c", None, grade="")
    value(two, "fat", "3")

    result = composition(one, two)

    assert result["vitamin_c"].amount == D(10)
    assert result["vitamin_c"].foods == (one,)
    assert result["fat"].foods == (two,)


def test_a_measured_value_wins_the_qualifier_over_a_limit_or_traces(source: Source):
    measured, limit, traces = food(source, "1"), food(source, "2"), food(source, "3")
    value(measured, "iodine", "10")
    value(limit, "iodine", "2", qualifier=LESS_THAN)
    value(traces, "iodine", None, qualifier=TRACES)

    estimate = composition(measured, limit, traces)["iodine"]

    assert estimate.qualifier == EXACT
    assert estimate.low == D(0)
    assert estimate.high == D("10.5")  # The measured one's rounding; traces say none.


def test_limits_and_traces_alone_make_a_limit_then_traces(source: Source):
    limit, traces = food(source, "1"), food(source, "2")
    value(limit, "iodine", "2", qualifier=LESS_THAN)
    value(traces, "iodine", None, qualifier=TRACES)

    assert composition(limit, traces)["iodine"].qualifier == LESS_THAN
    assert composition(traces)["iodine"].qualifier == TRACES


# ----------------------------------------------------------------------------
# What a food lacks and can be worked out from what it has
# ----------------------------------------------------------------------------
def test_a_nutrient_a_food_lacks_is_derived_from_its_components_with_its_range(
    source: Source,
):
    cake = food(source)
    value(cake, "retinol", "206", grade="B", minimum="200", maximum="212")
    value(cake, "beta_carotene", "151", grade="D", minimum="120", maximum="180")

    estimate = composition(cake)["vitamin_a"]

    assert round(estimate.amount, 1) == D("218.6")  # 206 + 151 / 12
    assert round(estimate.low, 1) == D("210.0")
    assert round(estimate.high, 1) == D("227.0")
    assert estimate.grades == ("D",)  # As good as its worst component.


def test_what_the_food_gives_is_not_replaced_by_a_derivation(source: Source):
    cake = food(source)
    value(cake, "vitamin_a", "219")
    value(cake, "retinol", "100")
    value(cake, "beta_carotene", "0")

    assert composition(cake)["vitamin_a"].amount == D(219)


def test_a_derivation_with_a_component_missing_gives_nothing(source: Source):
    shrimp = food(source)
    value(shrimp, "vitamin_k1", "0.2")

    assert "vitamin_k" not in composition(shrimp)


def test_a_derivation_with_a_component_in_traces_gives_nothing(source: Source):
    shrimp = food(source)
    value(shrimp, "vitamin_k1", "0.2")
    value(shrimp, "vitamin_k2", None, qualifier=TRACES)

    assert "vitamin_k" not in composition(shrimp)


def test_derived_values_are_combined_with_the_others_as_any_value_is(source: Source):
    one, two = food(source, "1"), food(source, "2")
    value(one, "vitamin_k1", "0.2", grade="A")
    value(one, "vitamin_k2", "3.4", grade="A")
    value(two, "vitamin_k", "5", grade="A")

    estimate = composition(one, two)["vitamin_k"]

    # One food gives it, the other it is derived for: 3.6 and 5, equal weights.
    assert estimate.amount == D("4.3")
    assert set(estimate.foods) == {one, two}


def test_the_composition_is_read_in_a_few_queries_however_many_foods(
    source: Source, django_assert_max_num_queries: Any
):
    foods = [food(source, str(i)) for i in range(5)]
    for aliment in foods:
        value(aliment, "vitamin_c", "9.3")
        value(aliment, "fat", "3")
    reference = reference_of(*foods)

    # The values, and the catalogue's derivations with their terms.
    with django_assert_max_num_queries(3):
        reference_composition(reference)


# ----------------------------------------------------------------------------
# A preparation draws on its source foods as a reference does
# ----------------------------------------------------------------------------
def test_a_preparation_of_one_food_is_that_foods_values(source: Source):
    mozzarella = food(source)
    value(mozzarella, "fat", "17.5", grade="B")
    preparation = Preparation.objects.create(name_en="mozzarella")
    preparation.source_foods.add(mozzarella)

    estimate = reference_composition(preparation)["fat"]

    assert (estimate.amount, estimate.grades, estimate.foods) == (
        D("17.5"),
        ("B",),
        (mozzarella,),
    )


def test_the_foods_of_a_reference_are_not_those_of_a_preparation(source: Source):
    one = food(source, "1")
    value(one, "fat", "10")
    other = food(source, "2")
    value(other, "fat", "30")
    reference = reference_of(one)
    preparation = Preparation.objects.create(name_en="gnocchi")
    preparation.source_foods.add(other)

    assert reference_composition(reference)["fat"].amount == D(10)
    assert reference_composition(preparation)["fat"].amount == D(30)


def test_a_preparation_with_no_source_food_has_no_composition(db: None):
    assert reference_composition(Preparation.objects.create(name_en="gnocchi")) == {}


# ----------------------------------------------------------------------------
# An additive draws on its source foods as a reference does
# ----------------------------------------------------------------------------
def test_the_foods_of_an_additive_are_not_those_of_a_reference(source: Source):
    one, other = food(source, "1"), food(source, "2")
    value(one, "fat", "10")
    value(other, "fat", "30")
    lecithin = Additive.objects.create(name_en="soy lecithin", code="E322")
    lecithin.source_foods.add(one)

    assert reference_composition(lecithin)["fat"].amount == D(10)
    assert reference_composition(reference_of(other))["fat"].amount == D(30)


def test_an_additive_with_no_source_food_has_no_composition(db: None):
    assert reference_composition(Additive.objects.create(name_en="citric acid")) == {}


# ----------------------------------------------------------------------------
# A preparation drawing on no food: what it is made of
# ----------------------------------------------------------------------------
def made_of(*references: ReferenceIngredient, name: str = "gnocchi") -> Preparation:
    preparation = Preparation.objects.create(name_en=name)
    preparation.components.add(*references)
    return preparation


def test_the_components_give_the_range_that_holds_all_of_theirs(source: Source):
    milk = food(source, "1")
    value(milk, "fat", "3.5", minimum="3", maximum="4")
    cream = food(source, "2")
    value(cream, "fat", "30", minimum="28", maximum="32")

    estimate = components_composition(made_of(reference_of(milk), reference_of(cream)))[
        "fat"
    ]

    # Whatever the mix is, it is in there; the amount is the mean of theirs.
    assert (estimate.low, estimate.amount, estimate.high) == (D(3), D("16.75"), D(32))
    assert estimate.qualifier == EXACT


def test_the_components_composition_has_no_grade_and_credits_all_their_foods(
    source: Source,
):
    milk, cream = food(source, "1"), food(source, "2")
    value(milk, "fat", "3.5", grade="A")
    value(cream, "fat", "30", grade="A")

    estimate = components_composition(made_of(reference_of(milk), reference_of(cream)))[
        "fat"
    ]

    assert estimate.grades == ()
    assert set(estimate.foods) == {milk, cream}


def test_a_nutrient_one_component_does_not_give_is_not_in_the_composition(
    source: Source,
):
    milk, flour = food(source, "1"), food(source, "2")
    value(milk, "fat", "3.5")
    value(milk, "vitamin_c", "1")
    value(flour, "fat", "1")

    found = components_composition(made_of(reference_of(milk), reference_of(flour)))

    assert set(found) == {"fat"}


def test_a_component_with_no_composition_leaves_the_preparation_with_none(
    source: Source,
):
    milk = food(source, "1")
    value(milk, "fat", "3.5")
    rennet = ReferenceIngredient.objects.create(name_en="rennet")

    assert components_composition(made_of(reference_of(milk), rennet)) == {}


def test_a_preparation_made_of_nothing_has_no_composition(db: None):
    assert components_composition(Preparation.objects.create(name_en="gnocchi")) == {}


def test_a_component_that_is_only_traces_leaves_the_top_of_the_range_open(
    source: Source,
):
    milk, salt = food(source, "1"), food(source, "2")
    value(milk, "fat", "3.5", minimum="3", maximum="4")
    value(salt, "fat", None, qualifier=TRACES)

    estimate = components_composition(made_of(reference_of(milk), reference_of(salt)))[
        "fat"
    ]

    assert (estimate.low, estimate.amount, estimate.high) == (D(0), D("3.5"), None)


def test_the_components_of_one_preparation_are_not_those_of_another(source: Source):
    one, other = food(source, "1"), food(source, "2")
    value(one, "fat", "10")
    value(other, "fat", "30")
    made_of_one = made_of(reference_of(one))
    made_of(reference_of(other), name="pizza")

    assert components_composition(made_of_one)["fat"].amount == D(10)


# ----------------------------------------------------------------------------
# A preparation made of other preparations
# ----------------------------------------------------------------------------
def made_of_preparations(
    *preparations: Preparation, name: str = "boulette"
) -> Preparation:
    preparation = Preparation.objects.create(name_en=name)
    preparation.preparation_components.add(*preparations)
    return preparation


def test_a_component_that_is_a_preparation_counts_by_its_foods(source: Source):
    milk, cream = food(source, "1"), food(source, "2")
    value(milk, "fat", "3.5", minimum="3", maximum="4")
    value(cream, "fat", "30", minimum="28", maximum="32")
    sauce = Preparation.objects.create(name_en="sauce")
    sauce.source_foods.add(cream)

    mixed = made_of(reference_of(milk))
    mixed.preparation_components.add(sauce)

    estimate = components_composition(mixed)["fat"]

    assert (estimate.low, estimate.amount, estimate.high) == (D(3), D("16.75"), D(32))
    assert set(estimate.foods) == {milk, cream}


def test_a_component_that_is_a_preparation_with_no_food_counts_by_its_components(
    source: Source,
):
    milk, cream = food(source, "1"), food(source, "2")
    value(milk, "fat", "3.5", minimum="3", maximum="4")
    value(cream, "fat", "30", minimum="28", maximum="32")
    sauce = made_of(reference_of(cream), name="sauce")

    mixed = made_of_preparations(sauce)
    mixed.components.add(reference_of(milk))

    estimate = components_composition(mixed)["fat"]

    assert (estimate.low, estimate.high) == (D(3), D(32))


def test_preparations_in_preparations_are_followed_all_the_way_down(source: Source):
    cream = food(source)
    value(cream, "fat", "30")
    sauce = made_of(reference_of(cream), name="sauce")
    filling = made_of_preparations(sauce, name="filling")

    assert components_composition(made_of_preparations(filling))["fat"].amount == D(30)


def test_a_component_that_is_a_preparation_saying_nothing_leaves_none(source: Source):
    milk = food(source)
    value(milk, "fat", "3.5")
    unknown = Preparation.objects.create(name_en="unknown")

    mixed = made_of(reference_of(milk))
    mixed.preparation_components.add(unknown)

    assert components_composition(mixed) == {}


def test_a_component_that_has_foods_but_no_value_does_not_fall_back_on_its_parts(
    source: Source,
):
    milk, cream = food(source, "1"), food(source, "2")
    value(milk, "fat", "3.5")
    value(cream, "fat", "30")
    sauce = made_of(reference_of(cream), name="sauce")
    sauce.source_foods.add(food(source, "3"))  # A food that measured nothing.

    mixed = made_of(reference_of(milk))
    mixed.preparation_components.add(sauce)

    assert components_composition(mixed) == {}


def test_a_preparation_made_of_itself_says_nothing_and_does_not_loop(source: Source):
    milk = food(source)
    value(milk, "fat", "3.5")
    one = made_of(reference_of(milk), name="one")
    other = made_of_preparations(one, name="other")
    one.preparation_components.add(other)  # A cycle: one -> other -> one.

    assert components_composition(one) == {}
    assert components_composition(other) == {}
    own = made_of(reference_of(milk), name="own")
    own.preparation_components.add(own)
    assert components_composition(own) == {}
