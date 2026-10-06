"""
The composition of a reference ingredient, worked out from the foods it draws on.

A reference draws on any number of source foods (CIQUAL's "Carotte, crue", and
later other tables'), and its composition is what they say together: more foods
make it more complete and more reliable. Every figure is an interval, as
everything estimated here is, and carries what it is made of.

For each nutrient of a food:
- a measured amount is an interval: the range the source's own data gives (its
  minimum and maximum), or else the amount's own rounding, half of the last digit
  it is written with (9.3 is 9.25 to 9.35). A measured zero has no margin;
- "below the detection limit x" is somewhere from 0 to x, and counts as x / 2;
- "traces" is there, and not quantified: from 0, with no upper end known;
- "not measured" says nothing, and the nutrient is not in the composition.
A nutrient the food lacks and that can be worked out from others it has (see
derived_nutrients) is derived for that food first, from the amounts, and from the
low and the high ends, so that its interval follows theirs.

The foods are then combined per nutrient. The amount is the mean of the foods'
amounts weighted by the grade of each (A 4, B 3, C 2, D 1, none 1), which is the
food's amount when there is one food. The interval is the range that holds all of
theirs.
"""

from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple

from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.derived_nutrients import derived_amount
from opennutrilab.products.services.derived_nutrients import derived_nutrients

Qualifier = SourceFoodNutrient.Qualifier

GRADE_WEIGHTS = {"A": Decimal(4), "B": Decimal(3), "C": Decimal(2), "D": Decimal(1)}
NO_GRADE_WEIGHT = Decimal(1)
GRADES_WORST_LAST = "ABCD"
# A nutrient in grams cannot be more than the 100 g it is given for.
MOST_GRAMS_PER_100_G = Decimal(100)
# What SourceFoodNutrient stores, and so what an estimate is given with.
_DIGITS = Decimal(1).scaleb(-6)


class Estimate(NamedTuple):
    """One nutrient of a reference, per 100 g, in the nutrient's unit."""

    # The point value; None when the nutrient is only there as traces.
    amount: Decimal | None
    low: Decimal | None
    # None when no food gives an upper end (traces only).
    high: Decimal | None
    # EXACT when a food measured it, else LESS_THAN or TRACES.
    qualifier: SourceFoodNutrient.Qualifier
    # The grades of the foods it is made of, best first.
    grades: tuple[str, ...]
    foods: tuple[SourceFood, ...]


class _Measure(NamedTuple):
    amount: Decimal | None
    low: Decimal | None
    high: Decimal | None
    qualifier: SourceFoodNutrient.Qualifier
    grade: str


def reference_composition(
    item: ReferenceIngredient | Preparation, derived: Iterable[Nutrient] | None = None
) -> dict[str, Estimate]:
    """
    What the foods of a reference, or of a preparation, say together, by nutrient
    code.

    One with no source food has no composition. `derived` is derived_nutrients()
    when not given; pass it when computing many, to read the catalogue once.
    """
    drawn_on = (
        {"food__reference_ingredients": item}
        if isinstance(item, ReferenceIngredient)
        else {"food__preparations": item}
    )
    rows = list(
        SourceFoodNutrient.objects.filter(**drawn_on)
        .select_related("food__source", "nutrient")
        .order_by("food_id")
    )
    by_food: defaultdict[int, list[SourceFoodNutrient]] = defaultdict(list)
    for row in rows:
        by_food[row.food_id].append(row)
    derivations = list(derived_nutrients() if derived is None else derived)

    per_nutrient: defaultdict[str, list[tuple[SourceFood, _Measure]]] = defaultdict(
        list
    )
    for food_rows in by_food.values():
        food = food_rows[0].food
        for code, measure in _food_measures(food_rows, derivations).items():
            per_nutrient[code].append((food, measure))
    return {code: _combine(found) for code, found in per_nutrient.items()}


def _food_measures(
    rows: Sequence[SourceFoodNutrient], derived: Iterable[Nutrient]
) -> dict[str, _Measure]:
    measures: dict[str, _Measure] = {}
    for row in rows:
        if (measure := _measure(row)) is not None:
            measures[row.nutrient_id] = measure
    for nutrient in derived:
        if nutrient.code not in measures and (measure := _derive(nutrient, measures)):
            measures[nutrient.code] = measure
    return measures


