from dataclasses import replace
from decimal import ROUND_HALF_EVEN
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.utils import translation

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
from opennutrilab.products.services.estimate_validation import Check
from opennutrilab.products.services.estimate_validation import Confidence
from opennutrilab.products.services.estimate_validation import Verdict
from opennutrilab.products.services.estimate_validation import compare
from opennutrilab.products.services.estimate_validation import confidence_of
from opennutrilab.products.services.estimate_validation import mismatches
from opennutrilab.products.services.estimate_validation import validate_estimate
from opennutrilab.products.services.nutrient_estimation import NutrientAmount
from opennutrilab.products.services.nutrient_estimation import nutrients_of
from opennutrilab.products.services.percentage_estimation import NUTRIENTS
from opennutrilab.products.services.percentage_estimation import EstimateWarning
from opennutrilab.products.services.percentage_estimation import Interval
from opennutrilab.products.services.percentage_estimation import Node
from opennutrilab.products.services.percentage_estimation import Problem
from opennutrilab.products.services.percentage_estimation import Range
from opennutrilab.products.services.percentage_estimation import solve_shares
from opennutrilab.products.services.reference_composition import Estimate

D = Decimal
CENT = D("0.01")
WHOLE = Interval(D(100), D(100), D(100))
CONSTITUENTS_FILE = Path(__file__).parents[1] / "data" / "ciqual_const_2025.xml"


def given(low: str, high: str | None, amount: str | None = None) -> NutrientAmount:
    """What the ingredients give of a nutrient, from the whole product."""
    return NutrientAmount(
        amount=D(low if amount is None else amount),
        low=D(low),
        high=None if high is None else D(high),
        coverage=WHOLE,
    )


def check_of(
    declared: str,
    estimate: NutrientAmount | None,
    code: str = "energy",
    constrained: tuple[str, ...] = (),
    group: str = "",
) -> Check:
    """
    By default for a nutrient the Commission's guidance gives no tolerance (energy),
    so that only the rounding of the figure is in the comparison.
    """
    nutrients = {} if estimate is None else {code: estimate}
    return compare(
        {code: D(declared)},
        nutrients,
        {code: "g"},
        constrained=constrained,
        groups={code: group},
    )[code]


# ----------------------------------------------------------------------------
# A declared figure against what the ingredients give
# ----------------------------------------------------------------------------
def test_a_declared_figure_within_the_estimate_agrees():
    check = check_of("9.4", given("7.7", "10.9"))

    assert check.verdict is Verdict.AGREES
    assert check.gap == 0
    assert check.declared_range == (D("9.35"), D("9.45"))
    assert check.estimated == (D("7.7"), D("10.9"))


def test_the_rounding_of_a_declared_figure_is_part_of_the_comparison():
    # 33 is 32.5 to 33.5: it meets an estimate that starts at 33.5, not at 33.6.
    assert check_of("33", given("33.5", "40")).verdict is Verdict.AGREES
    assert check_of("33", given("20", "32.5")).verdict is Verdict.AGREES

    below = check_of("33", given("33.6", "40"))
    assert below.verdict is Verdict.DECLARED_BELOW
    assert below.gap == D("0.1")


def test_a_label_under_what_the_ingredients_bring_at_the_least_is_below():
    check = check_of("10", given("12", "15"))

    assert check.verdict is Verdict.DECLARED_BELOW
    # 12 against the 10.5 the label's rounding allows.
    assert check.gap == D("1.5")


def test_a_label_over_what_the_ingredients_can_bring_at_the_most_is_above():
    check = check_of("30", given("10", "20"))

    assert check.verdict is Verdict.DECLARED_ABOVE
    assert check.gap == D("9.5")


def test_a_zero_on_the_label_of_a_nutrient_with_no_threshold_has_no_margin():
    assert check_of("0", given("0", "3")).verdict is Verdict.AGREES
    assert check_of("0", given("0.2", "3")).verdict is Verdict.DECLARED_BELOW


