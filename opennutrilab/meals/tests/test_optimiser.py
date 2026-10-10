"""
The optimiser on small made-up cases whose best day is known.

The products are made up with round figures, so that what a day brings can be
worked out by hand: `brought` adds up the picks the same way the optimiser does.
"""

from collections.abc import Mapping
from decimal import Decimal
from types import SimpleNamespace

import pytest

from opennutrilab.meals.services import optimiser
from opennutrilab.meals.services.energy import KJ_PER_KCAL
from opennutrilab.meals.services.needs import Kind
from opennutrilab.meals.services.needs import Need
from opennutrilab.meals.services.needs import Needs
from opennutrilab.meals.services.needs import Ratio
from opennutrilab.meals.services.optimiser import DEFAULT_SPLIT
from opennutrilab.meals.services.optimiser import KINDS
from opennutrilab.meals.services.optimiser import Candidate
from opennutrilab.meals.services.optimiser import Eaten
from opennutrilab.meals.services.optimiser import Options
from opennutrilab.meals.services.optimiser import Plan
from opennutrilab.meals.services.optimiser import Weights
from opennutrilab.meals.services.optimiser import optimise

D = Decimal
ALL = frozenset(KINDS)
KCAL = 2000
KJ = float(KCAL * KJ_PER_KCAL)
# What a day brings is worked out to this precision.
EPSILON = 1e-6
# The grams of EPA and DHA a day needs, and the user's ratio between them.
EPA_DHA_NEED = 5.0
RATIO_LOW, RATIO_HIGH = 0.9, 1.1


def product(
    barcode: str,
    per_100g: Mapping[str, float],
    *,
    max_grams: float = 600.0,
    meals: frozenset[str] = ALL,
) -> Candidate:
    """A product counted in steps of 10 g."""
    return Candidate(
        barcode=barcode,
        name=barcode,
        per_100g=per_100g,
        step_grams=10.0,
        step_quantity=10.0,
        unit="g",
        max_grams=max_grams,
        meals=meals,
    )


def need(
    code: tuple[str, ...], low: float | None = None, high: float | None = None
) -> Need:
    return Need(
        nutrients=code,
        low=None if low is None else D(str(low)),
        high=None if high is None else D(str(high)),
        low_kind=Kind.RNP if low is not None else "",
        high_kind=Kind.LSS if high is not None else "",
        low_source="test",
        high_source="test",
    )


def needs_of(*needs: Need, ratios: tuple[Ratio, ...] = ()) -> Needs:
    return Needs(
        energy=D(KCAL),
        energy_low=D(KCAL) * D("0.95"),
        energy_high=D(KCAL) * D("1.05"),
        basal_metabolisms={},
        nutrients=[need(("energy",), KJ * 0.95, KJ * 1.05), *needs],
        ratios=list(ratios),
    )


def dha_over_epa() -> Ratio:
    return Ratio(
        {"dha": D(1)},
        {"epa": D(1)},
        D(str(RATIO_LOW)),
        D(str(RATIO_HIGH)),
        Kind.TARGET,
        "user",
    )


def brought(
    plan: Plan,
    candidates: list[Candidate],
    code: str,
    kinds: tuple[str, ...] = KINDS,
) -> float:
    by_barcode = {c.barcode: c for c in candidates}
    return sum(
        pick.grams / 100 * by_barcode[pick.barcode].per_100g.get(code, 0.0)
        for pick in plan.picks
        if pick.kind in kinds
    )


# Oats: energy and a little protein. 10 g is 160 kJ and 0.5 g of protein.
OATS = product("oats", {"energy": 1600, "proteins": 5})
# Lentils: less energy, five times the protein.
LENTILS = product("lentils", {"energy": 1000, "proteins": 25})
# Fish oil has twice as much DHA as EPA, algae oil the other way round.
FISH = product("fish", {"energy": 3000, "dha": 20, "epa": 10}, max_grams=50)
ALGAE = product("algae", {"energy": 3000, "dha": 10, "epa": 20}, max_grams=50)


