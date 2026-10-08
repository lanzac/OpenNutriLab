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

A preparation that draws on no food has, when its label lists none of its parts,
the composition of the references and the preparations it is made of
(components_composition). Their shares are not known, so it is a range and not a
fit.
"""

from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple

from opennutrilab.products.models import Additive
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
    item: ReferenceIngredient | Preparation | Additive,
    derived: Iterable[Nutrient] | None = None,
) -> dict[str, Estimate]:
    """
    What the foods of a reference, of a preparation or of an additive say
    together, by nutrient code.

    One with no source food has no composition. `derived` is derived_nutrients()
    when not given; pass it when computing many, to read the catalogue once.
    """
    drawn_on = (
        {"food__reference_ingredients": item}
        if isinstance(item, ReferenceIngredient)
        else {"food__preparations": item}
        if isinstance(item, Preparation)
        else {"food__additives": item}
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


def components_composition(
    preparation: Preparation,
    derived: Iterable[Nutrient] | None = None,
    _visiting: frozenset[int] = frozenset(),
) -> dict[str, Estimate]:
    """
    What a preparation is, if all that is known is what it is made of.

    Their shares are not known, so a nutrient is somewhere between the lowest and
    the highest of its components', whatever the mix is: the widest reading that
    is true of every recipe. The amount is the mean of theirs. It has no grade,
    since it is not measured on anything: it says "made of these", and no more.

    A component may be a preparation, which counts by its foods if it has some and
    else by what it is made of in turn. A preparation that is made of itself, however
    far down, says nothing: that part has no composition.

    It stands only when every component says something. A component with no
    composition could be most of the preparation, and a nutrient one of them does
    not give is not zero, so the preparation has none then, or lacks that nutrient.
    """
    visiting = _visiting | {preparation.pk}
    parts = [
        reference_composition(component, derived)
        for component in preparation.components.all()
    ]
    parts.extend(
        _preparation_part(part, derived, visiting)
        for part in preparation.preparation_components.all()
    )
    if not parts or not all(parts):
        return {}
    shared = set(parts[0]).intersection(*parts[1:])
    return {code: _hull([part[code] for part in parts]) for code in shared}


def _preparation_part(
    part: Preparation, derived: Iterable[Nutrient] | None, visiting: frozenset[int]
) -> dict[str, Estimate]:
    """What a preparation that is a component of another is, if anything is known."""
    if part.pk in visiting:
        return {}
    if composition := reference_composition(part, derived):
        return composition
    if part.source_foods.exists():
        return {}
    return components_composition(part, derived, visiting)


def _hull(estimates: Sequence[Estimate]) -> Estimate:
    """The range that holds each of these, with the mean of their amounts."""
    amounts = [e.amount for e in estimates if e.amount is not None]
    highs = [e.high for e in estimates if e.high is not None]
    qualifiers = {e.qualifier for e in estimates}
    return Estimate(
        amount=_round(sum(amounts, Decimal(0)) / len(amounts)) if amounts else None,
        low=min(e.low or Decimal(0) for e in estimates),
        high=max(highs) if len(highs) == len(estimates) else None,
        qualifier=next(
            q
            for q in (Qualifier.EXACT, Qualifier.LESS_THAN, Qualifier.TRACES)
            if q in qualifiers
        ),
        grades=(),
        foods=tuple({food.pk: food for e in estimates for food in e.foods}.values()),
    )


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