# ----------------------------------------------------------------------------
# The tolerance a label is allowed (see label_tolerance)
# ----------------------------------------------------------------------------
def test_a_label_within_the_tolerance_agrees_and_says_it_needed_it():
    # 13 g of saturates is 12.5 to 13.5, and 9.9 to 16.1 with a fifth of tolerance.
    check = check_of("13", given("13.76", "13.95"), "saturated_fat", group="fatty_acid")

    assert check.verdict is Verdict.AGREES
    assert check.tolerated
    assert check.declared_range == (D("12.5"), D("13.5"))
    assert check.tolerance_range == (D("9.9"), D("16.1"))
    assert check.gap == 0


def test_a_label_within_the_rounding_did_not_need_the_tolerance():
    check = check_of("13", given("13.2", "13.4"), "saturated_fat", group="fatty_acid")

    assert check.verdict is Verdict.AGREES
    assert not check.tolerated


def test_a_label_beyond_the_tolerance_is_below_or_above_it():
    below = check_of("13", given("17", "18"), "saturated_fat", group="fatty_acid")
    above = check_of("13", given("6", "8"), "saturated_fat", group="fatty_acid")

    assert (below.verdict, below.gap) == (Verdict.DECLARED_BELOW, D("0.9"))
    assert (above.verdict, above.gap) == (Verdict.DECLARED_ABOVE, D("1.9"))
    assert not below.tolerated


def test_a_zero_on_the_label_stands_for_less_than_the_guidelines_threshold():
    # 0 g of protein is less than 0.5 g, and 2.5 g with the tolerance.
    within_rounding = check_of(
        "0", given("0.22", "3"), "proteins", group="macronutrient"
    )
    within_tolerance = check_of(
        "0", given("1.5", "3"), "proteins", group="macronutrient"
    )
    beyond = check_of("0", given("3", "4"), "proteins", group="macronutrient")

    assert within_rounding.verdict is Verdict.AGREES
    assert not within_rounding.tolerated
    assert (within_tolerance.verdict, within_tolerance.tolerated) == (
        Verdict.AGREES,
        True,
    )
    assert beyond.verdict is Verdict.DECLARED_BELOW


def test_energy_has_no_tolerance():
    assert check_of("3382", given("3400", "3500")).verdict is Verdict.DECLARED_BELOW


def test_a_vitamin_is_allowed_a_share_of_its_figure():
    # Vitamin C of 80 mg: 51.5 to 120.5 with the tolerance of the guidance.
    within = check_of("80", given("110", "120"), "vitamin_c", group="vitamin")
    beyond = check_of("80", given("125", "130"), "vitamin_c", group="vitamin")

    assert (within.verdict, within.tolerated) == (Verdict.AGREES, True)
    assert beyond.verdict is Verdict.DECLARED_BELOW


def test_a_nutrient_only_some_ingredients_give_has_no_highest_end_to_exceed():
    open_ended = given("5", None)

    assert check_of("100", open_ended).verdict is Verdict.AGREES
    # But what they bring at the least is still more than the label declares.
    assert check_of("3", open_ended).verdict is Verdict.DECLARED_BELOW


def test_a_nutrient_no_ingredient_gives_is_not_estimated():
    check = check_of("12", None)

    assert check.verdict is Verdict.NOT_ESTIMATED
    assert check.estimated is None
    assert check.gap == 0


def test_each_declared_nutrient_is_checked_with_its_unit():
    checks = compare(
        {"energy": D("1532"), "fat": D("9.4")},
        {"energy": given("1416", "1739"), "fat": given("7.7", "10.9")},
        {"energy": "kJ", "fat": "g"},
    )

    assert list(checks) == ["energy", "fat"]
    assert [c.unit for c in checks.values()] == ["kJ", "g"]


# ----------------------------------------------------------------------------
# What is a confirmation and what is not
# ----------------------------------------------------------------------------
def test_the_nutrients_the_shares_were_worked_out_with_agree_by_construction():
    checks = compare(
        {"energy": D("1532"), "fat": D("9.4")},
        {"energy": given("1416", "1739"), "fat": given("7.7", "10.9")},
        {},
        constrained=NUTRIENTS,
    )

    assert checks["fat"].constrained
    assert not checks["energy"].constrained
    assert not checks["fat"].informative
    assert checks["energy"].informative


