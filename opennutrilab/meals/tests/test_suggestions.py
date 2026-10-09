from datetime import date
from decimal import Decimal
from http import HTTPStatus
from typing import Any

import pytest
from django.test import Client

from opennutrilab.meals.models import Meal
from opennutrilab.meals.models import Profile
from opennutrilab.meals.services import limits
from opennutrilab.meals.services import suggestions
from opennutrilab.meals.services.day_report import DayReport
from opennutrilab.meals.services.day_report import GenericItem
from opennutrilab.meals.services.day_report import Status
from opennutrilab.meals.services.day_report import report_of
from opennutrilab.meals.services.needs import daily_needs
from opennutrilab.meals.services.optimiser import Plan
from opennutrilab.meals.services.proposals import NoProfileError
from opennutrilab.meals.services.suggestions import Gap
from opennutrilab.meals.services.suggestions import Row
from opennutrilab.meals.tests.conftest import make_product
from opennutrilab.meals.tests.conftest import make_profile
from opennutrilab.meals.tests.conftest import stock
from opennutrilab.meals.tests.test_day_report import meal_of
from opennutrilab.meals.tests.test_day_report import put
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.reference_composition import Measure
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

D = Decimal
DAY = date(2026, 10, 9)
OATS = "3229820794556"
PRODUCE = "fruits, légumes, légumineuses et oléagineux"
EXACT = SourceFoodNutrient.Qualifier.EXACT
TRACES = SourceFoodNutrient.Qualifier.TRACES
# What a day holds of the foods the tests name.
MOST_OIL, MOST_FISH, MOST_NUTS = 30.0, 200.0, 50.0


def ciqual_food(
    source: Source,
    code: str,
    name: str,
    where: tuple[str, str],
    **amounts: str,
) -> SourceFood:
    group, subgroup = where
    food = SourceFood.objects.create(
        source=source,
        code=code,
        name_fr=name,
        name_en=name,
        food_group=group,
        food_subgroup=subgroup,
    )
    for nutrient, amount in amounts.items():
        SourceFoodNutrient.objects.create(
            food=food,
            nutrient=Nutrient.objects.get(code=nutrient),
            amount=D(amount),
            confidence="A",
        )
    return food


@pytest.fixture
def table(catalogue: None) -> Source:
    """A small CIQUAL: foods that close gaps, and foods that are not suggested."""
    source = Source.objects.create(code="ciqual-2025", name="Ciqual", version="2025")
    oils = ("matières grasses", "huiles et graisses végétales")
    fish = ("viandes, oeufs, poissons", "poissons crus")
    ciqual_food(
        source, "17180", "Huile de lin", oils,
        energy="3700", fat="100", alpha_linolenic_acid="53.4", linoleic_acid="14.2",
    )  # fmt: skip
    ciqual_food(
        source, "26141", "Foie de morue", fish,
        energy="2400", fat="50", epa="6.41", dha="4.76", vitamin_d="100",
    )  # fmt: skip
    ciqual_food(
        source, "13000", "Orange", (PRODUCE, "fruits"), energy="190", vitamin_c="53"
    )
    # What is not suggested.
    ciqual_food(
        source, "5000", "Bière", ("eaux et autres boissons", "boisson alcoolisées"),
        energy="170", vitamin_b6="0.2", vitamin_c="500",
    )  # fmt: skip
    ciqual_food(
        source, "11000", "Petit pot", ("aliments infantiles", "plats infantiles"),
        energy="300", vitamin_c="500",
    )  # fmt: skip
    ciqual_food(
        source, "11058", "Sel",
        ("aides culinaires et ingrédients divers", "sels"),
        energy="1", sodium="39000", vitamin_c="500",
    )  # fmt: skip
    ciqual_food(
        source, "18066", "Eau du robinet", ("eaux et autres boissons", "eaux"),
        energy="0", vitamin_c="500",
    )  # fmt: skip
    return source


# ----------------------------------------------------------------------------
# How much of a food, and how it is counted
# ----------------------------------------------------------------------------
def row(group: str = "", subgroup: str = "", **amounts: float) -> Row:
    return Row(1, "1", "Aliment", "Food", group, subgroup, dict(amounts))


def test_the_most_of_a_food_in_a_day_goes_by_its_subgroup_then_its_group():
    most = suggestions.most_grams

    assert most(row("matières grasses", "beurres")) == MOST_OIL
    assert most(row("matières grasses", "huiles de poissons")) == 20.0  # noqa: PLR2004
    assert most(row("viandes, oeufs, poissons", "poissons crus")) == MOST_FISH
    assert most(row(PRODUCE, "fruits")) == suggestions.DEFAULT_MOST_GRAMS
    nuts = "fruits à coque et graines oléagineuses"
    assert most(row(PRODUCE, nuts)) == MOST_NUTS


