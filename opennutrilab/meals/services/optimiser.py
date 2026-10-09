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

And a small cost for each product used and for each product in each meal, so that a
day is not made of twenty products or of the same one in four places. The price of
each is a few hundredths of a missed need.

The products are those of the inventory, so the day is as good as they allow: where
the inventory cannot meet a target the plan says how far it is, and the suggestions
(a later step) say what could.
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
        upper: float = math.inf,
        cost: float = 0.0,
        integer: bool = False,
    ) -> int:
        self.lower.append(0.0)
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
    split: Mapping[str, float] = DEFAULT_SPLIT,
    time_limit: float = 20.0,
) -> Plan:
    """The best day from some candidates, for some needs. See the module."""
    day = _Day(candidates, weights)
    day.add_needs(needs)
    day.add_split(needs, split)
    day.add_ratios(needs)
    status, values, objective = day.model.solve(time_limit, MIP_GAP)
    if values is None:
        return Plan("failed", None, [])
    return Plan(status, objective, day.picks(values))


class _Day:
    """The programme of a day: what is decided, and what it is held to."""

    def __init__(self, candidates: Iterable[Candidate], weights: Weights) -> None:
        self.weights = weights
        self.model = _Model()
        self.usable = [c for c in candidates if c.max_grams >= c.step_grams > 0]
        # The number of steps of a product in a meal, by (product, meal).
        self.steps: dict[tuple[int, str], int] = {}
        for number, candidate in enumerate(self.usable):
            self._add_product(number, candidate)

    def _add_product(self, number: int, candidate: Candidate) -> None:
        """A whole number of steps of a product in each meal it may be in."""
        model, weights = self.model, self.weights
        most = math.floor(candidate.max_grams / candidate.step_grams + 1e-9)
        in_meals: list[int] = []
        for kind in KINDS:
            if kind not in candidate.meals:
                continue
            x = model.var(upper=most, integer=True)
            there = model.var(upper=1, cost=weights.pair, integer=True)
            model.row({x: 1, there: -most}, high=0)
            self.steps[number, kind] = x
            in_meals.append(there)
        if not in_meals:
            return
        used = model.var(upper=1, cost=weights.food, integer=True)
        model.row({**dict.fromkeys(in_meals, 1.0), used: -len(in_meals)}, high=0)
        # The most of it in a day.
        in_day = {x: 1.0 for (n, _kind), x in self.steps.items() if n == number}
        model.row(in_day, high=most)

    def terms(
        self, by_nutrient: Mapping[str, Weight], kinds: Iterable[str] = KINDS
    ) -> dict[int, float]:
        """What a combination of nutrients is, over the steps of the given meals."""
        found: dict[int, float] = defaultdict(float)
        for kind in kinds:
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

    def at_least(
        self, expression: Mapping[int, float], bound: float, weight: float
    ) -> None:
        """expression >= bound, a shortfall costing its share of the bound."""
        shortfall = self.model.var(cost=weight)
        scaled = {x: v / bound for x, v in expression.items()}
        self.model.row({**scaled, shortfall: 1.0}, low=1.0)

    def at_most(
        self, expression: Mapping[int, float], bound: float, weight: float
    ) -> None:
        """expression <= bound, an excess costing its share of the bound."""
        excess = self.model.var(cost=weight)
        scaled = {x: v / bound for x, v in expression.items()}
        self.model.row({**scaled, excess: -1.0}, high=1.0)

    def add_needs(self, needs: Needs) -> None:
        """Both ends of every need."""
        for need in needs.nutrients:
            expression = self.terms(dict.fromkeys(need.nutrients, 1.0))
            is_energy = need.nutrients == ("energy",)
            weight = self.weights.energy if is_energy else self.weights.need
            if need.low is not None and need.low > 0:
                self.at_least(expression, float(need.low), weight)
            if need.high is not None and need.high > 0:
                self.at_most(expression, float(need.high), weight)

    def add_split(self, needs: Needs, split: Mapping[str, float]) -> None:
        """The energy of each meal, near its share of the day's."""
        energy = float(needs.energy * KJ_PER_KCAL)
        for kind in KINDS:
            middle = split[kind] * energy
            meal = self.terms({"energy": 1.0}, [kind])
            self.at_least(meal, middle * (1 - SPLIT_MARGIN), self.weights.split)
            self.at_most(meal, middle * (1 + SPLIT_MARGIN), self.weights.split)

    def add_ratios(self, needs: Needs) -> None:
        """Each ratio within its ends, a violation taken over its denominator."""
        for ratio in needs.ratios:
            numerator = self.terms(ratio.numerator)
            denominator = self.terms(ratio.denominator)
            scale = _reference(ratio.denominator, needs) or 1.0
            weight = (
                self.weights.target if ratio.kind == Kind.TARGET else self.weights.ratio
            )
            if ratio.high is not None:
                row = _difference(numerator, denominator, float(ratio.high), scale)
                self.model.row({**row, self.model.var(cost=weight): -1.0}, high=0.0)
            if ratio.low is not None:
                row = _difference(numerator, denominator, float(ratio.low), scale)
                self.model.row({**row, self.model.var(cost=weight): 1.0}, low=0.0)

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


def _reference(terms: Mapping[str, Weight], needs: Needs) -> float:
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