def test_a_check_is_informative_if_it_could_have_failed():
    assert check_of("9.4", given("7.7", "10.9")).informative
    assert check_of("30", given("10", "20")).informative
    # Open at the top, and met: it says almost nothing.
    assert not check_of("100", given("5", None)).informative
    # Open at the top, and failed: it says something.
    assert check_of("3", given("5", None)).informative
    assert not check_of("12", None).informative


# ----------------------------------------------------------------------------
# A convention the law does not fix
# ----------------------------------------------------------------------------
# Vitamin A counting the carotene for a twelfth, then for a sixth.
VITAMIN_A = {
    "vitamin_a": given("14.5", "15.5"),
    "vitamin_a_sixth": given("19.4", "20.6"),
}


@pytest.mark.parametrize("declared", ["15", "20"])
def test_a_vitamin_a_that_either_convention_gives_agrees(declared: str):
    check = compare({"vitamin_a": D(declared)}, VITAMIN_A, {})["vitamin_a"]

    assert check.verdict is Verdict.AGREES
    # The estimate it was compared with holds both.
    assert check.estimated == (D("14.5"), D("20.6"))


def test_a_vitamin_a_between_the_two_readings_agrees_too():
    """The interval is the one the two readings span: another convention would
    land between them."""
    check = compare({"vitamin_a": D(17)}, VITAMIN_A, {})["vitamin_a"]

    assert check.verdict is Verdict.AGREES


def test_a_vitamin_a_outside_both_readings_is_off_by_its_distance_to_the_nearest():
    above = compare({"vitamin_a": D(30)}, VITAMIN_A, {})["vitamin_a"]
    below = compare({"vitamin_a": D(5)}, VITAMIN_A, {})["vitamin_a"]

    assert (above.verdict, above.gap) == (Verdict.DECLARED_ABOVE, D("8.9"))
    assert (below.verdict, below.gap) == (Verdict.DECLARED_BELOW, D("9"))


def test_the_vitamin_a_with_no_highest_end_in_one_reading_has_none_overall():
    nutrients = {
        "vitamin_a": given("14.5", "15.5"),
        "vitamin_a_sixth": given("5", None),
    }

    check = compare({"vitamin_a": D(100)}, nutrients, {})["vitamin_a"]

    assert check.estimated == (D(5), None)
    assert check.verdict is Verdict.AGREES


def test_a_vitamin_a_is_compared_with_the_reading_there_is():
    check = compare({"vitamin_a": D(15)}, {"vitamin_a": given("14.5", "15.5")}, {})

    assert check["vitamin_a"].estimated == (D("14.5"), D("15.5"))


# ----------------------------------------------------------------------------
# What is said of what does not agree
# ----------------------------------------------------------------------------
def test_a_declared_figure_the_ingredients_cannot_give_is_a_warning_that_names_it():
    checks = {"fat": check_of("9.4", given("12", None)), "sugars": check_of("1", None)}

    warnings = mismatches(checks, {"fat": "Fat", "sugars": "Sugars"}, {"fat": "g"})

    assert [w.problem for w in warnings] == [Problem.DECLARED_BELOW]
    assert warnings[0].codes == ("fat",)
    with translation.override("en"):
        assert warnings[0].message() == (
            "Fat: the label declares 9.4 g, but its ingredients bring at least 12 g."
        )


def test_an_over_declared_figure_is_held_against_the_highest_end():
    checks = {"fat": check_of("30", given("10", "20"))}

    (warning,) = mismatches(checks, {"fat": "Fat"}, {"fat": "g"})

    assert warning.problem == Problem.DECLARED_ABOVE
    with translation.override("en"):
        assert warning.message().endswith("bring at most 20 g.")


def test_the_figures_of_a_warning_follow_the_language_served():
    checks = {"fat": check_of("9.4", given("12", None))}

    with translation.override("fr"):
        (warning,) = mismatches(checks, {"fat": "Lipides"}, {"fat": "g"})
        message = warning.message()

    assert "l'étiquette déclare 9,4 g" in message