def test_the_energy_of_the_day_is_the_needs():
    candidates = [OATS]

    plan = optimise(candidates, needs_of())

    assert plan.status == "optimal"
    assert KJ * 0.95 <= brought(plan, candidates, "energy") <= KJ * 1.05


def test_the_energy_is_shared_between_the_meals():
    candidates = [OATS]

    plan = optimise(candidates, needs_of())

    for kind, share in DEFAULT_SPLIT.items():
        meal = brought(plan, candidates, "energy", (kind,))
        assert share * KJ * 0.75 <= meal <= share * KJ * 1.25, kind


def test_a_need_only_one_product_can_meet_is_met_by_it():
    # 60 g of protein a day: oats alone would need 1.2 kg and 19,200 kJ, more than
    # twice the day's energy. Lentils give it for 240 g and 2,400 kJ, and the oats
    # make up the rest of the energy.
    candidates = [OATS, LENTILS]

    plan = optimise(candidates, needs_of(need(("proteins",), low=60)))

    assert brought(plan, candidates, "proteins") >= 60 - EPSILON
    assert KJ * 0.95 <= brought(plan, candidates, "energy") <= KJ * 1.05
    assert {pick.barcode for pick in plan.picks} == {"oats", "lentils"}


def test_a_limit_is_not_passed_when_a_product_could_pass_it():
    # The oats alone give 25 g of protein for the day's energy; lentils bring the
    # 30 g, and 40 g is all the day may have of it.
    candidates = [OATS, LENTILS]

    plan = optimise(candidates, needs_of(need(("proteins",), low=30, high=40)))

    protein = brought(plan, candidates, "proteins")
    assert 30 - EPSILON <= protein <= 40 + EPSILON


def test_the_most_of_a_product_in_a_day_is_not_passed():
    capped = product("oats", {"energy": 1600, "proteins": 5}, max_grams=100)

    plan = optimise([capped], needs_of())

    assert sum(pick.grams for pick in plan.picks) <= 100 + EPSILON
    # And the day then misses its energy: it is still a plan.
    assert plan.status == "optimal"
    assert brought(plan, [capped], "energy") == capped.per_100g["energy"]


def test_a_product_is_only_in_the_meals_it_may_be_in():
    snack_only = product("bar", {"energy": 1800}, meals=frozenset({"snack"}))

    plan = optimise([OATS, snack_only], needs_of())

    assert {pick.kind for pick in plan.picks if pick.barcode == "bar"} <= {"snack"}


def test_a_product_that_cannot_be_in_any_meal_is_left_out():
    nowhere = product("ghost", {"energy": 9000}, meals=frozenset())

    plan = optimise([OATS, nowhere], needs_of())

    assert "ghost" not in {pick.barcode for pick in plan.picks}


def test_a_product_whose_most_is_less_than_a_step_is_left_out():
    too_little = product("pinch", {"energy": 9000}, max_grams=5)

    plan = optimise([OATS, too_little], needs_of())

    assert "pinch" not in {pick.barcode for pick in plan.picks}


def test_a_step_is_half_a_serving_for_a_product_that_has_one():
    # 40 g servings, so a step is 20 g: whole and half servings only.
    bar = Candidate(
        "bar",
        "bar",
        {"energy": 2000},
        step_grams=20,
        step_quantity=0.5,
        unit="serving",
        max_grams=240,
        meals=ALL,
    )

    plan = optimise([bar], needs_of())

    assert plan.picks
    for pick in plan.picks:
        assert pick.unit == "serving"
        assert pick.grams == pick.steps * 20
        assert pick.quantity == pick.steps * 0.5


def test_a_need_nothing_can_meet_still_gives_a_day_and_the_cost_says_so():
    candidates = [OATS]
    meets = optimise(candidates, needs_of())
    misses = optimise(candidates, needs_of(need(("vitamin_d",), low=15)))

    assert misses.status == "optimal"
    assert misses.picks == meets.picks
    # A need missed whole costs its weight: 1.
    assert misses.objective is not None
    assert meets.objective is not None
    assert abs(misses.objective - meets.objective - 1.0) < EPSILON


