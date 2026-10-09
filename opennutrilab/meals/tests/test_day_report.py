from decimal import Decimal

from opennutrilab.meals.models import Meal
from opennutrilab.meals.models import MealItem
from opennutrilab.meals.models import Profile
from opennutrilab.meals.services.day_report import NOTHING
from opennutrilab.meals.services.day_report import Portion
from opennutrilab.meals.services.day_report import Status
from opennutrilab.meals.services.day_report import Total
from opennutrilab.meals.services.day_report import add_up
from opennutrilab.meals.services.day_report import combine
from opennutrilab.meals.services.day_report import day_report
from opennutrilab.meals.services.day_report import ratio_of
from opennutrilab.meals.services.day_report import verdict
from opennutrilab.meals.tests.conftest import DAY
from opennutrilab.meals.tests.conftest import make_product
from opennutrilab.products.services.stored_estimates import Amount
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

D = Decimal


def amount(
    value: str,
    low: str | None = None,
    high: str | None = None,
    coverage: str = "100",
) -> Amount:
    return Amount(
        amount=D(value),
        low=D(low or value),
        high=None if high is None else D(high),
        coverage=D(coverage),
        declared=False,
    )


def total(
    value: str, low: str | None = None, high: str | None = None, coverage: str = "100"
) -> Total:
    return Total(
        D(value), D(low or value), None if high is None else D(high), D(coverage)
    )


# ----------------------------------------------------------------------------
# Adding portions up
# ----------------------------------------------------------------------------
def test_a_portion_brings_its_composition_times_grams_over_a_hundred():
    portions = [
        Portion(D(100), {"fat": amount("10", "9", "11")}),
        Portion(D(50), {"fat": amount("20", "18", "22")}),
    ]

    assert add_up(portions) == {"fat": total("20", "18", "22")}


def test_a_nutrient_a_product_lacks_counts_as_nothing_with_no_upper_end():
    portions = [
        Portion(D(100), {"fat": amount("10", "10", "10")}),
        Portion(D(50), {}),
    ]

    result = add_up(portions)["fat"]

    assert (result.amount, result.low, result.high) == (D(10), D(10), None)
    # 100 g of the 150 give a value.
    assert round(result.coverage, 2) == D("66.67")


def test_the_coverage_of_a_partly_covered_product_weighs_its_grams():
    portions = [Portion(D(100), {"iron": amount("2", "2", None, "50")})]

    assert add_up(portions)["iron"].coverage == D(50)


def test_a_nutrient_no_portion_gives_is_not_a_total_and_nothing_adds_up_to_nothing():
    assert add_up([Portion(D(100), {"fat": amount("1")})]).keys() == {"fat"}
    assert add_up([]) == {}


def test_nutrients_given_by_some_only_are_totals_of_those():
    portions = [
        Portion(D(100), {"fat": amount("1", "1", "1")}),
        Portion(D(100), {"fiber": amount("5", "5", "5")}),
    ]

    result = add_up(portions)

    assert result["fat"] == total("1", "1", None, "50")
    assert result["fiber"] == total("5", "5", None, "50")


# ----------------------------------------------------------------------------
# A sum of nutrients
# ----------------------------------------------------------------------------
def test_a_sum_of_nutrients_adds_their_totals_and_is_as_covered_as_the_least():
    totals = {
        "epa": total("0.2", "0.1", "0.3", "100"),
        "dha": total("0.3", "0.2", "0.5", "40"),
    }

    result = combine(totals, {"epa": D(1), "dha": D(1)})

    assert result == total("0.5", "0.3", "0.8", "40")


def test_a_nutrient_nothing_gives_counts_as_nothing_known_for_none_of_the_mass():
    result = combine({"epa": total("1")}, {"epa": D(1), "dha": D(1)})

    assert (result.amount, result.high, result.coverage) == (D(1), None, D(0))
    assert combine({}, {"epa": D(1)}) == NOTHING


def test_a_sum_can_be_weighted():
    result = combine({"sodium": total("100")}, {"sodium": D("0.5")})

    assert result.amount == D(50)


