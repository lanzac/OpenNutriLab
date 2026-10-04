"""
The percentages a label does not give, worked out from what it does say.

A label gives the order of the ingredients, a few percentages, and the nutrition
of the whole product. Nothing else is used. The unknown is the share of the
product that each ingredient, sub-ingredients included, makes up, and these are
the rules it has to follow:

- the ingredients at the top of the list add up to 100 %;
- the sub-ingredients of an ingredient add up to that ingredient;
- a declared percentage holds within its rounding (33 is 32.5 to 33.5, see
  rounding_margin). One written next to a sub-ingredient is a share of its
  parent, as "Dattes 7 % (dattes, farine de riz 2 %)" reads;
- the list is in descending order of weight (Regulation (EU) 1169/2011,
  article 18), so an ingredient never weighs more than the one before it in the
  same list. The regulation has exceptions that a text does not show, which can
  only make a result too narrow, and are reported when they make it impossible;
- the nutrition of the product, per 100 g, is what its ingredients add up to.
  For each nutrient on the label, the lowest the ingredients can make is below
  the label's upper end and the highest they can make is above its lower end.
  Each ingredient is itself an interval, and taking each nutrient on its own
  keeps the rules linear. So the intervals can be a little wider than the truth,
  never narrower.

Energy is left out of the last rule: a label computes it from the other
nutrients, so it says nothing more about the ingredients. Step 8 checks it.

The composition that counts for an ingredient is the one of the coarsest level
that has one in its branch: "raisins secs (raisins, huile de tournesol)" is
worked out from dried grapes, not from fresh ones and oil, whose water would
count for nothing but a quarter of the sugars. The sub-ingredients are used when
the ingredient has no composition of its own, and still get a percentage.

All of these are linear rules over the percentages, so what each percentage can
be is found exactly: its lowest and highest values among all the combinations
that follow the rules, one linear program for each (scipy, HiGHS). The point
value is the mean of those extreme combinations, which follows the rules as they
do, and a declared percentage keeps its own figure when it still holds.

When the rules cannot all hold, nothing is guessed:
- an ingredient with no composition leaves the nutrition unused, and says which;
- a label that the compositions cannot give leaves it unused, and says which
  nutrients are off. It is the label that is not trusted here and the composition
  that may be wrong, and the warning does not say which;
- declared percentages and order that contradict each other give no estimate.

The processing a food goes through is not modelled: the percentages are of the
ingredients as used, and the nutrition is of the food as sold, so a product that
loses water (baked, dried) is out of reach of the nutrition rule.
"""

import itertools
from collections import defaultdict
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from decimal import ROUND_CEILING
from decimal import ROUND_FLOOR
from decimal import ROUND_HALF_EVEN
from decimal import Decimal
from typing import NamedTuple

import numpy as np
from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _
from numpy.typing import NDArray
from scipy.optimize import linprog

from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.services.derived_nutrients import derived_nutrients
from opennutrilab.products.services.reference_composition import Estimate
from opennutrilab.products.services.reference_composition import reference_composition
from opennutrilab.products.services.reference_composition import rounding_margin

# The nutrients of a label that tell what the ingredients are. In parent first
# order: a nutrient a food lacks is at most the one it is part of.
NUTRIENTS = (
    "fat",
    "saturated_fat",
    "carbohydrates",
    "sugars",
    "fiber",
    "proteins",
    "salt",
)
# A food with none of these has no composition worth counting.
REQUIRED_NUTRIENTS = frozenset({"fat", "carbohydrates", "proteins"})

_HUNDRED = 100.0
# What the solver leaves of a rule that holds exactly.
_TOLERANCE = 1e-7
_DIGITS = Decimal("0.01")

Range = tuple[float, float]
Matrix = NDArray[np.float64]


class Interval(NamedTuple):
    """A share of the product, in percent. `point` is within `low` and `high`."""

    low: Decimal
    point: Decimal
    high: Decimal