def test_a_product_that_brings_nothing_is_not_used():
    useless = product("water", {"energy": 0})

    plan = optimise([OATS, useless], needs_of())

    assert "water" not in {pick.barcode for pick in plan.picks}


def test_of_two_equal_products_one_is_used():
    twin = product("twin", {"energy": 1600, "proteins": 5})

    plan = optimise([OATS, twin], needs_of())

    assert len({pick.barcode for pick in plan.picks}) == 1


def test_a_product_is_not_spread_over_meals_it_need_not_be_in():
    # With a split to keep, oats are in every meal; with none, in the fewest the
    # energy needs.
    plan = optimise([OATS], needs_of(), weights=Weights(split=0.0))

    assert len({pick.kind for pick in plan.picks}) == 1


def test_the_users_ratio_is_kept_between_two_products():
    # Equal parts of fish and algae oil give 1:1, and 0.9 to 1.1 is a band around it.
    candidates = [OATS, FISH, ALGAE]
    wanted = needs_of(need(("epa", "dha"), low=EPA_DHA_NEED), ratios=(dha_over_epa(),))

    plan = optimise(candidates, wanted)

    dha, epa = brought(plan, candidates, "dha"), brought(plan, candidates, "epa")
    assert dha + epa >= EPA_DHA_NEED - EPSILON
    assert RATIO_LOW - EPSILON <= dha / epa <= RATIO_HIGH + EPSILON


def test_a_ratio_the_user_weighs_little_is_given_up_for_a_need():
    # Only fish oil is on offer: its 2:1 cannot be 1:1. With the ratio worth little,
    # the need for EPA + DHA is met all the same.
    candidates = [OATS, FISH]
    wanted = needs_of(need(("epa", "dha"), low=EPA_DHA_NEED), ratios=(dha_over_epa(),))

    plan = optimise(candidates, wanted, weights=Weights(target=0.05))

    dha, epa = brought(plan, candidates, "dha"), brought(plan, candidates, "epa")
    assert dha + epa >= EPA_DHA_NEED - EPSILON
    assert dha / epa > RATIO_HIGH


def test_a_ratio_the_user_weighs_much_is_kept_at_the_price_of_the_need():
    # The same offer, the ratio worth much: no fish oil at all is the only way to
    # keep it, which the cost of a missed need is the price of.
    candidates = [OATS, FISH]
    wanted = needs_of(need(("epa", "dha"), low=EPA_DHA_NEED), ratios=(dha_over_epa(),))

    plan = optimise(candidates, wanted, weights=Weights(target=50.0))

    assert brought(plan, candidates, "dha") == 0
    assert brought(plan, candidates, "epa") == 0


def test_a_ratio_below_its_ceiling_is_kept_by_taking_less_of_the_numerator():
    # Linoleic over alpha-linolenic acid at most 5: seeds that are 6 to 1 and oil
    # that is 1 to 4.
    seeds = product(
        "seeds", {"energy": 2000, "linoleic_acid": 6, "alpha_linolenic_acid": 1}
    )
    linseed = product(
        "linseed",
        {"energy": 8000, "linoleic_acid": 1, "alpha_linolenic_acid": 4},
        max_grams=30,
    )
    ratio = Ratio(
        {"linoleic_acid": D(1)},
        {"alpha_linolenic_acid": D(1)},
        None,
        D(5),
        Kind.CONSTRAINT,
        "anses",
    )
    candidates = [seeds, linseed]

    plan = optimise(
        candidates, needs_of(need(("linoleic_acid",), low=10), ratios=(ratio,))
    )

    linoleic = brought(plan, candidates, "linoleic_acid")
    linolenic = brought(plan, candidates, "alpha_linolenic_acid")
    assert linoleic >= 10 - EPSILON
    assert linoleic / linolenic <= 5 + EPSILON