# ----------------------------------------------------------------------------
# Below, within or above a need
# ----------------------------------------------------------------------------
def test_a_total_whose_upper_end_is_below_the_need_is_below_for_certain():
    result = verdict(total("8", "7", "9"), D(10), None)

    assert (result.status, result.certain) == (Status.BELOW, True)


def test_a_total_that_could_reach_the_need_is_below_but_not_for_certain():
    result = verdict(total("8", "7", "11"), D(10), None)
    open_ended = verdict(total("8", "7", None), D(10), None)

    assert (result.status, result.certain) == (Status.BELOW, False)
    assert (open_ended.status, open_ended.certain) == (Status.BELOW, False)


def test_a_total_whose_lower_end_is_above_the_limit_is_above_for_certain():
    sure = verdict(total("12", "11", "13"), None, D(10))
    unsure = verdict(total("12", "9", "13"), None, D(10))

    assert (sure.status, sure.certain) == (Status.ABOVE, True)
    assert (unsure.status, unsure.certain) == (Status.ABOVE, False)


def test_a_total_is_within_for_certain_when_the_whole_interval_is():
    sure = verdict(total("10", "9", "11"), D(8), D(12))
    too_wide = verdict(total("10", "7", "11"), D(8), D(12))
    no_upper_end = verdict(total("10", "9", None), D(8), D(12))
    no_limit = verdict(total("10", "9", None), D(8), None)

    assert [
        (v.status, v.certain) for v in (sure, too_wide, no_upper_end, no_limit)
    ] == [
        (Status.WITHIN, True),
        (Status.WITHIN, False),
        (Status.WITHIN, False),
        (Status.WITHIN, True),
    ]


def test_the_ends_of_a_need_are_within_it():
    assert verdict(total("10"), D(10), D(10)).status == Status.WITHIN


# ----------------------------------------------------------------------------
# Ratios
# ----------------------------------------------------------------------------
def test_a_ratio_is_one_total_over_another_with_its_interval():
    totals = {"dha": total("2", "1", "3"), "epa": total("1", "0.5", "2")}

    result = ratio_of(totals, {"dha": D(1)}, {"epa": D(1)})

    assert result is not None
    assert result.amount == D(2)
    # At lowest, the lowest DHA over the highest EPA; at highest, the reverse.
    assert (result.low, result.high) == (D("0.5"), D(6))


def test_a_ratio_over_a_denominator_with_no_upper_end_has_none_either():
    totals = {"dha": total("2", "1", "3"), "epa": total("1", "0.5", None)}

    result = ratio_of(totals, {"dha": D(1)}, {"epa": D(1)})

    assert result is not None
    assert (result.low, result.high) == (D(0), D(6))


def test_a_ratio_over_nothing_is_not_one():
    assert ratio_of({"dha": total("1")}, {"dha": D(1)}, {"epa": D(1)}) is None


def test_a_ratio_can_be_in_moles():
    totals = {"sodium": total("2300"), "potassium": total("3900")}

    result = ratio_of(totals, {"sodium": D("0.043498")}, {"potassium": D("0.025577")})

    assert result is not None
    assert round(result.amount, 3) == D("1.003")


# ----------------------------------------------------------------------------
# A day from the database
# ----------------------------------------------------------------------------
def meal_of(user: User, kind: str = "breakfast") -> Meal:
    return Meal.objects.get_or_create(user=user, date=DAY, kind=kind)[0]


def put(meal: Meal, product: str, quantity: str, unit: str = "g") -> MealItem:
    return MealItem.objects.create(
        meal=meal, product_id=product, quantity=D(quantity), unit=unit
    )