def measure(amount: str | None, low: str = "0", high: str | None = None) -> Measure:
    return Measure(
        None if amount is None else D(amount),
        D(low),
        None if high is None else D(high),
        EXACT if amount is not None else TRACES,
        "A",
    )


def test_a_trace_is_nothing_with_no_upper_end_and_a_measure_keeps_its_interval():
    found = suggestions.amounts_of(
        {"iron": measure("2.5", "2", "3"), "iodine": measure(None)}
    )

    iron = found["iron"]
    assert (iron.amount, iron.low, iron.high) == (D("2.5"), D(2), D(3))
    assert (found["iodine"].amount, found["iodine"].high) == (D(0), None)
    assert iron.coverage == D(100)
    assert iron.declared is False


def test_omega_totals_of_a_food_add_the_parts_it_has_and_are_whole_with_all():
    some = suggestions.amounts_of({"alpha_linolenic_acid": measure("50", "49", "51")})
    every = suggestions.amounts_of(
        {
            "alpha_linolenic_acid": measure("2", "2", "2"),
            "epa": measure("3", "3", "3"),
            "dha": measure("4", "4", "4"),
        }
    )

    assert some["omega_3"].amount == D(50)
    assert (some["omega_3"].high, some["omega_3"].coverage) == (None, D(0))
    assert every["omega_3"].amount == D(9)
    assert (every["omega_3"].high, every["omega_3"].coverage) == (D(9), D(100))
    assert "omega_6" not in some


# ----------------------------------------------------------------------------
# The foods looked at
# ----------------------------------------------------------------------------
def test_the_foods_looked_at_are_those_that_give_the_most_of_what_is_missed(
    table: Source,
):
    gap = Gap("Vitamine C", "mg", {"vitamin_c": 1.0}, 110.0)

    found = suggestions.foods_to_look_at([gap])

    # Only the orange: the beer, the baby food, the salt and the water give far more
    # and are not suggested, and the oils and the liver give none.
    assert [f.code for f in found] == ["13000"]


def test_a_food_that_gives_too_little_of_a_gap_is_not_looked_at(table: Source):
    # An orange at 200 g gives 106 mg of 5,000: not a fifth of it.
    gap = Gap("Vitamine C", "mg", {"vitamin_c": 1.0}, 5000.0)

    assert suggestions.foods_to_look_at([gap]) == []


def test_the_share_a_food_gives_is_counted_at_the_most_a_day_holds_of_it(
    table: Source,
):
    # Linseed oil is 53 g of alpha-linolenic acid in 100 g, but a day holds 30 g.
    gap = Gap("ALA", "g", {"alpha_linolenic_acid": 1.0}, 16.0)

    [found] = suggestions.foods_to_look_at([gap])

    assert found.code == "17180"
    share = suggestions._share(found, gap)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert share == pytest.approx(53.4 * MOST_OIL / 100 / 16.0)


def test_the_omega_totals_are_sought_through_their_parts(table: Source):
    gap = Gap("Omega-3", "g", {"omega_3": 1.0}, 11.0)

    codes = [f.code for f in suggestions.foods_to_look_at([gap])]

    # The liver (11 g of omega-3 in 100 g, 200 g a day) and the oil (53 g, 30 g).
    assert set(codes) == {"26141", "17180"}


def test_what_is_not_a_food_for_an_adult_or_is_drunk_or_has_no_energy_is_left_out(
    table: Source,
):
    # Each of the foods that are left out gives 500 mg of vitamin C in 100 g.
    gap = Gap("Vitamine C", "mg", {"vitamin_c": 1.0}, 50.0)

    found = {f.code for f in suggestions.foods_to_look_at([gap])}

    # Not the beer, the baby food, the salt, nor the water (which has no energy).
    assert found.isdisjoint({"5000", "11000", "11058", "18066"})
    assert found == {"13000"}


# ----------------------------------------------------------------------------
# What a day is below
# ----------------------------------------------------------------------------
@pytest.fixture
def below(user: User, catalogue: None) -> DayReport:
    """A day of oats alone, which is below most of what a man needs."""
    make_profile(user)
    stock(user, make_product(OATS, energy="1600", proteins="12", fat="6", fiber="10"))
    put(meal_of(user, "breakfast"), OATS, "300")
    return report_of(user, DAY, {"breakfast": list(Meal.objects.get().items.all())})


