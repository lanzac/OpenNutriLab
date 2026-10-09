"""
Foods made in-house, for the ingredients no source has a food for.

A reference ingredient draws on source foods, and some have none: CIQUAL has
nothing for "flocons de soja" or "purée de tomate double concentrée". Such a food
is worked out from the foods that come closest, and kept as a food of the source
`Manual`, so that it counts like any other: the reference links to it, and its
composition, its ranges and its grade are read the usual way
(reference_composition).

What is a judgement is in the spec, which says which foods it comes from (the
proxies), in what shares, and how far they are brought to the ingredient (the
water it has left, the nutrients given by hand). What is arithmetic is here:

- Every nutrient the proxies all measure is taken, as the mean of theirs weighted
  by their shares. One that a proxy did not measure is left out, and said: it is
  not zero.
- Bringing the proxies to a water content keeps their dry matter: each is
  multiplied by (100 - water wanted) / (100 - its water), the water excepted.
- Each figure is an interval, as everything estimated here is: the range that
  holds the proxies' own, widened to at least `margin` (15 %) of the amount, since
  an ingredient is never exactly a food of a table. An amount given by hand with a
  range keeps that range: the margin only widens a side that is not given. The
  grade is D, the worst of CIQUAL's scale, for all of them: the figures are
  estimated, not measured.
- What the food says is checked against the 100 g it is for: the main components
  (water, fat, carbohydrates, fibre, proteins, ash...) add up to about 100.

Some ingredients are no food (a flavouring, a rennet, a culture, an enzyme): their
composition is not defined, there is nothing to scale, and what is known is what
they cannot be. A nutrient is then given as a range with no amount: it is kept as
that range, and its amount is the lower end, what is surely there, as the estimate
of a product counts a nutrient no ingredient gives. The ingredient adds no gram to
the point values of a product, and its upper bounds are not left unknown.

Nothing here marks a reference as curated: that stays a person's decision.
"""

from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from decimal import Decimal
from decimal import InvalidOperation
from typing import Any
from typing import NamedTuple

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.text import slugify

from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.food_forms import STATE_WORDS
from opennutrilab.products.services.food_forms import form_of_food
from opennutrilab.products.services.food_forms import has_a_word_of
from opennutrilab.products.services.reference_composition import Measure
from opennutrilab.products.services.reference_composition import measure_of

Qualifier = SourceFoodNutrient.Qualifier

MANUAL_SOURCE_CODE = "Manual"
MANUAL_FOOD_GROUP = "Estimation manuelle"
GRADE = "D"
DEFAULT_MARGIN = Decimal("0.15")
MOST_GRAMS_PER_100_G = Decimal(100)
_DIGITS = Decimal(1).scaleb(-6)
_NAME_LENGTH = 255
_CODE_LENGTH = 50

# The nutrients that make up a food's 100 g. Their sum is checked when the first
# six are all there: CIQUAL's own foods add up to 95-105 g in 98 % of the cases.
MASS_BALANCE = (
    "water",
    "fat",
    "carbohydrates",
    "fiber",
    "proteins",
    "ash",
    "alcohol",
    "organic_acids",
    "polyols",
)
MASS_BALANCE_REQUIRED = MASS_BALANCE[:6]
MASS_BALANCE_RANGE = (Decimal(95), Decimal(105))
# Without them an estimate ignores a food's composition altogether.
NEEDED_BY_AN_ESTIMATE = ("fat", "carbohydrates", "proteins")

_KEYS = frozenset(
    [
        "code",
        "name_fr",
        "name_en",
        "proxies",
        "water",
        "nutrients",
        "exclude",
        "margin",
        "basis_fr",
        "basis_en",
        "references",
    ]
)
_LEADS = {"fr": "estimé d'après", "en": "estimated from"}
_WATER_PHRASES = {"fr": "à {water} % d'eau", "en": "at {water} % water"}


class CustomFoodError(Exception):
    """The spec cannot be made into a food; the message says what to change."""


@dataclass(frozen=True)
class Proxy:
    """A source food the new one is worked out from, and its share."""

    source: str
    code: str
    weight: Decimal = Decimal(1)


@dataclass(frozen=True)
class Given:
    """
    An amount given by hand, with the range it is given with if any.

    A range given without an amount (`bounds_only`) is what is known of an
    ingredient whose composition is not defined, a flavouring for instance. Its
    amount is the lower end, what is surely there, as a nutrient no ingredient
    gives counts as nothing in the estimate of a product: the middle of the range
    would be a figure nobody knows, and would add grams to every product the
    ingredient is in.
    """

    amount: Decimal
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    bounds_only: bool = False