def test_a_meal_and_the_day_add_up_what_the_label_declares(user: User, catalogue: None):
    make_product("1111111111116", serving="50", energy="1000", proteins="10")
    make_product("2222222222222", energy="500", proteins="4")
    breakfast, lunch = meal_of(user), meal_of(user, "lunch")
    put(breakfast, "1111111111116", "2", "serving")  # 100 g
    put(breakfast, "2222222222222", "200")
    put(lunch, "2222222222222", "100")

    report = day_report(user, DAY)

    by_kind = {meal.kind: meal for meal in report.meals}
    assert [meal.kind for meal in report.meals] == [
        "breakfast",
        "lunch",
        "snack",
        "dinner",
    ]
    assert by_kind["breakfast"].mass == D(300)
    assert by_kind["breakfast"].totals["energy"].amount == D(2000)
    assert by_kind["lunch"].totals["proteins"].amount == D(4)
    assert by_kind["snack"].items == []
    assert by_kind["snack"].totals == {}
    # The day is the sum of its meals, covered whole by what labels declare.
    assert report.mass == D(400)
    assert report.totals["energy"].amount == D(2500)
    assert report.totals["energy"].coverage == D(100)
    assert report.totals["proteins"].amount == D(22)


def test_a_declared_figure_has_the_rounding_it_is_written_with(
    user: User, catalogue: None
):
    make_product("1111111111116", proteins="10")
    put(meal_of(user), "1111111111116", "100")

    proteins = day_report(user, DAY).totals["proteins"]

    assert (proteins.amount, proteins.low, proteins.high) == (
        D(10),
        D("9.5"),
        D("10.5"),
    )


def test_a_day_is_the_users_own_and_that_date_only(user: User, catalogue: None):
    make_product("1111111111116", energy="1000")
    other = UserFactory()
    put(meal_of(other), "1111111111116", "100")
    put(
        Meal.objects.create(user=user, date=DAY.replace(day=8), kind="lunch"),
        "1111111111116",
        "100",
    )

    report = day_report(user, DAY)

    assert report.totals == {}
    assert report.mass == D(0)


def test_servings_of_a_product_that_lost_its_serving_are_left_out(
    user: User, catalogue: None
):
    product = make_product("1111111111116", serving="50", energy="1000")
    item = put(meal_of(user), "1111111111116", "2", "serving")
    product.serving_quantity = None
    product.serving_unit = ""
    product.save()

    report = day_report(user, DAY)

    assert item.grams is None or MealItem.objects.get(pk=item.pk).grams is None
    assert report.mass == D(0)
    assert report.totals == {}
    # The item is still there to be seen, and to be put right.
    assert [i.id for i in report.meals[0].items] == [item.pk]


def test_without_a_profile_there_are_no_needs(user: User, catalogue: None):
    report = day_report(user, DAY)

    assert report.needs is None
    assert report.ratios is None


def test_with_a_profile_the_day_is_set_against_the_needs(user: User, catalogue: None):
    Profile.objects.create(
        user=user,
        sex="male",
        birth_year=1995,
        height=D(180),
        weight=D(61),
        activity_level=D("1.7"),
    )
    make_product("1111111111116", energy="1000", proteins="100", fiber="10")
    put(meal_of(user), "1111111111116", "300")

    report = day_report(user, DAY)

    assert report.needs is not None
    assert report.ratios is not None
    by_name = {status.need.nutrients: status for status in report.needs}
    energy = by_name[("energy",)]
    # 3000 kJ of the 10536 to 11645 the person needs.
    assert (energy.total.amount, energy.verdict.status) == (D(3000), Status.BELOW)
    assert energy.unit == "kJ"
    fiber = by_name[("fiber",)]
    assert (fiber.total.amount, fiber.verdict.status) == (D(30), Status.WITHIN)
    # A need on a sum, and one on a nutrient nothing gives.
    assert by_name[("epa", "dha")].total == NOTHING
    assert by_name[("epa", "dha")].verdict.status == Status.BELOW
    # The omega ratio is over nothing here.
    omega = [r for r in report.ratios if r.denominator.startswith("Omega-6")]
    assert [(r.value, r.verdict.status) for r in omega] == [(None, Status.UNKNOWN)]
    # What the names are for the page.
    assert report.catalogue["energy"].unit == "kJ"


def test_the_estimate_of_a_product_fills_in_what_its_label_does_not(
    user: User, catalogue: None
):
    # A product with no ingredient has no estimate: only what is declared counts.
    make_product("1111111111116", energy="1000")
    put(meal_of(user), "1111111111116", "100")

    report = day_report(user, DAY)

    assert set(report.totals) == {"energy"}