def test_a_gap_is_a_lower_end_the_day_does_not_reach(user: User, below: DayReport):
    gaps = suggestions.gaps_of(below, daily_needs(Profile.objects.get(user=user)))

    # The oats have none of it, and a man needs 110 mg.
    [vitamin_c] = [gap for gap in gaps if gap.terms == {"vitamin_c": 1.0}]
    assert vitamin_c.reference == 110.0  # noqa: PLR2004
    assert vitamin_c.unit == "mg"
    # Their 30 g of fibre in 300 g meet the need: it is no gap.
    assert all(gap.terms != {"fiber": 1.0} for gap in gaps)
    # Sodium is salt's to meet and energy the optimiser's: none is looked for.
    assert all("sodium" not in gap.terms for gap in gaps)
    assert all("energy" not in gap.terms for gap in gaps)


def test_the_gaps_of_a_ratio_name_what_is_raised_and_the_ratio(
    user: User, below: DayReport
):
    gaps = suggestions.gaps_of(below, daily_needs(Profile.objects.get(user=user)))

    # A need is named as itself, with nothing raised; a ratio by its two sides.
    for gap in gaps:
        assert (gap.raised == "") == (" / " not in gap.name)


def test_how_many_needs_and_ratios_are_not_met_is_counted(below: DayReport):
    statuses = [*(below.needs or []), *(below.ratios or [])]

    assert suggestions.missed(below) == sum(
        1 for s in statuses if s.verdict.status != Status.WITHIN
    )
    assert 0 < suggestions.missed(below) <= len(statuses)


# ----------------------------------------------------------------------------
# A suggestion
# ----------------------------------------------------------------------------
@pytest.fixture
def oats_stocked(user: User, catalogue: None) -> Product:
    product = make_product(
        OATS, energy="1600", proteins="12", fat="6", carbohydrates="60", fiber="10"
    )
    stock(user, product)
    return product


def test_a_day_cannot_be_suggested_for_without_a_profile(
    user: User, oats_stocked: Product, table: Source
):
    with pytest.raises(NoProfileError):
        suggestions.suggest_foods(user, DAY)


def test_foods_are_suggested_that_close_what_the_inventory_misses(
    user: User, oats_stocked: Product, table: Source
):
    make_profile(user)

    found = suggestions.suggest_foods(user, DAY)

    assert found.status == "optimal"
    assert found.missed_after < found.missed_before <= found.total
    names = {suggested.food.name for suggested in found.foods}
    # What the oats lack is in the oil, the liver and the orange; none of what is not
    # suggested is among them.
    assert names
    assert names <= {"Huile de lin", "Foie de morue", "Orange"}
    assert len(found.foods) <= suggestions.MOST_NEW
    for suggested in found.foods:
        assert suggested.helps
        assert suggested.grams == sum(g for _kind, g in suggested.picks)
        url = f"https://ciqual.anses.fr/#/aliments/{suggested.food.code}"
        assert suggested.food.url == url
        # In one meal, to be got and eaten.
        assert len(suggested.picks) == 1
    # Nothing is written.
    assert not Meal.objects.exists()


def test_a_product_asked_for_whole_is_all_in_the_day_with_the_suggested_foods_too(
    user: User, oats_stocked: Product, table: Source
):
    make_profile(user)
    Product.objects.filter(pk=OATS).update(package_quantity=D(375), package_unit="g")
    oats_stocked.refresh_from_db()
    limits.set_limits(user, oats_stocked, [], None, None, use_all=True)

    found = suggestions.suggest_foods(user, DAY)

    assert found.foods
    for report in (found.base, found.report):
        oats = [
            item
            for meal in report.meals
            for item in meal.items
            if getattr(item, "product", None) == oats_stocked
        ]
        assert oats
        assert sum(item.quantity for item in oats) == D(375)


def test_a_suggested_food_is_in_the_day_reported_as_an_item_that_is_not_saved(
    user: User, oats_stocked: Product, table: Source
):
    make_profile(user)

    found = suggestions.suggest_foods(user, DAY)

    generic = [
        item
        for meal in found.report.meals
        for item in meal.items
        if isinstance(item, GenericItem)
    ]
    assert {item.food.name for item in generic} == {s.food.name for s in found.foods}
    assert all(item.id is None and item.unit == "g" for item in generic)
    # And the day without them is the best day from the inventory alone.
    assert not any(
        isinstance(item, GenericItem)
        for meal in found.base.meals
        for item in meal.items
    )