def _measure(row: SourceFoodNutrient) -> _Measure | None:
    """What one value of a food says, or None when it was not measured."""
    if row.qualifier == Qualifier.TRACES.value:
        return _Measure(None, Decimal(0), None, Qualifier.TRACES, row.confidence)
    amount = row.amount
    if amount is None:
        return None
    if row.qualifier == Qualifier.LESS_THAN.value:
        return _Measure(
            _round(amount / 2), Decimal(0), amount, Qualifier.LESS_THAN, row.confidence
        )
    margin = rounding_margin(amount)
    low = row.minimum if row.minimum is not None else max(Decimal(0), amount - margin)
    high = row.maximum if row.maximum is not None else amount + margin
    if row.nutrient.unit == Nutrient.Unit.GRAM.value:
        high = min(high, MOST_GRAMS_PER_100_G)
    return _Measure(
        amount, min(low, amount), max(high, amount), Qualifier.EXACT, row.confidence
    )


def rounding_margin(amount: Decimal) -> Decimal:
    """
    Half of the last decimal `amount` is written with, trailing zeros ignored.

    The rule is the one for the figures a label declares: 33 is 32.5 to 33.5 and
    9.30 is 9.25 to 9.35. Zeros before the point are digits, not a lack of them.
    """
    if amount == 0:
        return Decimal(0)
    exponent = amount.normalize().as_tuple().exponent
    return (
        Decimal(5).scaleb(min(0, exponent) - 1)
        if isinstance(exponent, int)
        else Decimal(0)
    )


def _derive(nutrient: Nutrient, measures: dict[str, _Measure]) -> _Measure | None:
    """A nutrient worked out from the amounts of a food, with its interval."""
    terms = {c.component_id for c in nutrient.components.all()}
    if not terms:
        return None
    amount = derived_amount(nutrient, {c: _field(measures, c, "amount") for c in terms})
    if amount is None:
        return None
    low = derived_amount(nutrient, {c: _field(measures, c, "low") for c in terms})
    high = derived_amount(nutrient, {c: _field(measures, c, "high") for c in terms})
    if low is None or high is None:
        return None
    return _Measure(
        _round(amount),
        _round(low),
        _round(high),
        Qualifier.EXACT,
        _worst_grade(measures[c].grade for c in terms),
    )


def _field(measures: dict[str, _Measure], code: str, field: str) -> Decimal | None:
    measure = measures.get(code)
    value: Decimal | None = getattr(measure, field, None)
    return value


def _worst_grade(grades: Iterable[str]) -> str:
    """The lowest grade of what a value is made of; none if any has none."""
    found = list(grades)
    if not found or "" in found:
        return ""
    return max(found, key=GRADES_WORST_LAST.index)


def _combine(found: Sequence[tuple[SourceFood, _Measure]]) -> Estimate:
    weighted = [
        (m.amount, GRADE_WEIGHTS.get(m.grade, NO_GRADE_WEIGHT))
        for _, m in found
        if m.amount is not None
    ]
    amount = (
        _round(
            sum((a * w for a, w in weighted), Decimal(0))
            / sum((w for _, w in weighted), Decimal(0))
        )
        if weighted
        else None
    )
    lows = [m.low for _, m in found if m.low is not None]
    highs = [m.high for _, m in found if m.high is not None]
    qualifiers = {m.qualifier for _, m in found}
    qualifier = next(
        q
        for q in (Qualifier.EXACT, Qualifier.LESS_THAN, Qualifier.TRACES)
        if q in qualifiers
    )
    grades = sorted({m.grade for _, m in found if m.grade}, key=GRADES_WORST_LAST.index)
    return Estimate(
        amount=amount,
        low=min(lows) if lows else None,
        high=max(highs) if highs else None,
        qualifier=qualifier,
        grades=tuple(grades),
        foods=tuple({food.pk: food for food, _ in found}.values()),
    )


def _round(value: Decimal) -> Decimal:
    return value.quantize(_DIGITS)
