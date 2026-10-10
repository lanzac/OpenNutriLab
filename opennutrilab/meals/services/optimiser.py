"""
The best day from some products: which of them, in which meal, and how much.

It is a mixed-integer linear programme, solved by HiGHS through scipy. For each
product and each meal it may be in there is a whole number of steps, a step being
half a serving of a product that has one and 10 g of one that has not, and the day
is what these add up to, at the amounts the products' compositions give (the points
of their estimates, or what their labels declare: services.stored_estimates).

**Every target is soft**, so that there is always an answer, the closest day, and
what it misses is what the day report shows. A lower end of a need is met by
`amount / low + shortfall >= 1`, an upper end by `amount / high - excess <= 1`, and
each shortfall or excess costs its weight: a cost is the share of the need that is
missed, whatever the nutrient's unit, so a day that misses 10 % of a vitamin costs
a tenth of one that has none of it. The targets are:

- the needs: every lower and upper end of services.needs, among them the energy,
  held by a weight that outweighs the rest (a day of 1,000 kcal that meets every
  vitamin is not a day);
- the energy of each meal, near its share of the day's (25, 35, 10 and 30 %), with
  a margin of 25 %;
- the ratios: ANSES' (linoleic over alpha-linolenic acid at most 5, sodium over
  potassium in moles at most 1) and the user's own (DHA over EPA, omega-3 over
  omega-6, each within its tolerance), which weigh more. A ratio is linear:
  `numerator - high * denominator <= 0`, and its violation is taken over what the
  denominator is at the need, so that it costs the same whatever the nutrient's unit.

A candidate can be **required whole**: all of a quantity in the day (the package of a
product the user would have used up), shared between the meals it may be in as the
optimiser sees fit. It is the one thing a day is held to, not a target: the other
targets are then the closest that is left, which may be far from them.

And a small cost for each product used and for each product in each meal, so that a
day is not made of twenty products or of the same one in four places. The price of
each is a few hundredths of a missed need.

A candidate can be **new**: a food that is not in the inventory, which a suggestion
(services.suggestions) would have the user get. It costs more (`Weights.new`, on top)
and a day may use at most `Options.max_new` of them, so that only the few that close
the most of what the inventory misses are worth it.

A day may already be **partly eaten**: some of its meals are behind the user. What they
brought is a constant in every target (a need of 100 is met by 60 eaten and 40 to
add), nothing is put in those meals, and the meals that are left share what the day's
energy still lacks, in the proportions of the split. The plan is then what to add.

The products are those of the inventory, so the day is as good as they allow: where
the inventory cannot meet a target the plan says how far it is, and the suggestions
say what could.
"""

import math
from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Mapping
from decimal import Decimal
from typing import NamedTuple

import numpy as np
from scipy.optimize import Bounds
from scipy.optimize import LinearConstraint
from scipy.optimize import milp
from scipy.sparse import coo_array

from opennutrilab.meals.models import Meal
from opennutrilab.meals.services.energy import KJ_PER_KCAL
from opennutrilab.meals.services.needs import Kind
from opennutrilab.meals.services.needs import Needs
from opennutrilab.products.services.derived_nutrients import SUMS

KINDS: tuple[str, ...] = tuple(Meal.Kind.values)
# The weight of a nutrient in a combination: the needs give them as decimals.
Weight = float | Decimal
# How the energy of a day is shared between its meals.
DEFAULT_SPLIT: dict[str, float] = {
    "breakfast": 0.25,
    "lunch": 0.35,
    "snack": 0.10,
    "dinner": 0.30,
}
# How far the energy of a meal may be from its share before it costs anything.
SPLIT_MARGIN = 0.25
# How far from the best the solver may stop at, as a share of the cost.
MIP_GAP = 0.005


class Weights(NamedTuple):
    """What each kind of miss costs, per unit of the share of the need missed."""

    energy: float = 10.0
    split: float = 1.0
    need: float = 1.0
    # ANSES' ratios, and the user's own.
    ratio: float = 1.0
    target: float = 3.0
    # A product used in the day, and a product in a meal.
    food: float = 0.03
    pair: float = 0.01
    # A food that is not in the inventory, which a suggestion would have the user
    # get: on top of `food`, so that it is only worth it for a gain of this share of
    # a need or more.
    new: float = 0.15


class Options(NamedTuple):
    """How a day is looked for, apart from what it is held to."""

    # How the energy of a day is shared between its meals.
    split: Mapping[str, float] = DEFAULT_SPLIT
    # Seconds the solver is given.
    time_limit: float = 20.0
    # The most foods that are not in the inventory a day may use; None, any number.
    max_new: int | None = None
    # Whether the products of the inventory are counted in whole steps. Without, they
    # are in any quantity, and a new food is only asked whether it is in the day, in
    # no meal in particular: not a day to eat, but a much quicker way to see which
    # new foods are worth having in it.
    whole_steps: bool = True
    # How far from the best the solver may stop at, as a share of the cost.
    gap: float = MIP_GAP