def test_each_food_says_what_it_closes_and_how_much_of_it(
    user: User, oats_stocked: Product, table: Source
):
    make_profile(user)

    found = suggestions.suggest_foods(user, DAY)

    for suggested in found.foods:
        # Said once, whatever the gaps it closes.
        seen = [(h.amount, h.unit) for h in suggested.helps]
        assert len(set(seen)) == len(seen)
        assert all(h.share >= D("0.2") and h.amount > 0 for h in suggested.helps)
    oranges = [s for s in found.foods if s.food.name == "Orange"]
    for orange in oranges:
        vitamin_c = next(h for h in orange.helps if "C" in h.name)
        assert vitamin_c.unit == "mg"


def test_nothing_is_suggested_when_the_inventory_misses_nothing(
    user: User, oats_stocked: Product, table: Source, monkeypatch: pytest.MonkeyPatch
):
    make_profile(user)
    monkeypatch.setattr(suggestions, "gaps_of", lambda *_args: [])

    found = suggestions.suggest_foods(user, DAY)

    assert (found.status, found.foods) == ("no_gaps", [])
    assert found.report is found.base
    assert found.missed_before == found.missed_after


def test_nothing_is_suggested_when_there_is_no_table_to_look_in(
    user: User, oats_stocked: Product, catalogue: None
):
    make_profile(user)

    found = suggestions.suggest_foods(user, DAY)

    assert (found.status, found.foods) == ("no_foods", [])


def _after_the_first(replace: Plan, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every call of the optimiser but the first answer `replace`."""
    real = suggestions.optimise
    calls: list[int] = []

    def optimise(*args: Any, **kwargs: Any) -> Plan:
        calls.append(1)
        # The first is the best day from the inventory; the second, the choice.
        return real(*args, **kwargs) if len(calls) == 1 else replace

    monkeypatch.setattr(suggestions, "optimise", optimise)


def test_nothing_is_suggested_when_none_is_worth_its_price(
    user: User, oats_stocked: Product, table: Source, monkeypatch: pytest.MonkeyPatch
):
    make_profile(user)
    _after_the_first(Plan("optimal", 1.0, []), monkeypatch)

    found = suggestions.suggest_foods(user, DAY)

    assert (found.status, found.foods) == ("no_suggestion", [])
    assert found.missed_before == found.missed_after


def test_no_day_is_given_when_the_solver_finds_none(
    user: User, oats_stocked: Product, table: Source, monkeypatch: pytest.MonkeyPatch
):
    make_profile(user)
    _after_the_first(Plan("failed", None, []), monkeypatch)

    assert suggestions.suggest_foods(user, DAY).status == "failed"


def test_the_inventory_of_others_is_not_counted(
    user: User, oats_stocked: Product, table: Source
):
    make_profile(user)
    other = make_product("3017620422003", energy="2500", vitamin_c="900")
    stock(UserFactory(), other)

    found = suggestions.suggest_foods(user, DAY)

    assert all(
        item.product_id != other.pk
        for meal in found.report.meals
        for item in meal.items
    )


# ----------------------------------------------------------------------------
# The API
# ----------------------------------------------------------------------------
API = "/api/v1/meals/2026-10-09/suggest"


@pytest.fixture
def api_client(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def test_the_suggestions_come_with_the_day_they_make(
    api_client: Client, user: User, oats_stocked: Product, table: Source
):
    make_profile(user)

    response = api_client.post(API)

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["status"] == "optimal"
    assert body["missed_after"] < body["missed_before"] <= body["total"]
    [first, *_] = body["foods"]
    assert set(first) == {"code", "name", "group", "url", "grams", "meals", "helps"}
    assert first["meals"][0]["kind"] in {"breakfast", "lunch", "snack", "dinner"}
    assert first["meals"][0]["label"]
    assert set(first["helps"][0]) == {"name", "unit", "amount", "share", "raised"}
    # The day has them as items that are not products, with their sheet.
    items = [i for m in body["day"]["meals"] for i in m["items"]]
    generic = [i for i in items if i["generic"]]
    assert {i["name"] for i in generic} == {f["name"] for f in body["foods"]}
    assert all(i["id"] is None for i in generic)
    assert all(i["url"].startswith("https://ciqual") for i in generic)
    assert all(i["serving"] is None for i in generic)
    assert not any(i["generic"] for i in items if i["barcode"] == OATS)
    assert not Meal.objects.exists()


def test_suggestions_need_a_profile(
    api_client: Client, oats_stocked: Product, table: Source
):
    response = api_client.post(API)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "profile" in response.json()["detail"]


def test_suggestions_need_a_signed_in_user(client: Client, db: None):
    assert client.post(API).status_code == HTTPStatus.UNAUTHORIZED