def test_the_same_inputs_give_the_same_day():
    candidates = [OATS, LENTILS]
    wanted = needs_of(need(("proteins",), low=60))

    assert optimise(candidates, wanted) == optimise(candidates, wanted)


def test_there_is_nothing_to_plan_without_a_product():
    plan = optimise([], needs_of())

    # Every need missed whole, and no product in the day.
    assert plan.picks == []
    assert plan.status in {"optimal", "failed"}


# ----------------------------------------------------------------------------
# What the solver may answer
# ----------------------------------------------------------------------------
def test_the_best_day_found_when_the_time_is_up_is_kept(
    monkeypatch: pytest.MonkeyPatch,
):
    real = optimiser.milp

    def out_of_time(**kwargs: object) -> SimpleNamespace:
        found = real(**kwargs)  # pyright: ignore[reportArgumentType]
        # HiGHS' status 1: a limit was reached, with the best solution so far.
        return SimpleNamespace(status=1, x=found.x, fun=found.fun)

    monkeypatch.setattr(optimiser, "milp", out_of_time)

    plan = optimise([OATS], needs_of())

    assert plan.status == "time_limit"
    assert plan.picks
    assert plan.objective is not None


def test_no_day_is_given_when_the_solver_finds_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        optimiser, "milp", lambda **_kwargs: SimpleNamespace(status=2, x=None, fun=None)
    )

    plan = optimise([OATS], needs_of())

    assert plan == Plan("failed", None, [])


# ----------------------------------------------------------------------------
# Foods that are not in the inventory
# ----------------------------------------------------------------------------
def new(
    barcode: str, per_100g: Mapping[str, float], max_grams: float = 50.0
) -> Candidate:
    return product(barcode, per_100g, max_grams=max_grams)._replace(new=True)


def test_a_new_food_is_taken_when_it_closes_a_need_the_inventory_cannot():
    flax = new("flax", {"energy": 3700, "alpha_linolenic_acid": 50})
    candidates = [OATS, flax]
    wanted = needs_of(need(("alpha_linolenic_acid",), low=EPA_DHA_NEED))

    without = optimise([OATS], wanted)
    with_new = optimise(candidates, wanted)

    assert "flax" not in {pick.barcode for pick in without.picks}
    assert (
        brought(with_new, candidates, "alpha_linolenic_acid") >= EPA_DHA_NEED - EPSILON
    )
    assert with_new.objective is not None
    assert without.objective is not None
    assert with_new.objective < without.objective


def test_a_new_food_that_closes_too_little_is_not_worth_its_price():
    # It brings a hundredth of the need for 10 g: much less than what it costs.
    weak = new("weak", {"energy": 1600, "alpha_linolenic_acid": 0.05})
    candidates = [OATS, weak]
    wanted = needs_of(need(("alpha_linolenic_acid",), low=EPA_DHA_NEED))

    plan = optimise(candidates, wanted)

    assert "weak" not in {pick.barcode for pick in plan.picks}


def test_the_same_food_is_cheaper_when_it_is_in_the_inventory():
    # A third of the need for a tenth of the price of a new food: the same food is
    # taken from the inventory, and not as a new one.
    seeds = {"energy": 1600, "alpha_linolenic_acid": 3.0}
    wanted = needs_of(need(("alpha_linolenic_acid",), low=EPA_DHA_NEED))
    owned = product("seeds", seeds, max_grams=50)
    bought = new("seeds", seeds)

    got = optimise([OATS, owned], wanted)
    asked = optimise([OATS, bought], wanted)

    assert got.objective is not None
    assert asked.objective is not None
    assert got.objective < asked.objective


def test_at_most_so_many_new_foods_are_used():
    foods = [
        new(f"food{n}", {"energy": 1600, f"nutrient{n}": 50.0}, max_grams=100)
        for n in range(4)
    ]
    wanted = needs_of(*(need((f"nutrient{n}",), low=10.0) for n in range(4)))

    free = optimise([OATS, *foods], wanted)
    capped = optimise([OATS, *foods], wanted, options=Options(max_new=2))

    used = {pick.barcode for pick in capped.picks} - {"oats"}
    assert len({p.barcode for p in free.picks} - {"oats"}) == 4  # noqa: PLR2004
    assert len(used) == 2  # noqa: PLR2004