class Candidate(NamedTuple):
    """A product the day may be made of."""

    barcode: str
    name: str
    # Amounts per 100 g by nutrient code, in the catalogue's units.
    per_100g: Mapping[str, float]
    # What a step is: this many grams, which is this much of the unit it is
    # counted in ("serving" or "g").
    step_grams: float
    step_quantity: float
    unit: str
    # The most of it a day, in grams.
    max_grams: float
    # The meals it may be in.
    meals: frozenset[str]
    # Not a product of the inventory: a food a suggestion would have the user get.
    new: bool = False
    # All of it, this many grams, is in the day: a whole number of steps, which is
    # for the caller to make this a multiple of. None, as much as is best.
    required_grams: float | None = None


class Eaten(NamedTuple):
    """What a day holds already: the meals behind the user, and what they brought."""

    # The meals that are eaten (Meal.Kind), in which nothing more is put.
    kinds: frozenset[str] = frozenset()
    # What they brought, by nutrient code, in the catalogue's units.
    amounts: Mapping[str, float] = {}


NOTHING_EATEN = Eaten()


class Pick(NamedTuple):
    """Some of a candidate in a meal."""

    barcode: str
    kind: str
    steps: int
    grams: float
    quantity: float
    unit: str


class Plan(NamedTuple):
    # "optimal", "time_limit" (the best found when the time was up), or "failed".
    status: str
    # The cost: what the day misses, weighed, and the small costs of its products.
    objective: float | None
    picks: list[Pick]


class _Model:
    """Variables and rows of a mixed-integer programme, minimised by HiGHS."""

    def __init__(self) -> None:
        self.lower: list[float] = []
        self.upper: list[float] = []
        self.cost: list[float] = []
        self.integer: list[int] = []
        self.rows: list[tuple[Mapping[int, float], float, float]] = []

    def var(
        self,
        *,
        lower: float = 0.0,
        upper: float = math.inf,
        cost: float = 0.0,
        integer: bool = False,
    ) -> int:
        self.lower.append(lower)
        self.upper.append(upper)
        self.cost.append(cost)
        self.integer.append(int(integer))
        return len(self.cost) - 1

    def row(
        self, terms: Mapping[int, float], low: float = -math.inf, high: float = math.inf
    ) -> None:
        self.rows.append((terms, low, high))

    def solve(
        self, time_limit: float, gap: float
    ) -> tuple[str, np.ndarray | None, float | None]:
        """The status, the values of the variables and the cost, when there are."""
        size = len(self.cost)
        if not self.rows:
            return "failed", None, None
        rows, columns, data = [], [], []
        for number, (terms, _low, _high) in enumerate(self.rows):
            for column, coefficient in terms.items():
                rows.append(number)
                columns.append(column)
                data.append(coefficient)
        matrix = coo_array(
            (data, (rows, columns)), shape=(len(self.rows), size)
        ).tocsr()
        found = milp(
            c=np.array(self.cost),
            integrality=np.array(self.integer),
            bounds=Bounds(np.array(self.lower), np.array(self.upper)),
            constraints=LinearConstraint(
                matrix,
                np.array([low for _t, low, _h in self.rows]),
                np.array([high for _t, _l, high in self.rows]),
            ),
            options={"time_limit": time_limit, "mip_rel_gap": gap},
        )
        if found.x is None:
            return "failed", None, None
        return ("optimal" if found.status == 0 else "time_limit"), found.x, found.fun


def optimise(
    candidates: Iterable[Candidate],
    needs: Needs,
    *,
    weights: Weights = Weights(),  # noqa: B008
    options: Options = Options(),  # noqa: B008
    eaten: Eaten = NOTHING_EATEN,
) -> Plan:
    """The best day from some candidates, for some needs. See the module."""
    day = _Day(candidates, weights, options, eaten)
    day.add_needs(needs)
    day.add_split(needs, options.split)
    day.add_ratios(needs)
    status, values, objective = day.model.solve(options.time_limit, options.gap)
    if values is None:
        return Plan("failed", None, [])
    return Plan(status, objective, day.picks(values))