class Problem(TextChoices):
    """What kept the estimate from using all there is. "%(detail)s" is what."""

    NO_COMPOSITION = (
        "no_composition",
        _(
            "The nutrition of the product was not used: no composition is known "
            "for %(detail)s."
        ),
    )
    NO_NUTRITION = (
        "no_nutrition",
        _("The nutrition of the product was not used: it declares none."),
    )
    LABEL_DISAGREES = (
        "label_disagrees",
        _(
            "The nutrition of the product was not used: the compositions of its "
            "ingredients cannot give it (%(detail)s)."
        ),
    )
    IMPOSSIBLE = (
        "impossible",
        _(
            "The declared percentages and the order of the ingredients "
            "contradict each other: nothing could be estimated."
        ),
    )


class EstimateWarning(NamedTuple):
    problem: Problem
    detail: str = ""

    def message(self) -> str:
        return str(self.problem.label) % {"detail": self.detail}


class PercentageEstimate(NamedTuple):
    # By ingredient id: its share of the whole product. Empty when impossible.
    percentages: dict[int, Interval]
    warnings: list[EstimateWarning]
    # Whether the nutrition of the product narrowed the percentages.
    used_nutrition: bool


class Node(NamedTuple):
    """One ingredient, siblings in the order the label lists them."""

    key: int
    parent: int | None
    name: str
    declared: Decimal | None = None
    # (low, high) per 100 g, for the nutrients in NUTRIENTS; None if it has none.
    composition: Mapping[str, Range] | None = None


Row = tuple[dict[int, float], float]


@dataclass
class _Problem:
    """Linear rules over the columns: `ub` rows are <=, `eq` rows are =."""

    width: int
    ub: list[Row] = field(default_factory=list)
    eq: list[Row] = field(default_factory=list)
    bounds: list[Range] = field(default_factory=list)

    def solve(self, objective: Matrix) -> Matrix | None:
        """The columns that minimise the objective, or None if no values follow
        the rules."""
        result = linprog(
            objective,
            A_ub=self._matrix(self.ub) if self.ub else None,
            b_ub=[bound for _, bound in self.ub] if self.ub else None,
            A_eq=self._matrix(self.eq) if self.eq else None,
            b_eq=[bound for _, bound in self.eq] if self.eq else None,
            bounds=self.bounds,
            method="highs",
        )
        if result.status == 2:  # noqa: PLR2004
            return None
        if result.status != 0:
            msg = f"The linear program failed: {result.message}"
            raise RuntimeError(msg)
        return np.asarray(result.x, dtype=np.float64)

    def _matrix(self, rows: Sequence[Row]) -> Matrix:
        matrix = np.zeros((len(rows), self.width))
        for r, (coefficients, _bound) in enumerate(rows):
            for column, value in coefficients.items():
                matrix[r, column] = value
        return matrix


def estimate_percentages(product: Product) -> PercentageEstimate:
    """What the label of a product says of the shares of its ingredients."""
    ingredients = list(product.ingredients.select_related("reference"))
    catalogue = {
        nutrient.code: nutrient
        for nutrient in Nutrient.objects.filter(code__in=NUTRIENTS)
    }
    derived = list(derived_nutrients())
    compositions = {
        reference.pk: _macronutrients(
            reference_composition(reference, derived), catalogue
        )
        for reference in {i.reference_id: i.reference for i in ingredients}.values()
    }
    nodes = [
        Node(
            key=i.id,
            parent=i.parent_id,
            name=i.reference.name,
            declared=i.percentage,
            composition=compositions[i.reference_id],
        )
        for i in ingredients
    ]
    label = {
        code: _declared_range(Decimal(amount))
        for code, amount in product.declared_nutrients.filter(
            nutrient__in=catalogue.values()
        ).values_list("nutrient_id", "amount")
    }
    return estimate(nodes, label, {c: n.name for c, n in catalogue.items()})