def test_what_agrees_or_cannot_be_compared_says_nothing():
    checks = {
        "fat": check_of("9.4", given("7.7", "10.9")),
        "sugars": check_of("1", None, "sugars"),
    }

    assert mismatches(checks, {}, {}) == []


# ----------------------------------------------------------------------------
# Confidence
# ----------------------------------------------------------------------------
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


def content(amount: str, grades: tuple[str, ...] = ("A",)) -> Estimate:
    return Estimate(
        amount=D(amount),
        low=D(amount),
        high=D(amount),
        qualifier=SourceFoodNutrient.Qualifier.EXACT,
        grades=grades,
        foods=(),
    )


# Two ingredients in this order and nothing else said: 50 to 100 % and 0 to 50 %,
# and 75 and 25 % at the point.
ORDER_ONLY = [node(1, protein=(0, 0)), node(2, protein=(0, 0))]


def confidence_for(
    compositions: list[dict[str, Estimate]],
    checks: dict[str, Check] | None = None,
    nodes: list[Node] | None = None,
) -> dict[str, Confidence]:
    solution = solve_shares(nodes or ORDER_ONLY, {})
    nutrients = nutrients_of(solution, compositions)
    return confidence_of(solution, compositions, nutrients, checks or {})


def test_the_parts_of_the_confidence_come_with_a_score_that_is_their_product():
    compositions = [{"vitamin_c": content("10")}, {"vitamin_c": content("20")}]

    parts = confidence_for(compositions)["vitamin_c"]

    assert parts.coverage == D("1.00")
    assert parts.quality == D("1.00")
    # Half of the widths, 50 and 50, is the half of the product that could be
    # either ingredient.
    assert parts.uncertainty == D("0.50")
    assert parts.agreement is None
    assert parts.score == D("0.50")


def test_the_score_can_be_worked_out_from_the_parts_it_shows():
    compositions = [
        {"vitamin_c": content("10", ("B",))},
        {"vitamin_c": content("20", ("D",))},
    ]
    checks = {"energy": check_of("1500", given("1400", "1700"), "energy")}

    parts = confidence_for(compositions, checks)["vitamin_c"]

    assert parts.agreement is not None
    assert parts.agreement == D("1.00")
    assert parts.score == (
        parts.coverage * parts.quality * (1 - parts.uncertainty) * parts.agreement
    ).quantize(CENT, ROUND_HALF_EVEN)


def test_quality_is_the_grade_of_what_is_given_weighted_by_the_share_of_each():
    compositions = [
        {"vitamin_c": content("10", ("A",))},
        {"vitamin_c": content("20", ("D",))},
    ]

    parts = confidence_for(compositions)["vitamin_c"]

    # 75 % of an A (1) and 25 % of a D (0.25).
    assert parts.quality == D("0.81")


def test_the_quality_of_a_total_is_its_worst_parts():
    compositions = [
        {"linoleic_acid": content("10", ("A",)), "arachidonic_acid": content("0")},
        {"linoleic_acid": content("20", ("A",)), "arachidonic_acid": content("0")},
    ]
    compositions[1]["arachidonic_acid"] = content("0", ("D",))
    sums = {"omega_6": ("linoleic_acid", "arachidonic_acid")}
    solution = solve_shares(ORDER_ONLY, {})
    nutrients = nutrients_of(solution, compositions, None, sums)

    parts = confidence_of(solution, compositions, nutrients, {}, sums)

    # AA: 75 % of an A and 25 % of a D, against LA's two A.
    assert parts["omega_6"].quality == D("0.81")
    assert parts["linoleic_acid"].quality == D("1.00")


def test_the_grades_of_several_foods_are_averaged_and_no_grade_is_the_lowest():
    mixed = confidence_for(
        [{"zinc": content("1", ("A", "C"))}, {"zinc": content("1", ("A", "C"))}]
    )
    ungraded = confidence_for([{"zinc": content("1", ())}, {"zinc": content("1", ())}])

    assert mixed["zinc"].quality == D("0.75")
    assert ungraded["zinc"].quality == D("0.25")


