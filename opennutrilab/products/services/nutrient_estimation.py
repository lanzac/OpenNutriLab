"""
The nutrients of a product, worked out from the shares of its ingredients.

A nutrient of the product, per 100 g, is what its ingredients bring: the share
of each, in percent, times its content of the nutrient per 100 g, over 100.
Both are intervals, and so is the result. It is not found by multiplying the
ends: the shares are bound to each other (they add up, they are in order, the
label's nutrition holds), and the lowest and the highest the nutrient can be are
found over the combinations that follow the rules of percentage_estimation, one
linear program for each (the lowest content of each ingredient over the
combinations, and the highest). That is as tight as the rules allow.

The point value is the one of the combination percentage_estimation takes as its
point, with each ingredient's own amount, so it lies within the interval.

As in the percentages, the composition that counts in a branch is the coarsest
that has one, so a parent and its sub-ingredients are never counted together.

A food does not give a value for every nutrient (CIQUAL has its holes, and the
foods added by hand have the nutrition of a label and nothing else), and a
nutrient missing from an ingredient is not zero. So each nutrient has its
coverage: the share of the product, in percent, whose ingredients give a value.
When it is not the whole product, the amount and the lowest figure count the
rest as nothing, which makes them what is at least there, and the highest figure
is not known: there is none. There is one when an ingredient that lacks the
nutrient gives the one it is part of (no sugars, but carbohydrates: at most
those). A value of "traces" has no upper end either.
"""

from collections.abc import Mapping
from collections.abc import Sequence
from decimal import ROUND_CEILING
from decimal import ROUND_FLOOR
from decimal import ROUND_HALF_EVEN
from decimal import Decimal
from typing import NamedTuple

import numpy as np

from opennutrilab.products.models import Product
from opennutrilab.products.services.percentage_estimation import Interval
from opennutrilab.products.services.percentage_estimation import Matrix
from opennutrilab.products.services.percentage_estimation import PercentageEstimate
from opennutrilab.products.services.percentage_estimation import Solution
from opennutrilab.products.services.percentage_estimation import interval
from opennutrilab.products.services.percentage_estimation import load
from opennutrilab.products.services.percentage_estimation import percentages_of
from opennutrilab.products.services.percentage_estimation import solve_shares
from opennutrilab.products.services.reference_composition import Estimate

# What a nutrient is given with, as the foods' own values are.
_DIGITS = Decimal(1).scaleb(-6)


class NutrientAmount(NamedTuple):
    """One nutrient of a product, per 100 g, in the nutrient's unit."""

    amount: Decimal
    low: Decimal
    # None when the product's whole mass has no value, or when one gives traces.
    high: Decimal | None
    # The share of the product, in percent, whose ingredients give a value.
    coverage: Interval


class NutrientsEstimate(NamedTuple):
    # By nutrient code. Empty when the shares are impossible or nothing has a
    # composition.
    nutrients: dict[str, NutrientAmount]
    # What they are worked out from, and what is to say of it.
    percentages: PercentageEstimate


def estimate_nutrients(product: Product) -> NutrientsEstimate:
    """The nutrients of a product, as intervals, from its ingredients."""
    loaded = load(product)
    solution = solve_shares(loaded.nodes, loaded.label, loaded.nutrient_names)
    return NutrientsEstimate(
        nutrients_of(solution, loaded.compositions, loaded.parents),
        percentages_of(solution),
    )


def nutrients_of(
    solution: Solution,
    compositions: Sequence[Mapping[str, Estimate]],
    parents: Mapping[str, str | None] | None = None,
) -> dict[str, NutrientAmount]:
    """
    The nutrients the shares of a solution give, from the whole composition of
    each node (parallel to the solution's nodes). `parents` gives, by code, the
    nutrient each is part of.
    """
    if solution.rules is None or solution.ranges is None or not solution.units:
        return {}
    units = solution.units
    codes = sorted({code for i in units for code in compositions[i]})
    coverages: dict[frozenset[int], Interval] = {}
    nutrients: dict[str, NutrientAmount] = {}
    for code in codes:
        having = [i for i in units if code in compositions[i]]
        covered = frozenset(having)
        if covered not in coverages:
            coverages[covered] = _coverage(solution, covered)
        # What bounds the nutrient in an ingredient that lacks it: the nutrient it
        # is part of, if it gives that.
        parent = (parents or {}).get(code)
        lacking = {
            i: compositions[i][parent]
            for i in units
            if i not in covered and parent is not None and parent in compositions[i]
        }
        nutrients[code] = _amount(
            solution,
            {i: compositions[i][code] for i in having},
            lacking,
            coverages[covered],
            closed=not solution.without
            and all(i in covered or i in lacking for i in units),
        )
    return nutrients


def _amount(
    solution: Solution,
    contents: Mapping[int, Estimate],
    lacking: Mapping[int, Estimate],
    coverage: Interval,
    *,
    closed: bool,
) -> NutrientAmount:
    """
    One nutrient, from the content of each ingredient that has a value. `lacking`
    is, for the others, the nutrient this one is part of, which is at most that.
    `closed` is whether every ingredient gives a value or a bound.
    """
    assert solution.rules is not None
    assert solution.ranges is not None
    _lows, _highs, mean = solution.ranges
    width = solution.rules.width

    least = np.zeros(width)
    most = np.zeros(width)
    point = 0.0
    bounded = closed
    for i, parent in lacking.items():
        if parent.high is None:
            bounded = False
        else:
            most[i] = float(parent.high) / 100
    for i, content in contents.items():
        least[i] = float(content.low or 0) / 100
        if content.high is None:
            bounded = False
        else:
            most[i] = float(content.high) / 100
        point += mean[i] * float(content.amount or 0) / 100

    low = _extreme(solution, least)
    high = -_extreme(solution, -most) if bounded else None
    amount = min(max(point, low), high if high is not None else point)
    return NutrientAmount(
        amount=_round(amount, ROUND_HALF_EVEN),
        low=_round(min(low, amount), ROUND_FLOOR),
        high=None if high is None else _round(max(high, amount), ROUND_CEILING),
        coverage=coverage,
    )


def _extreme(solution: Solution, objective: Matrix) -> float:
    """The lowest the objective gets over the combinations that follow the rules."""
    assert solution.rules is not None
    found = solution.rules.solve(objective)
    # The rules held when the shares were solved, and nothing has changed since.
    assert found is not None
    return float(objective @ found)


def _coverage(solution: Solution, covered: frozenset[int]) -> Interval:
    """The share of the product, in percent, that the covered nodes make up."""
    assert solution.rules is not None
    assert solution.ranges is not None
    _lows, _highs, mean = solution.ranges
    indicator = np.zeros(solution.rules.width)
    indicator[list(covered)] = 1.0
    return interval(
        None,
        _extreme(solution, indicator),
        float(indicator @ mean),
        -_extreme(solution, -indicator),
    )


def _round(value: float, rounding: str) -> Decimal:
    """Rounded as asked, after the solver's noise, which is far below the digits."""
    return Decimal(str(round(value, 9))).quantize(_DIGITS, rounding)