def estimate(
    nodes: Sequence[Node],
    label: Mapping[str, Range],
    nutrient_names: Mapping[str, str] | None = None,
) -> PercentageEstimate:
    """
    The share each node can be, from the rules in the module's description.

    `label` is the interval of each nutrient of the whole product, per 100 g.
    """
    if not nodes:
        return PercentageEstimate({}, [], used_nutrition=False)
    warnings: list[EstimateWarning] = []
    tree = _tree(nodes)
    units, without = _units(nodes)

    nutrition: _Problem | None = None
    if not label:
        warnings.append(EstimateWarning(Problem.NO_NUTRITION))
    elif without:
        names = ", ".join(nodes[i].name for i in without)
        warnings.append(EstimateWarning(Problem.NO_COMPOSITION, names))
    else:
        nutrition = _with_nutrition(tree, nodes, units, label)

    ranges = _ranges(nutrition) if nutrition is not None else None
    used_nutrition = ranges is not None
    if ranges is None:
        ranges = _ranges(tree)
        if ranges is None:
            warnings.append(EstimateWarning(Problem.IMPOSSIBLE))
            return PercentageEstimate({}, warnings, used_nutrition=False)
        if nutrition is not None:
            off = _disagreeing(tree, nodes, units, label)
            names = nutrient_names or {}
            detail = ", ".join(names.get(code, code) for code in off)
            warnings.append(EstimateWarning(Problem.LABEL_DISAGREES, detail))

    lows, highs, points = ranges
    percentages = {
        node.key: _interval(node.declared, lows[i], points[i], highs[i])
        for i, node in enumerate(nodes)
    }
    return PercentageEstimate(percentages, warnings, used_nutrition=used_nutrition)


def _declared_range(amount: Decimal) -> Range:
    margin = rounding_margin(amount)
    return float(max(Decimal(0), amount - margin)), float(amount + margin)


def _macronutrients(
    composition: Mapping[str, Estimate], catalogue: Mapping[str, Nutrient]
) -> dict[str, Range] | None:
    """
    The (low, high) of each nutrient in NUTRIENTS, or None for a composition that
    lacks the main ones.

    A nutrient it does not have is somewhere from nothing to the one it is part
    of (sugars are carbohydrates), or to the 100 g everything is given for.
    """
    if not composition.keys() >= REQUIRED_NUTRIENTS:
        return None
    ranges: dict[str, Range] = {}
    for code in NUTRIENTS:
        if (estimate_ := composition.get(code)) is not None:
            high = float(estimate_.high) if estimate_.high is not None else _HUNDRED
            ranges[code] = (float(estimate_.low or 0), high)
            continue
        parent = catalogue[code].parent_id if code in catalogue else None
        ranges[code] = (0.0, ranges[parent][1] if parent in ranges else _HUNDRED)
    return ranges


def _units(nodes: Sequence[Node]) -> tuple[list[int], list[int]]:
    """
    The indices of the nodes whose composition counts, which is the coarsest that
    has one in each branch, and of those that leave a branch without any.
    """
    children: defaultdict[int | None, list[int]] = defaultdict(list)
    for i, node in enumerate(nodes):
        children[node.parent].append(i)

    units: list[int] = []
    without: list[int] = []

    def visit(i: int) -> None:
        if nodes[i].composition is not None:
            units.append(i)
        elif subs := children[nodes[i].key]:
            for sub in subs:
                visit(sub)
        else:
            without.append(i)

    for root in children[None]:
        visit(root)
    return units, without