def test_an_ingredient_that_gives_nothing_lowers_the_coverage_and_not_the_quality():
    compositions: list[dict[str, Estimate]] = [{"vitamin_c": content("10")}, {}]

    parts = confidence_for(compositions)["vitamin_c"]

    assert parts.coverage == D("0.75")
    assert parts.quality == D("1.00")


def test_a_recipe_that_is_better_known_is_less_uncertain():
    nodes = [
        node(1, declared="60", protein=(0, 0)),
        node(2, declared="40", protein=(0, 0)),
    ]
    compositions = [{"vitamin_c": content("10")}, {"vitamin_c": content("20")}]

    parts = confidence_for(compositions, nodes=nodes)["vitamin_c"]

    # Only the rounding of the two figures: 1 and 1 over 200.
    assert parts.uncertainty == D("0.01")


def test_the_agreement_is_the_share_of_the_checks_that_could_fail_that_agree():
    compositions = [{"zinc": content("1")}, {"zinc": content("1")}]
    checks = {
        "energy": check_of("1500", given("1400", "1700"), "energy"),
        "iron": check_of("5", given("1", "2"), "iron"),
        # These cannot count: one was used as a rule, one has nothing to meet.
        "fat": check_of("9.4", given("7", "11"), "fat", constrained=("fat",)),
        "zinc": check_of("100", given("5", None), "zinc"),
    }

    parts = confidence_for(compositions, checks)["zinc"]

    assert parts.agreement == D("0.50")


def test_a_total_disagreement_is_zero_and_not_the_lack_of_a_check():
    compositions = [{"zinc": content("1")}, {"zinc": content("1")}]
    checks = {"iron": check_of("5", given("1", "2"), "iron")}

    parts = confidence_for(compositions, checks)["zinc"]

    assert parts.agreement == D("0.00")
    assert parts.score == D("0.00")


def test_a_nutrient_the_label_cannot_be_given_with_counts_as_not_agreeing():
    compositions = [{"zinc": content("1")}, {"zinc": content("1")}]
    solution = solve_shares(ORDER_ONLY, {})
    conflict = EstimateWarning(Problem.LABEL_DISAGREES, "Fat", ("fat",))
    solution = replace(solution, warnings=[conflict])
    checks = {
        # Each of them meets the estimate on its own, but not together.
        "fat": check_of("9.4", given("7", "11"), "fat"),
        "energy": check_of("1500", given("1400", "1700"), "energy"),
    }

    parts = confidence_of(
        solution, compositions, nutrients_of(solution, compositions), checks
    )["zinc"]

    assert parts.agreement == D("0.50")


def test_nothing_is_trusted_where_nothing_could_be_estimated():
    nodes = [node(1, declared="70"), node(2, declared="50"), node(3)]
    solution = solve_shares(nodes, {})

    assert confidence_of(solution, [{}, {}, {}], {}, {}) == {}


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


def product_of(*refs: ReferenceIngredient, **declared: str) -> Product:
    product = Product.objects.create(barcode="3229820794556", name="Muesli")
    for code, amount in declared.items():
        ProductNutrient.objects.create(
            product=product, nutrient=Nutrient.objects.get(code=code), amount=D(amount)
        )
    for ref in refs:
        Ingredient.objects.create(product=product, reference=ref)
    return product


def test_the_energy_of_a_label_is_checked_and_the_rest_agrees_by_construction(
    source: Source,
):
    first = reference(source, "1", proteins="20", energy="1600")
    second = reference(source, "2", proteins="10", energy="1000")
    # With 15 g of protein, the first is 50 to 55 %, and so the energy 1300 to 1330.
    product = product_of(first, second, proteins="15", energy="1310")

    result = validate_estimate(product)

    assert result.checks["energy"].verdict is Verdict.AGREES
    assert result.checks["energy"].informative
    assert result.checks["proteins"].constrained
    assert result.warnings == []
    assert result.confidence.keys() == result.nutrients.keys()
    assert result.confidence["energy"].agreement == D("1.00")