def test_the_foods_of_the_inventory_are_not_counted_in_the_most_new():
    foods = [new("flax", {"energy": 3700, "alpha_linolenic_acid": 50})]
    wanted = needs_of(need(("alpha_linolenic_acid",), low=EPA_DHA_NEED))

    plan = optimise([OATS, LENTILS, *foods], wanted, options=Options(max_new=1))

    assert {"oats", "flax"} <= {pick.barcode for pick in plan.picks}


# ----------------------------------------------------------------------------
# A product required whole
# ----------------------------------------------------------------------------
def whole(
    barcode: str,
    per_100g: Mapping[str, float],
    grams: float,
    *,
    step: float = 10.0,
    meals: frozenset[str] = ALL,
) -> Candidate:
    """A product the day must have all of, which is this many grams."""
    return product(barcode, per_100g, max_grams=grams, meals=meals)._replace(
        step_grams=step, step_quantity=step, required_grams=grams
    )


def grams_of(plan: Plan, barcode: str) -> float:
    return sum(pick.grams for pick in plan.picks if pick.barcode == barcode)


def test_a_product_required_whole_is_all_in_the_day():
    jam = whole("jam", {"energy": 1000}, 200)

    plan = optimise([OATS, jam], needs_of())

    assert plan.status == "optimal"
    assert grams_of(plan, "jam") == pytest.approx(200)


def test_the_whole_is_shared_between_the_meals_it_may_be_in():
    jam = whole("jam", {"energy": 1000}, 200, meals=frozenset({"snack", "dinner"}))

    plan = optimise([OATS, jam], needs_of())

    assert {p.kind for p in plan.picks if p.barcode == "jam"} <= {"snack", "dinner"}
    assert grams_of(plan, "jam") == pytest.approx(200)


def test_a_whole_of_steps_that_are_not_ten_grams_is_all_there():
    muesli = whole("muesli", {"energy": 1500}, 375, step=5.0)

    plan = optimise([OATS, muesli], needs_of())

    assert grams_of(plan, "muesli") == pytest.approx(375)


def test_a_product_required_whole_is_in_the_day_though_the_day_has_no_need_of_it():
    # 300 g of this is 60,000 kJ, seven times the day's energy: the day is then the
    # closest it can be, and the oats that would have made the energy are not there.
    cake = whole("cake", {"energy": 20000}, 300)
    candidates = [OATS, cake]

    plan = optimise(candidates, needs_of())

    assert plan.status == "optimal"
    assert grams_of(plan, "cake") == pytest.approx(300)
    assert grams_of(plan, "oats") == 0


def test_a_product_required_whole_is_in_the_day_when_it_brings_nothing():
    plain = whole("plain", {}, 100)

    plan = optimise([OATS, plain], needs_of())

    assert grams_of(plan, "plain") == pytest.approx(100)


def test_a_product_required_whole_is_in_a_quick_look_at_the_foods_too():
    jam = whole("jam", {"energy": 1000}, 200)

    plan = optimise([OATS, jam], needs_of(), options=Options(whole_steps=False))

    assert "jam" in {pick.barcode for pick in plan.picks}


def test_a_product_that_is_not_required_whole_is_not():
    jam = product("jam", {"energy": 1000}, max_grams=200)

    plan = optimise([OATS, jam], needs_of())

    assert grams_of(plan, "jam") < jam.max_grams


# ----------------------------------------------------------------------------
# A day partly eaten
# ----------------------------------------------------------------------------
def eaten_in(*kinds: str, **amounts: float) -> Eaten:
    """Meals behind the user, and what they brought."""
    return Eaten(frozenset(kinds), amounts)