class _Day:
    """The programme of a day: what is decided, and what it is held to."""

    def __init__(
        self,
        candidates: Iterable[Candidate],
        weights: Weights,
        options: Options,
        eaten: Eaten,
    ) -> None:
        self.weights = weights
        self.options = options
        self.eaten = eaten
        # The meals something can be put in.
        self.kinds = tuple(kind for kind in KINDS if kind not in eaten.kinds)
        self.model = _Model()
        self.usable = [c for c in candidates if c.max_grams >= c.step_grams > 0]
        # The number of steps of a product in a meal, by (product, meal).
        self.steps: dict[tuple[int, str], int] = {}
        # Whether each new food is used in the day.
        self.new_used: list[int] = []
        for number, candidate in enumerate(self.usable):
            self._add_product(number, candidate)
        if options.max_new is not None and self.new_used:
            self.model.row(dict.fromkeys(self.new_used, 1.0), high=options.max_new)

    def _add_loose(self, number: int, candidate: Candidate) -> None:
        """
        A product in any quantity in each meal it may be in, and whether it is in the
        day at all, which is all that is asked of a new food (a whole number only for
        those): what a quick look needs, with no choice of a meal for each.
        """
        model, weights = self.model, self.weights
        most = candidate.max_grams / candidate.step_grams
        needed = _steps_required(candidate)
        in_meals = [
            (kind, model.var(upper=most))
            for kind in self.kinds
            if kind in candidate.meals
        ]
        if not in_meals:
            return
        cost = weights.food + (weights.new if candidate.new else 0.0)
        used = model.var(
            lower=0 if needed is None else 1,
            upper=1,
            cost=cost,
            integer=candidate.new,
        )
        if candidate.new:
            self.new_used.append(used)
        model.row({**{x: 1.0 for _kind, x in in_meals}, used: -most}, high=0)
        if needed is not None:
            model.row({x: 1.0 for _kind, x in in_meals}, low=needed, high=needed)
        for kind, x in in_meals:
            self.steps[number, kind] = x

    def _add_product(self, number: int, candidate: Candidate) -> None:
        """A whole number of steps of a product in each meal it may be in."""
        if not self.options.whole_steps:
            self._add_loose(number, candidate)
            return
        model, weights = self.model, self.weights
        most = math.floor(candidate.max_grams / candidate.step_grams + 1e-9)
        needed = _steps_required(candidate)
        in_meals: list[int] = []
        for kind in self.kinds:
            if kind not in candidate.meals:
                continue
            # A new food is an order of magnitude, not a count of steps: its quantity
            # is a number (the page rounds it), which a solver finds far faster.
            x = model.var(upper=most, integer=not candidate.new)
            there = model.var(upper=1, cost=weights.pair, integer=True)
            model.row({x: 1, there: -most}, high=0)
            self.steps[number, kind] = x
            in_meals.append(there)
        if not in_meals:
            return
        cost = weights.food + (weights.new if candidate.new else 0.0)
        used = model.var(
            lower=0 if needed is None else 1, upper=1, cost=cost, integer=True
        )
        if candidate.new:
            self.new_used.append(used)
            # In one meal: it is to be got and eaten, not spread.
            model.row({**dict.fromkeys(in_meals, 1.0), used: -1.0}, high=0)
        else:
            model.row({**dict.fromkeys(in_meals, 1.0), used: -len(in_meals)}, high=0)
        # The most of it in a day, which is all of it where it is required whole.
        in_day = {x: 1.0 for (n, _kind), x in self.steps.items() if n == number}
        if needed is None:
            model.row(in_day, high=most)
        else:
            model.row(in_day, low=needed, high=needed)

    def terms(
        self, by_nutrient: Mapping[str, Weight], kinds: Iterable[str] | None = None
    ) -> dict[int, float]:
        """What a combination of nutrients is, over the steps of the given meals."""
        found: dict[int, float] = defaultdict(float)
        for kind in self.kinds if kinds is None else kinds:
            for number, candidate in enumerate(self.usable):
                x = self.steps.get((number, kind))
                if x is None:
                    continue
                per_gram = sum(
                    float(weight) * candidate.per_100g.get(code, 0.0)
                    for code, weight in by_nutrient.items()
                )
                if per_gram:
                    found[x] += candidate.step_grams / 100 * per_gram
        return found

    def brought(self, by_nutrient: Mapping[str, Weight]) -> float:
        """What the meals eaten brought of a combination of nutrients."""
        return sum(
            float(weight) * self.eaten.amounts.get(code, 0.0)
            for code, weight in by_nutrient.items()
        )

    def at_least(
        self,
        expression: Mapping[int, float],
        bound: float,
        weight: float,
        brought: float = 0.0,
    ) -> None:
        """
        brought + expression >= bound, a shortfall costing its share of the bound.
        `brought` is what is there already, which the expression adds to.
        """
        shortfall = self.model.var(cost=weight)
        scaled = {x: v / bound for x, v in expression.items()}
        self.model.row({**scaled, shortfall: 1.0}, low=1.0 - brought / bound)

    def at_most(
        self,
        expression: Mapping[int, float],
        bound: float,
        weight: float,
        brought: float = 0.0,
    ) -> None:
        """
        brought + expression <= bound, an excess costing its share of the bound.
        """
        excess = self.model.var(cost=weight)
        scaled = {x: v / bound for x, v in expression.items()}
        self.model.row({**scaled, excess: -1.0}, high=1.0 - brought / bound)

    def add_needs(self, needs: Needs) -> None:
        """Both ends of every need."""
        for need in needs.nutrients:
            by_nutrient = dict.fromkeys(need.nutrients, 1.0)
            expression = self.terms(by_nutrient)
            brought = self.brought(by_nutrient)
            is_energy = need.nutrients == ("energy",)
            weight = self.weights.energy if is_energy else self.weights.need
            if need.low is not None and need.low > 0:
                self.at_least(expression, float(need.low), weight, brought)
            if need.high is not None and need.high > 0:
                self.at_most(expression, float(need.high), weight, brought)

    def add_split(self, needs: Needs, split: Mapping[str, float]) -> None:
        """
        The energy of each meal that is not eaten, near its share of the day's. With
        meals eaten, the energy the day still lacks is shared between the others, in the
        proportions of the split; with none left to give, or none to share, nothing
        is asked of the meals.
        """
        left = float(needs.energy * KJ_PER_KCAL) - self.eaten.amounts.get("energy", 0.0)
        shares = sum(split[kind] for kind in self.kinds)
        if left <= 0 or shares <= 0:
            return
        for kind in self.kinds:
            middle = split[kind] / shares * left
            meal = self.terms({"energy": 1.0}, [kind])
            self.at_least(meal, middle * (1 - SPLIT_MARGIN), self.weights.split)
            self.at_most(meal, middle * (1 + SPLIT_MARGIN), self.weights.split)

    def add_ratios(self, needs: Needs) -> None:
        """Each ratio within its ends, a violation taken over its denominator."""
        for ratio in needs.ratios:
            numerator = self.terms(ratio.numerator)
            denominator = self.terms(ratio.denominator)
            scale = reference_amount(ratio.denominator, needs) or 1.0
            weight = (
                self.weights.target if ratio.kind == Kind.TARGET else self.weights.ratio
            )
            # What the meals eaten bring, taken the same way as the rest of the row.
            top, bottom = self.brought(ratio.numerator), self.brought(ratio.denominator)
            if ratio.high is not None:
                row = _difference(numerator, denominator, float(ratio.high), scale)
                brought = (top - float(ratio.high) * bottom) / scale
                self.model.row(
                    {**row, self.model.var(cost=weight): -1.0}, high=-brought
                )
            if ratio.low is not None:
                row = _difference(numerator, denominator, float(ratio.low), scale)
                brought = (top - float(ratio.low) * bottom) / scale
                self.model.row({**row, self.model.var(cost=weight): 1.0}, low=-brought)

    def picks(self, values: np.ndarray) -> list[Pick]:
        """The steps that were chosen, in the order of the day."""
        found: list[Pick] = []
        for (number, kind), x in self.steps.items():
            count = round(values[x])
            if count <= 0:
                continue
            candidate = self.usable[number]
            found.append(
                Pick(
                    barcode=candidate.barcode,
                    kind=kind,
                    steps=count,
                    grams=count * candidate.step_grams,
                    quantity=count * candidate.step_quantity,
                    unit=candidate.unit,
                )
            )
        return sorted(found, key=lambda p: (KINDS.index(p.kind), p.barcode))