def test_a_label_the_ingredients_cannot_give_is_a_warning_and_the_estimate_stays(
    source: Source,
):
    first = reference(source, "1", proteins="20", energy="1600")
    second = reference(source, "2", proteins="10", energy="1000")
    product = product_of(first, second, proteins="15", energy="500")

    result = validate_estimate(product)

    assert result.checks["energy"].verdict is Verdict.DECLARED_BELOW
    (warning,) = result.warnings
    assert warning.problem == Problem.DECLARED_BELOW
    assert warning.codes == ("energy",)
    with translation.override("en"):
        assert "500 kJ" in warning.message()
    # Non-blocking: the estimate is there, with what the check made of it.
    assert result.nutrients["energy"].low > D(500)
    assert result.confidence["energy"].agreement == D("0.00")
    assert result.confidence["energy"].score == D("0.00")


def test_the_warnings_of_the_shares_come_first(source: Source):
    first = reference(source, "1", proteins="20", energy="1600")
    second = reference(source, "2", proteins="10", energy="1000")
    # Nothing declared but the energy: the nutrition of the label is not used.
    product = product_of(first, second, energy="500")

    result = validate_estimate(product)

    assert [w.problem for w in result.warnings] == [
        Problem.NO_NUTRITION,
        Problem.DECLARED_BELOW,
    ]
    assert result.warnings[:1] == result.percentages.warnings


def per_100_ml(product: Product) -> Product:
    product.nutrition_unit = "ml"
    product.save()
    return product


def an_oil(source: Source, **amounts: str) -> ReferenceIngredient:
    oil = reference(source, "1", **amounts)
    oil.density_low, oil.density_high = D("0.908"), D("0.915")
    oil.save()
    return oil


def test_a_label_per_100_ml_without_a_density_is_kept_as_printed_and_not_compared(
    source: Source,
):
    # 91 g of fat per 100 ml of an oil that is 99.9 g per 100 g: neither wrong nor
    # contradicted, only not the same quantity as the estimate.
    oil = reference(source, "1", fat="99.9", proteins="0.25")
    product = per_100_ml(product_of(oil, fat="91"))

    result = validate_estimate(product)

    assert [w.problem for w in result.warnings] == [Problem.NUTRITION_PER_VOLUME]
    assert result.checks == {}
    assert result.density is None
    assert result.nutrients["fat"].amount == D("99.9")
    # What is kept is what the label printed.
    assert product.declared_nutrients.get(nutrient_id="fat").amount == D("91")


def test_a_label_per_100_ml_is_set_against_the_estimate_per_100_ml(source: Source):
    oil = an_oil(source, fat="99.9", proteins="0.25")
    product = per_100_ml(product_of(oil, fat="91"))

    result = validate_estimate(product)

    assert result.warnings == []
    assert result.density == (D("0.908"), D("0.915"))
    fat = result.checks["fat"]
    assert fat.verdict is Verdict.AGREES
    assert fat.constrained
    # The estimate is kept per 100 g, and set against the label per 100 ml.
    assert result.nutrients["fat"].amount == D("99.9")
    assert fat.estimated is not None
    # 99.9 is written to a tenth, so it is 99.85 to 99.95.
    assert fat.estimated[0] == D("99.85") * D("0.908")
    assert fat.estimated[1] == D("99.95") * D("0.915")
    # The label is still the figure as printed.
    assert fat.declared == D("91")


@pytest.mark.parametrize(
    ("energy", "verdict"),
    [("3382", Verdict.AGREES), ("3000", Verdict.DECLARED_BELOW)],
)
def test_the_energy_of_a_label_per_100_ml_is_checked_through_the_density(
    source: Source, energy: str, verdict: Verdict
):
    # 3700 kJ per 100 g of an oil of 0.908 to 0.915 is 3359 to 3386 kJ per 100 ml.
    oil = an_oil(source, fat="99.9", energy="3700")
    product = per_100_ml(product_of(oil, fat="91", energy=energy))

    result = validate_estimate(product)

    assert result.checks["energy"].verdict is verdict
    assert result.checks["energy"].informative