@dataclass(frozen=True)
class CustomFoodSpec:
    name_fr: str
    name_en: str
    code: str
    proxies: tuple[Proxy, ...] = ()
    # The water the food has, in g per 100 g, that the proxies are brought to.
    water: Decimal | None = None
    nutrients: Mapping[str, Given] = field(default_factory=dict[str, Given])
    exclude: frozenset[str] = frozenset()
    margin: Decimal = DEFAULT_MARGIN
    # What the figures come from, when the proxies do not say it all.
    basis_fr: str = ""
    basis_en: str = ""
    # Reference ingredients to link the food to, by id or by name.
    references: tuple[int | str, ...] = ()


class Value(NamedTuple):
    """One nutrient of the food, per 100 g, in the nutrient's unit."""

    amount: Decimal | None
    low: Decimal | None
    high: Decimal | None
    qualifier: SourceFoodNutrient.Qualifier


@dataclass
class WorkedOut:
    values: dict[str, Value] = field(default_factory=dict)
    # Nutrients the proxies could not give, with why.
    left_out: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Nutrients given as a range and nothing else: their amount says nothing.
    bounded: set[str] = field(default_factory=set[str])


class Linked(NamedTuple):
    reference: ReferenceIngredient
    # How many other foods the reference already draws on: with some, this one
    # widens its range and is no longer the only reading.
    other_foods: int


@dataclass(frozen=True)
class CustomFood:
    food: SourceFood
    created: bool
    worked_out: WorkedOut
    linked: list[Linked]


# ----------------------------------------------------------------------------
# Reading a spec
# ----------------------------------------------------------------------------
def parse_spec(data: object) -> CustomFoodSpec:  # noqa: C901
    """The spec a JSON file holds, checked; raises CustomFoodError."""
    if not isinstance(data, dict):
        msg = "The spec must be a JSON object."
        raise CustomFoodError(msg)
    spec: dict[str, Any] = data  # pyright: ignore[reportUnknownVariableType]
    if unknown := sorted(set(spec) - _KEYS):
        msg = f"Unknown key(s) in the spec: {', '.join(unknown)}."
        raise CustomFoodError(msg)

    name_fr = _text(spec, "name_fr")
    name_en = _text(spec, "name_en")
    if not (name_fr or name_en):
        msg = "The food needs a name: name_fr or name_en."
        raise CustomFoodError(msg)
    code = _text(spec, "code") or slugify(name_en or name_fr)
    if not code or len(code) > _CODE_LENGTH:
        msg = f"The code must be 1 to {_CODE_LENGTH} characters, got {code!r}."
        raise CustomFoodError(msg)

    proxies = tuple(_proxy(p) for p in _list(spec, "proxies"))
    nutrients = _given(spec.get("nutrients", {}))
    exclude = frozenset(str(c) for c in _list(spec, "exclude"))
    water = _decimal(spec["water"], "water") if "water" in spec else None
    margin = _decimal(spec["margin"], "margin") if "margin" in spec else DEFAULT_MARGIN
    basis_fr, basis_en = _text(spec, "basis_fr"), _text(spec, "basis_en")

    if not 0 <= margin < 1:
        msg = f"margin is a share between 0 and 1, got {margin}."
        raise CustomFoodError(msg)
    if water is not None:
        if not proxies:
            msg = "water brings the proxies to a water content: it needs proxies."
            raise CustomFoodError(msg)
        if not 0 <= water < MOST_GRAMS_PER_100_G:
            msg = f"water is g per 100 g, from 0 to under 100, got {water}."
            raise CustomFoodError(msg)
    if not proxies and not (nutrients and (basis_fr or basis_en)):
        msg = (
            "Without proxies the food is made of the nutrients given by hand, and "
            "basis_fr or basis_en must say what they come from."
        )
        raise CustomFoodError(msg)
    if clash := sorted(exclude & set(nutrients)):
        msg = f"Both excluded and given by hand: {', '.join(clash)}."
        raise CustomFoodError(msg)
    if len({(p.source, p.code) for p in proxies}) != len(proxies):
        msg = "A proxy is listed twice."
        raise CustomFoodError(msg)

    return CustomFoodSpec(
        name_fr=name_fr,
        name_en=name_en,
        code=code,
        proxies=proxies,
        water=water,
        nutrients=nutrients,
        exclude=exclude,
        margin=margin,
        basis_fr=basis_fr,
        basis_en=basis_en,
        references=tuple(_reference_id(r) for r in _list(spec, "references")),
    )