def _steps_required(candidate: Candidate) -> int | None:
    """How many steps of a candidate the day must have, where it is required whole."""
    if candidate.required_grams is None:
        return None
    return round(candidate.required_grams / candidate.step_grams)


def _difference(
    numerator: Mapping[int, float],
    denominator: Mapping[int, float],
    ratio: float,
    scale: float,
) -> dict[int, float]:
    """(numerator - ratio x denominator) / scale, as the terms of a row."""
    found: dict[int, float] = defaultdict(float)
    for x, value in numerator.items():
        found[x] += value / scale
    for x, value in denominator.items():
        found[x] -= ratio * value / scale
    return dict(found)


def reference_amount(terms: Mapping[str, Weight], needs: Needs) -> float:
    """
    What a ratio's denominator is at the needs, which a violation of the ratio is
    taken over: the lower end of the need of each nutrient in it (see _need_of).
    """
    return sum(float(weight) * _need_of(code, needs) for code, weight in terms.items())


def _need_of(code: str, needs: Needs) -> float:
    """
    The lower end of a nutrient's need. Where it has none of its own: its share of
    the need of a sum that holds it (EPA is half of EPA + DHA), or the sum of its
    parts' (omega-6 is linoleic and arachidonic acid).
    """
    for need in needs.nutrients:
        if need.nutrients == (code,) and need.low:
            return float(need.low)
    for need in needs.nutrients:
        if code in need.nutrients and need.low:
            return float(need.low) / len(need.nutrients)
    return sum(_need_of(part, needs) for part in SUMS.get(code, ()))