def test_a_label_per_100_ml_within_the_tolerance_is_read_with_it_and_says_so(
    source: Source,
):
    # The label of the oil of the user: 91 g of fat, 13 g of saturates and 0 g of
    # protein per 100 ml. The saturates are 13.7 to 14 g per 100 ml for CIQUAL, off
    # the rounding of 13 but within the tolerance; the 0 stands for less than 0.5 g.
    oil = an_oil(source, fat="99.9", saturated_fat="15.2", proteins="0.25")
    product = per_100_ml(product_of(oil, fat="91", saturated_fat="13", proteins="0"))

    result = validate_estimate(product)

    assert [w.problem for w in result.warnings] == [Problem.WITHIN_TOLERANCE]
    assert result.warnings[0].codes == ("saturated_fat",)
    assert result.percentages.used_nutrition
    assert {c.verdict for c in result.checks.values()} == {Verdict.AGREES}
    assert result.checks["saturated_fat"].tolerated
    assert not result.checks["proteins"].tolerated
    assert not result.checks["fat"].tolerated


def test_a_label_per_100_ml_that_the_density_does_not_reconcile_is_named(
    source: Source,
):
    oil = an_oil(source, fat="99.9", proteins="0.25")
    product = per_100_ml(product_of(oil, fat="70"))

    result = validate_estimate(product)

    assert next(w.problem for w in result.warnings) is Problem.LABEL_DISAGREES
    assert result.checks["fat"].verdict is Verdict.DECLARED_BELOW
    assert result.checks["fat"].estimated is not None


def test_a_declared_vitamin_a_is_compared_with_both_readings_of_the_carotene(
    source: Source,
):
    # Retinol 10 and beta-carotene 60 µg: 15 with a twelfth of it, 20 with a sixth.
    only = reference(source, "1", retinol="10", beta_carotene="60")
    product = product_of(only, vitamin_a="19")

    result = validate_estimate(product)

    twelfth = result.nutrients["vitamin_a"]
    assert twelfth.high is not None
    assert twelfth.high < D("18.5")
    assert result.nutrients["vitamin_a_sixth"].low > twelfth.high
    # 19 is out of the first reading and within the second, so it agrees.
    assert result.checks["vitamin_a"].verdict is Verdict.AGREES
    assert not [w for w in result.warnings if w.codes == ("vitamin_a",)]


def test_a_declared_nutrient_no_ingredient_gives_is_listed_and_not_estimated(
    source: Source,
):
    product = product_of(reference(source, "1"), vitamin_a="19")

    result = validate_estimate(product)

    assert result.checks["vitamin_a"].verdict is Verdict.NOT_ESTIMATED
    assert result.warnings == [EstimateWarning(Problem.NO_NUTRITION)]


def test_nothing_is_checked_or_trusted_when_the_shares_are_impossible(source: Source):
    product = Product.objects.create(barcode="3229820794556", name="Muesli")
    ProductNutrient.objects.create(
        product=product, nutrient=Nutrient.objects.get(code="energy"), amount=D(500)
    )
    for code, percentage in (("1", "70"), ("2", "50"), ("3", None)):
        Ingredient.objects.create(
            product=product,
            reference=reference(source, code, energy="100"),
            percentage=None if percentage is None else D(percentage),
        )

    result = validate_estimate(product)

    assert result.nutrients == {}
    assert result.confidence == {}
    assert result.checks["energy"].verdict is Verdict.NOT_ESTIMATED
    assert Problem.IMPOSSIBLE in [w.problem for w in result.warnings]


def test_a_product_without_ingredients_has_no_estimate_and_keeps_its_declaration(
    source: Source,
):
    result = validate_estimate(product_of(energy="500"))

    assert (result.nutrients, result.confidence) == ({}, {})
    assert result.checks["energy"].verdict is Verdict.NOT_ESTIMATED


def test_a_product_is_validated_in_a_few_queries_however_many_ingredients(
    source: Source, django_assert_max_num_queries: Any
):
    refs = [reference(source, str(i), vitamin_c=str(i + 1)) for i in range(6)]
    product = product_of(*refs, proteins="15", energy="500")

    # What the estimate of the nutrients takes, and the declared nutrients.
    with django_assert_max_num_queries(5 + 6 + 1):
        validate_estimate(product)