def test_what_the_meals_eaten_brought_counts_towards_the_needs():
    candidates = [OATS]
    eaten = eaten_in("breakfast", "lunch", energy=KJ * 0.6)

    plan = optimise(candidates, needs_of(), eaten=eaten)

    # 60 % of the day is eaten: the energy to add is the 40 % left.
    day = KJ * 0.6 + brought(plan, candidates, "energy")
    assert KJ * 0.95 <= day <= KJ * 1.05


def test_nothing_is_put_in_a_meal_that_is_eaten():
    plan = optimise(
        [OATS], needs_of(), eaten=eaten_in("breakfast", "lunch", energy=KJ * 0.6)
    )

    assert plan.picks
    assert {pick.kind for pick in plan.picks} <= {"snack", "dinner"}


def test_the_energy_left_is_shared_between_the_meals_that_are_left():
    candidates = [OATS]
    eaten = eaten_in("breakfast", "lunch", energy=KJ * 0.6)

    plan = optimise(candidates, needs_of(), eaten=eaten)

    # A snack is 10 and a dinner 30 of the 40 % left: a quarter and three quarters.
    left = KJ * 0.4
    snack = brought(plan, candidates, "energy", ("snack",))
    dinner = brought(plan, candidates, "energy", ("dinner",))
    assert left * 0.25 * 0.75 <= snack <= left * 0.25 * 1.25
    assert left * 0.75 * 0.75 <= dinner <= left * 0.75 * 1.25


def test_a_need_the_meals_eaten_meet_asks_for_nothing_more():
    candidates = [OATS, LENTILS]
    wanted = needs_of(need(("proteins",), low=60))

    asked = optimise(candidates, wanted)
    met = optimise(candidates, wanted, eaten=eaten_in(proteins=60.0))

    assert "lentils" in {pick.barcode for pick in asked.picks}
    assert {pick.barcode for pick in met.picks} == {"oats"}


def test_a_limit_counts_what_the_meals_eaten_brought():
    # 40 g of protein is all the day may have; 30 are eaten, and oats alone would
    # add the 25 g the day's energy makes of them: the day is as near as it can be.
    candidates = [OATS]
    wanted = needs_of(need(("proteins",), high=40))

    free = optimise(candidates, wanted)
    eaten = optimise(candidates, wanted, eaten=eaten_in(proteins=30.0))

    assert brought(free, candidates, "proteins") <= 40 + EPSILON
    # 10 g are left of the limit, and a cost is paid for the 15 g of excess it ends in.
    assert eaten.objective is not None
    assert free.objective is not None
    assert eaten.objective > free.objective


def test_the_users_ratio_counts_what_the_meals_eaten_brought():
    # Fish oil was eaten: 10 g of DHA and 5 g of EPA. For DHA over EPA at 1:1, the day
    # needs more EPA than DHA: the 50 g of algae oil there is, which has the EPA.
    candidates = [OATS, FISH, ALGAE]
    wanted = needs_of(need(("epa", "dha"), low=EPA_DHA_NEED), ratios=(dha_over_epa(),))

    plan = optimise(candidates, wanted, eaten=eaten_in(dha=10.0, epa=5.0))

    dha = 10.0 + brought(plan, candidates, "dha")
    epa = 5.0 + brought(plan, candidates, "epa")
    assert RATIO_LOW - 1e-4 <= dha / epa <= RATIO_HIGH + 1e-4
    assert grams_of(plan, "algae") > 0


def test_a_day_with_every_meal_eaten_has_nothing_to_add():
    plan = optimise([OATS], needs_of(), eaten=eaten_in(*KINDS, energy=KJ))

    assert plan.picks == []


def test_a_day_whose_energy_is_eaten_already_adds_none():
    # More than the day's energy is eaten, so the meals left share nothing.
    plan = optimise([OATS], needs_of(), eaten=eaten_in("breakfast", energy=KJ * 1.2))

    assert plan.status == "optimal"
    assert plan.picks == []


def test_no_meal_eaten_is_the_day_as_it_was():
    candidates = [OATS, LENTILS]
    wanted = needs_of(need(("proteins",), low=60))

    assert optimise(candidates, wanted, eaten=Eaten()) == optimise(candidates, wanted)