def _tree(nodes: Sequence[Node]) -> _Problem:
    """The rules a label's list of ingredients gives, and no more."""
    index = {node.key: i for i, node in enumerate(nodes)}
    problem = _Problem(len(nodes), bounds=[(0.0, _HUNDRED)] * len(nodes))
    siblings: defaultdict[int | None, list[int]] = defaultdict(list)
    for i, node in enumerate(nodes):
        siblings[node.parent].append(i)

    for i, node in enumerate(nodes):
        if node.declared is None:
            continue
        low, high = _declared_range(node.declared)
        if node.parent is None:
            problem.bounds[i] = (low, min(high, _HUNDRED))
        else:
            # A share of its parent: low% of it at least, high% of it at most.
            parent = index[node.parent]
            problem.ub.append(({i: 1.0, parent: -min(high, _HUNDRED) / 100}, 0.0))
            problem.ub.append(({parent: low / 100, i: -1.0}, 0.0))

    roots = siblings[None]
    # A label that declares every ingredient need not add up to 100: 99.4 is
    # rounding, not an error.
    if any(nodes[i].declared is None for i in roots):
        problem.eq.append((dict.fromkeys(roots, 1.0), _HUNDRED))
    for parent_key, group in siblings.items():
        if parent_key is not None:
            problem.eq.append(
                ({**dict.fromkeys(group, 1.0), index[parent_key]: -1.0}, 0.0)
            )
        problem.ub.extend(
            ({after: 1.0, before: -1.0}, 0.0)
            for before, after in itertools.pairwise(group)
        )
    return problem


def _with_nutrition(
    tree: _Problem,
    nodes: Sequence[Node],
    units: Sequence[int],
    label: Mapping[str, Range],
    *,
    slack: bool = False,
) -> _Problem:
    """
    The tree's rules and those of the nutrition. With `slack`, each nutrient has a
    column that lets it be missed, by that many times the label's rounding.
    """
    width = tree.width + (len(label) if slack else 0)
    problem = _Problem(
        width,
        ub=list(tree.ub),
        eq=list(tree.eq),
        bounds=[*tree.bounds, *[(0.0, np.inf)] * (width - tree.width)],
    )
    for k, (code, (low, high)) in enumerate(label.items()):
        lows: dict[int, float] = {}
        highs: dict[int, float] = {}
        for i in units:
            composition = nodes[i].composition or {}
            least, most = composition.get(code, (0.0, _HUNDRED))
            lows[i] = least / 100
            highs[i] = -most / 100
        if slack:
            scale = max((high - low) / 2, _TOLERANCE)
            lows[tree.width + k] = -scale
            highs[tree.width + k] = -scale
        problem.ub.append((lows, high))
        problem.ub.append((highs, -low))
    return problem


def _ranges(problem: _Problem) -> tuple[Matrix, Matrix, Matrix] | None:
    """
    The lowest and highest value of each of the first columns, and the mean of
    those extreme combinations; None if no values follow the rules.
    """
    count = len(problem.bounds)
    lows = np.zeros(count)
    highs = np.zeros(count)
    vertices: list[Matrix] = []
    for i in range(count):
        for sign in (1.0, -1.0):
            objective = np.zeros(count)
            objective[i] = sign
            found = problem.solve(objective)
            if found is None:
                return None
            vertices.append(found)
            (lows if sign > 0 else highs)[i] = found[i]
    return lows, highs, np.mean(vertices, axis=0)


def _disagreeing(
    tree: _Problem,
    nodes: Sequence[Node],
    units: Sequence[int],
    label: Mapping[str, Range],
) -> list[str]:
    """The nutrients that have to be missed for the rest to hold, the least."""
    problem = _with_nutrition(tree, nodes, units, label, slack=True)
    objective = np.zeros(problem.width)
    objective[tree.width :] = 1.0
    found = problem.solve(objective)
    if found is None:  # Not possible: the slack can relax every nutrient rule.
        return []
    return [code for k, code in enumerate(label) if found[tree.width + k] > _TOLERANCE]


def _interval(
    declared: Decimal | None, low: float, point: float, high: float
) -> Interval:
    """Rounded outwards, since the solver is exact only to its tolerance."""
    lowest = _decimal(low).quantize(_DIGITS, ROUND_FLOOR)
    highest = _decimal(high).quantize(_DIGITS, ROUND_CEILING)
    if declared is not None and lowest <= declared <= highest:
        return Interval(lowest, declared, highest)
    middle = _decimal(point).quantize(_DIGITS, ROUND_HALF_EVEN)
    return Interval(lowest, min(max(middle, lowest), highest), highest)


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))