def _text(spec: Mapping[str, Any], key: str) -> str:
    value = spec.get(key, "")
    if not isinstance(value, str):
        msg = f"{key} must be text."
        raise CustomFoodError(msg)
    return " ".join(value.split())


def _list(spec: Mapping[str, Any], key: str) -> list[Any]:
    value = spec.get(key, [])
    if not isinstance(value, list):
        msg = f"{key} must be a list."
        raise CustomFoodError(msg)
    return value  # pyright: ignore[reportUnknownVariableType]


def _decimal(value: object, what: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        msg = f"{what} must be a number, got {value!r}."
        raise CustomFoodError(msg)
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        msg = f"{what} must be a number, got {value!r}."
        raise CustomFoodError(msg) from None
    if not number.is_finite():
        msg = f"{what} must be a number, got {value!r}."
        raise CustomFoodError(msg)
    return number


def _proxy(item: object) -> Proxy:
    if not isinstance(item, dict):
        msg = f'A proxy is {{"source": ..., "code": ...}}, got {item!r}.'
        raise CustomFoodError(msg)
    entry: dict[str, Any] = item  # pyright: ignore[reportUnknownVariableType]
    if extra := sorted(set(entry) - {"source", "code", "weight"}):
        msg = f"Unknown key(s) in a proxy: {', '.join(extra)}."
        raise CustomFoodError(msg)
    source, code = entry.get("source"), entry.get("code")
    if not (isinstance(source, str) and isinstance(code, str) and source and code):
        msg = f'A proxy needs its "source" (a source code) and its "code": {item!r}.'
        raise CustomFoodError(msg)
    weight = _decimal(entry.get("weight", 1), "a proxy's weight")
    if weight <= 0:
        msg = f"A proxy's weight must be above 0, got {weight}."
        raise CustomFoodError(msg)
    return Proxy(source=source, code=code, weight=weight)


def _given(raw: object) -> dict[str, Given]:
    if not isinstance(raw, dict):
        msg = 'nutrients is {"code": amount, ...}.'
        raise CustomFoodError(msg)
    entries: dict[Any, Any] = raw  # pyright: ignore[reportUnknownVariableType]
    given: dict[str, Given] = {}
    for code, item in entries.items():
        what = f"nutrients.{code}"
        if isinstance(item, dict):
            entry: dict[str, Any] = item  # pyright: ignore[reportUnknownVariableType]
            if extra := sorted(set(entry) - {"amount", "min", "max"}):
                msg = f"Unknown key(s) in {what}: {', '.join(extra)}."
                raise CustomFoodError(msg)
            low = _decimal(entry["min"], f"{what}.min") if "min" in entry else None
            high = _decimal(entry["max"], f"{what}.max") if "max" in entry else None
            bounds_only = False
            if "amount" in entry:
                amount = _decimal(entry["amount"], f"{what}.amount")
            elif low is not None and high is not None:
                amount, bounds_only = low, True
            else:
                msg = f"{what} needs an amount, or both a min and a max."
                raise CustomFoodError(msg)
        else:
            amount, low, high, bounds_only = _decimal(item, what), None, None, False
        if amount < 0 or (low is not None and low < 0):
            msg = f"{what} cannot be negative."
            raise CustomFoodError(msg)
        if (low is not None and low > amount) or (high is not None and high < amount):
            msg = f"{what} must lie between its min and its max."
            raise CustomFoodError(msg)
        given[str(code)] = Given(amount, low, high, bounds_only)
    return given


def _reference_id(item: object) -> int | str:
    if isinstance(item, bool) or not isinstance(item, int | str):
        msg = f"A reference is an id or a name, got {item!r}."
        raise CustomFoodError(msg)
    return item


# ----------------------------------------------------------------------------
# Working the figures out
# ----------------------------------------------------------------------------
def work_out(
    spec: CustomFoodSpec, proxies: Sequence[tuple[Proxy, SourceFood]]
) -> WorkedOut:
    """The nutrients of the food, from its proxies and what is given by hand."""
    units: dict[str, str] = dict(Nutrient.objects.values_list("code", "unit"))
    if unknown := sorted((set(spec.nutrients) | spec.exclude) - set(units)):
        msg = f"Not in the catalogue of nutrients: {', '.join(unknown)}."
        raise CustomFoodError(msg)

    worked = WorkedOut()
    if proxies:
        _from_proxies(spec, proxies, units, worked)
    for code, given in spec.nutrients.items():
        # A range that is given is the range: the margin only widens a side that is
        # not, so a specification's "75 to 80 %" is not made "66 to 89 %".
        margins = (
            Decimal(0) if given.minimum is not None else spec.margin,
            Decimal(0) if given.maximum is not None else spec.margin,
        )
        worked.values[code] = _widened(
            given.amount,
            given.minimum if given.minimum is not None else given.amount,
            given.maximum if given.maximum is not None else given.amount,
            margins,
            code,
            units[code],
        )
        worked.left_out.pop(code, None)
        if given.bounds_only:
            worked.bounded.add(code)
    if not worked.values:
        msg = "Nothing to keep: the proxies give no nutrient."
        raise CustomFoodError(msg)
    worked.warnings.extend(_balance_warnings(worked.values, worked.bounded))
    return worked


def _from_proxies(
    spec: CustomFoodSpec,
    proxies: Sequence[tuple[Proxy, SourceFood]],
    units: Mapping[str, str],
    worked: WorkedOut,
) -> None:
    total = sum((proxy.weight for proxy, _ in proxies), Decimal(0))
    measured = [
        (proxy.weight / total, food, _measures(food)) for proxy, food in proxies
    ]
    factors = [_factor(spec.water, food, found) for _, food, found in measured]
    codes = sorted({c for _, _, found in measured for c in found} - spec.exclude)

    for code in codes:
        if code == "water" and spec.water is not None:
            worked.values[code] = _widened(
                spec.water,
                spec.water,
                spec.water,
                (spec.margin, spec.margin),
                code,
                units[code],
            )
            continue
        lacking = [food.code for _, food, found in measured if code not in found]
        if lacking:
            worked.left_out[code] = f"not measured in {', '.join(lacking)}"
            continue
        parts = [
            (share, _scaled(found[code], factor))
            for (share, _, found), factor in zip(measured, factors, strict=True)
        ]
        mixed = _mix(parts, spec.margin, code, units[code])
        if isinstance(mixed, str):
            worked.left_out[code] = mixed
        else:
            worked.values[code] = mixed


def _measures(food: SourceFood) -> dict[str, Measure]:
    rows = food.nutrients.select_related("nutrient")
    found = {row.nutrient_id: m for row in rows if (m := measure_of(row)) is not None}
    if not found:
        msg = f"{food.source.code} {food.code} has no nutrient measured."
        raise CustomFoodError(msg)
    return found


def _factor(
    water: Decimal | None, food: SourceFood, found: Mapping[str, Measure]
) -> Decimal:
    """What brings a proxy's dry matter to a water content: 1 without one."""
    if water is None:
        return Decimal(1)
    own = found.get("water")
    if own is None or own.amount is None or own.qualifier != Qualifier.EXACT:
        msg = (
            f"{food.source.code} {food.code} does not say its water, so it cannot "
            "be brought to a water content."
        )
        raise CustomFoodError(msg)
    if own.amount >= MOST_GRAMS_PER_100_G:
        msg = f"{food.source.code} {food.code} is all water: there is no dry matter."
        raise CustomFoodError(msg)
    return (MOST_GRAMS_PER_100_G - water) / (MOST_GRAMS_PER_100_G - own.amount)


def _scaled(measure: Measure, factor: Decimal) -> Measure:
    if factor == 1:
        return measure
    return measure._replace(
        amount=None if measure.amount is None else measure.amount * factor,
        low=None if measure.low is None else measure.low * factor,
        high=None if measure.high is None else measure.high * factor,
    )


def _mix(
    parts: Sequence[tuple[Decimal, Measure]], margin: Decimal, code: str, unit: str
) -> Value | str:
    """
    What the proxies say of one nutrient together: a value, or why it is left out.

    The amount is the mean of theirs by share. The range holds all of theirs and
    not the mean of their ranges: the shares are an assumption, and the food
    could be anywhere between its proxies.
    """
    qualifiers = {m.qualifier for _, m in parts}
    if qualifiers == {Qualifier.TRACES}:
        return Value(None, None, None, Qualifier.TRACES)
    if Qualifier.TRACES in qualifiers:
        return "traces in some of the foods and a figure in others"
    if qualifiers == {Qualifier.LESS_THAN}:
        limit = sum((s * (m.high or Decimal(0)) for s, m in parts), Decimal(0))
        return Value(_round(limit), None, None, Qualifier.LESS_THAN)
    amount = sum((s * (m.amount or Decimal(0)) for s, m in parts), Decimal(0))
    low = min(m.low if m.low is not None else amount for _, m in parts)
    high = max(m.high if m.high is not None else amount for _, m in parts)
    return _widened(amount, low, high, (margin, margin), code, unit)


def _widened(  # noqa: PLR0913
    amount: Decimal,
    low: Decimal,
    high: Decimal,
    margins: tuple[Decimal, Decimal],
    code: str,
    unit: str,
) -> Value:
    """The range, at least a margin of the amount on each side, kept in 0-100 g."""
    if unit == Nutrient.Unit.GRAM.value and amount > MOST_GRAMS_PER_100_G:
        msg = (
            f"{code} comes to {_round(amount)} g per 100 g: more than the food "
            "weighs. Check the water it is brought to, or the amount given."
        )
        raise CustomFoodError(msg)
    below, above = margins
    low = max(Decimal(0), min(low, amount * (1 - below)))
    high = max(high, amount * (1 + above))
    if unit == Nutrient.Unit.GRAM.value:
        high = min(high, MOST_GRAMS_PER_100_G)
    return Value(_round(amount), _round(low), _round(high), Qualifier.EXACT)


def _round(value: Decimal) -> Decimal:
    return value.quantize(_DIGITS)


def _balance_warnings(values: Mapping[str, Value], bounded: set[str]) -> list[str]:
    warnings: list[str] = []
    if missing := [c for c in NEEDED_BY_AN_ESTIMATE if c not in values]:
        warnings.append(
            f"No {', '.join(missing)}: an estimate ignores a composition without "
            "fat, carbohydrates and proteins."
        )
    if not all(
        c in values and values[c].amount is not None for c in MASS_BALANCE_REQUIRED
    ):
        return warnings
    low, high = MASS_BALANCE_RANGE
    components = [values[c] for c in MASS_BALANCE if c in values]
    if bounded.intersection(MASS_BALANCE):
        # A range with no amount: what can be asked is that some composition inside
        # the ranges adds up to 100 g, not that their middles do.
        least = sum((v.low or Decimal(0) for v in components), Decimal(0))
        most = sum((v.high or Decimal(0) for v in components), Decimal(0))
        if least > high or most < low:
            warnings.append(
                "Water, fat, carbohydrates, fibre, proteins and ash cannot add up to "
                f"100 g within the ranges given ({least:.1f} to {most:.1f} g): "
                "check the bounds."
            )
        return warnings
    total = sum((v.amount or Decimal(0) for v in components), Decimal(0))
    if not low <= total <= high:
        warnings.append(
            "Water, fat, carbohydrates, fibre, proteins and ash add up to "
            f"{total:.1f} g per 100 g, not about 100: check the arithmetic."
        )
    return warnings


# ----------------------------------------------------------------------------
# The food: its name, and keeping it
# ----------------------------------------------------------------------------
def create_custom_food(spec: CustomFoodSpec, *, replace: bool = False) -> CustomFood:
    """
    Make the food in the source `Manual` (made if it is not there), and link it.

    A food with that code is refused unless `replace`, which keeps its row, so
    what links to it stays, and writes its names and nutrients again. Nothing is
    written when the spec is refused. A reference it links to keeps its status:
    curating it is for a person.
    """
    with transaction.atomic():
        proxies = [(proxy, _proxy_food(proxy)) for proxy in spec.proxies]
        references = [_reference(identifier) for identifier in spec.references]
        worked = work_out(spec, proxies)
        name_fr, name_en = _names(spec, [food for _, food in proxies])

        source, _made = Source.objects.get_or_create(
            code=MANUAL_SOURCE_CODE,
            defaults={
                "name": "Manual",
                "attribution": (
                    "Foods estimated in-house from other sources' foods, or by "
                    "hand, where no source has the ingredient. Each name says what "
                    "the figures were worked out from; they are graded D."
                ),
            },
        )
        food = SourceFood.objects.filter(source=source, code=spec.code).first()
        if food is not None and not replace:
            msg = (
                f"{MANUAL_SOURCE_CODE} already has a food {spec.code!r}: "
                f"{food.name_fr or food.name_en}. Choose another code, or replace it."
            )
            raise CustomFoodError(msg)
        created = food is None
        if food is None:
            food = SourceFood(source=source, code=spec.code)
        food.name_fr, food.name_en = name_fr, name_en
        food.food_group = MANUAL_FOOD_GROUP
        food.save()

        food.nutrients.all().delete()
        SourceFoodNutrient.objects.bulk_create(
            SourceFoodNutrient(
                food=food,
                nutrient_id=code,
                amount=value.amount,
                minimum=value.low if value.qualifier == Qualifier.EXACT else None,
                maximum=value.high if value.qualifier == Qualifier.EXACT else None,
                qualifier=value.qualifier,
                confidence=GRADE,
            )
            for code, value in worked.values.items()
        )

        linked = [
            Linked(reference, reference.source_foods.exclude(pk=food.pk).count())
            for reference in references
        ]
        for reference in references:
            reference.source_foods.add(food)
    return CustomFood(food=food, created=created, worked_out=worked, linked=linked)


def _proxy_food(proxy: Proxy) -> SourceFood:
    food = (
        SourceFood.objects.select_related("source")
        .filter(source__code=proxy.source, code=proxy.code)
        .first()
    )
    if food is None:
        msg = f"No food {proxy.code!r} in the source {proxy.source!r}."
        raise CustomFoodError(msg)
    return food


def _reference(identifier: int | str) -> ReferenceIngredient:
    """A reference by id, or by its English or French name (case apart)."""
    if isinstance(identifier, int):
        found = list(ReferenceIngredient.objects.filter(pk=identifier))
    else:
        name = " ".join(identifier.split()).lower()
        found = list(
            ReferenceIngredient.objects.alias(en=Lower("name_en"), fr=Lower("name_fr"))
            .filter(Q(en=name) | Q(fr=name))
            .order_by("pk")
        )
    if not found:
        msg = f"No reference ingredient is {identifier!r}."
        raise CustomFoodError(msg)
    if len(found) > 1:
        msg = f"{identifier!r} is the name of {len(found)} references: use an id."
        raise CustomFoodError(msg)
    return found[0]


def _names(spec: CustomFoodSpec, proxies: Sequence[SourceFood]) -> tuple[str, str]:
    """
    The food's names, each saying what the figures come from.

    The state of the food is read from its name (food_forms), so the basis must not
    change it: "Oignon, séché (estimé d'après Oignon, cuit)" would read as cooked.
    The basis made from the proxies leaves their states out, and a name that still
    reads differently is refused.
    """
    name_fr = _named("fr", spec.name_fr, spec.basis_fr, spec, proxies)
    name_en = _named("en", spec.name_en, spec.basis_en, spec, proxies)
    bare = form_of_food(SourceFood(name_fr=spec.name_fr, name_en=spec.name_en))
    full = form_of_food(SourceFood(name_fr=name_fr, name_en=name_en))
    if bare != full:
        msg = (
            f"The basis changes the state the name reads as ({bare} -> {full}): "
            "word basis_fr and basis_en without a state (cru, cuit, sec, raw, "
            "cooked, dried...)."
        )
        raise CustomFoodError(msg)
    return name_fr, name_en


def _named(
    language: str,
    name: str,
    basis: str,
    spec: CustomFoodSpec,
    proxies: Sequence[SourceFood],
) -> str:
    if not name:
        return ""
    basis = basis or _basis(language, spec, proxies)
    full = f"{name} ({_LEADS[language]} {basis})" if basis else name
    if len(full) > _NAME_LENGTH:
        msg = (
            f"A name is {len(full)} characters, over {_NAME_LENGTH}: shorten the basis."
        )
        raise CustomFoodError(msg)
    return full


def _basis(language: str, spec: CustomFoodSpec, proxies: Sequence[SourceFood]) -> str:
    """The proxies, by name and source code, and the water they were brought to."""
    shares_differ = len({proxy.weight for proxy in spec.proxies}) > 1
    parts: list[str] = []
    for proxy, food in zip(spec.proxies, proxies, strict=True):
        name = (
            food.name_fr or food.name_en
            if language == "fr"
            else food.name_en or food.name_fr
        )
        part = f"{_without_states(name)} {food.source.name} {food.code}"
        parts.append(f"{part} x{proxy.weight.normalize():f}" if shares_differ else part)
    basis = "; ".join(parts)
    if spec.water is not None:
        water = _WATER_PHRASES[language].format(water=f"{spec.water.normalize():f}")
        basis = f"{basis}, {water}"
    return basis


def _without_states(name: str) -> str:
    """A CIQUAL name without its state segments: "Cassis, cru" is "Cassis"."""
    head, *segments = (segment.strip() for segment in name.split(","))
    kept = [s for s in segments if not has_a_word_of(s, STATE_WORDS)]
    return ", ".join([head, *kept])
