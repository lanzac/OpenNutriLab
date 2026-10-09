"""
What a day's meals bring, meal by meal and over the day, against the user's needs.

A product's composition is per 100 g (products.services.stored_estimates): what its
label declares where it declares it, and its estimate for the rest. A portion of a
product is some grams of it, so what it brings is its composition times grams over
100, and a meal or a day is the sum over its portions. Like the estimates it is
made of, a total keeps three things:

- the amount, and the interval it lies in (`low`, `high`), which are the sums of
  the portions' own;
- the coverage: the share of the mass, in percent, whose product gives a value for
  the nutrient. A nutrient a product does not give is not zero, but it is counted
  as nothing, so the amount is what is at least there, and the upper end is not
  known (None) unless every product gives the nutrient.

A need is met or not by the amount; the verdict says how far to trust it: a day is
below a need for certain only when even the upper end is, and within it for certain
only when the whole interval is.

Energy shares in the needs (fat at 35 to 40 % of the energy) were turned into
grams at the person's energy need (services.needs): a day within 5 % of its energy,
which the needs ask, is within 5 % of those grams too.
"""

from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from django.db.models import TextChoices

from opennutrilab.meals.models import Meal
from opennutrilab.meals.models import MealItem
from opennutrilab.meals.models import Profile
from opennutrilab.meals.services.needs import Need
from opennutrilab.meals.services.needs import Ratio
from opennutrilab.meals.services.needs import daily_needs
from opennutrilab.products.models import Nutrient
from opennutrilab.products.services.stored_estimates import Amount
from opennutrilab.products.services.stored_estimates import compositions
from opennutrilab.users.models import User


class Status(TextChoices):
    BELOW = "below"
    WITHIN = "within"
    ABOVE = "above"
    # A ratio over nothing.
    UNKNOWN = "unknown"


class Total(NamedTuple):
    """An amount of a nutrient, in the unit of the catalogue."""

    amount: Decimal
    low: Decimal
    # None when no upper end is known.
    high: Decimal | None
    # The share of the mass, in percent, whose product gives a value.
    coverage: Decimal


class Portion(NamedTuple):
    """Some grams of a product, with its composition per 100 g."""

    grams: Decimal
    composition: Mapping[str, Amount]


class Verdict(NamedTuple):
    status: str
    # Whether the whole interval of the total says the same.
    certain: bool


class NeedStatus(NamedTuple):
    need: Need
    name: str
    unit: str
    group: str
    total: Total
    verdict: Verdict


class RatioStatus(NamedTuple):
    ratio: Ratio
    numerator: str
    denominator: str
    value: Decimal | None
    low: Decimal | None
    high: Decimal | None
    verdict: Verdict


class GenericFood(NamedTuple):
    """
    A food of a table that is no product of the inventory, as a suggestion names it:
    "huile de lin", not a brand. It has no serving and is counted in grams.
    """

    code: str
    name: str
    group: str
    url: str

    @property
    def pk(self) -> str:
        """The key it goes by where a product goes by its barcode."""
        return f"ciqual:{self.code}"


class GenericItem(NamedTuple):
    """Some grams of a generic food in a meal: an item that is not saved."""

    food: GenericFood
    quantity: Decimal
    id: None = None
    unit: str = "g"

    @property
    def product(self) -> GenericFood:
        return self.food

    @property
    def product_id(self) -> str:
        return self.food.pk

    @property
    def grams(self) -> Decimal:
        return self.quantity


class MealReport(NamedTuple):
    kind: str
    label: str
    items: list[MealItem | GenericItem]
    # The grams of the items that have a mass; an item of servings of a product that
    # has none is left out of every total.
    mass: Decimal
    totals: dict[str, Total]


class DayReport(NamedTuple):
    day: date
    meals: list[MealReport]
    mass: Decimal
    totals: dict[str, Total]
    # None without a profile to work the needs out from.
    needs: list[NeedStatus] | None
    ratios: list[RatioStatus] | None
    # The nutrients' names, units and groups, by code.
    catalogue: dict[str, Nutrient]


NOTHING = Total(Decimal(0), Decimal(0), None, Decimal(0))


def add_up(portions: Sequence[Portion]) -> dict[str, Total]:
    """
    The totals of some portions, by nutrient code, for each nutrient that at least
    one of them gives. See the module for what a total is.
    """
    mass = sum((p.grams for p in portions), Decimal(0))
    if mass <= 0:
        return {}
    totals: dict[str, Total] = {}
    for code in {code for p in portions for code in p.composition}:
        amount = low = Decimal(0)
        high: Decimal | None = Decimal(0)
        covered = Decimal(0)
        for portion in portions:
            share = portion.grams / 100
            found = portion.composition.get(code)
            if found is None:
                high = None
                continue
            amount += share * found.amount
            low += share * found.low
            high = (
                None
                if high is None or found.high is None
                else high + share * found.high
            )
            covered += portion.grams * found.coverage
        totals[code] = Total(amount, low, high, covered / mass)
    return totals


def combine(totals: Mapping[str, Total], terms: Mapping[str, Decimal]) -> Total:
    """
    The weighted sum of some nutrients' totals (EPA and DHA, or sodium in moles).
    A nutrient no portion gives counts as nothing, known for none of the mass.
    """
    amount = low = Decimal(0)
    high: Decimal | None = Decimal(0)
    coverage: Decimal | None = None
    for code, weight in terms.items():
        found = totals.get(code, NOTHING)
        amount += weight * found.amount
        low += weight * found.low
        high = (
            None if high is None or found.high is None else high + weight * found.high
        )
        coverage = found.coverage if coverage is None else min(coverage, found.coverage)
    return Total(amount, low, high, coverage or Decimal(0))


def verdict(total: Total, low: Decimal | None, high: Decimal | None) -> Verdict:
    """Whether a total is below, within or above the ends of a need."""
    if low is not None and total.amount < low:
        return Verdict(
            Status.BELOW, certain=total.high is not None and total.high < low
        )
    if high is not None and total.amount > high:
        return Verdict(Status.ABOVE, certain=total.low > high)
    certain = (low is None or total.low >= low) and (
        high is None or (total.high is not None and total.high <= high)
    )
    return Verdict(Status.WITHIN, certain=certain)


def ratio_of(
    totals: Mapping[str, Total],
    numerator: Mapping[str, Decimal],
    denominator: Mapping[str, Decimal],
) -> Total | None:
    """
    One total over another, as a total: the value, the interval it lies in, and the
    coverage of the less covered. None over nothing.

    The lowest it can be is the numerator's lowest over the denominator's highest,
    and the highest the numerator's highest over the denominator's lowest.
    """
    top, bottom = combine(totals, numerator), combine(totals, denominator)
    if bottom.amount <= 0:
        return None
    low = (
        top.low / bottom.high
        if bottom.high is not None and bottom.high > 0
        else Decimal(0)
    )
    high = top.high / bottom.low if top.high is not None and bottom.low > 0 else None
    return Total(
        top.amount / bottom.amount, low, high, min(top.coverage, bottom.coverage)
    )


def needs_status(
    needs: Sequence[Need],
    totals: Mapping[str, Total],
    catalogue: Mapping[str, Nutrient],
) -> list[NeedStatus]:
    """Each need set against the totals of a day."""
    statuses: list[NeedStatus] = []
    for need in needs:
        total = combine(totals, dict.fromkeys(need.nutrients, Decimal(1)))
        first = catalogue[need.nutrients[0]]
        statuses.append(
            NeedStatus(
                need=need,
                name=" + ".join(catalogue[code].name for code in need.nutrients),
                unit=first.unit,
                group=first.group,
                total=total,
                verdict=verdict(total, need.low, need.high),
            )
        )
    return statuses


def ratios_status(
    ratios: Sequence[Ratio],
    totals: Mapping[str, Total],
    catalogue: Mapping[str, Nutrient],
) -> list[RatioStatus]:
    """Each ratio set against the totals of a day."""
    statuses: list[RatioStatus] = []
    for ratio in ratios:
        found = ratio_of(totals, ratio.numerator, ratio.denominator)
        statuses.append(
            RatioStatus(
                ratio=ratio,
                numerator=" + ".join(catalogue[code].name for code in ratio.numerator),
                denominator=" + ".join(
                    catalogue[code].name for code in ratio.denominator
                ),
                value=None if found is None else found.amount,
                low=None if found is None else found.low,
                high=None if found is None else found.high,
                verdict=(
                    Verdict(Status.UNKNOWN, certain=False)
                    if found is None
                    else verdict(found, ratio.low, ratio.high)
                ),
            )
        )
    return statuses


def day_report(user: User, day: date) -> DayReport:
    """The meals of a user on a day, with their totals and the day's against needs."""
    meals = Meal.objects.filter(user=user, date=day).prefetch_related("items__product")
    return report_of(user, day, {meal.kind: list(meal.items.all()) for meal in meals})


def report_of(
    user: User,
    day: date,
    items: Mapping[str, Sequence[MealItem | GenericItem]],
    foods: Mapping[str, Mapping[str, Amount]] | None = None,
) -> DayReport:
    """
    The report of a day made of `items`, by kind of meal. They need not be saved:
    a day that is only proposed (services.proposals) is reported the same way.

    `foods` are the compositions of the generic foods among the items, by their key
    (GenericFood.pk): they are no product, so no estimate is kept for them.
    """
    products = {
        item.product_id: item.product
        for found in items.values()
        for item in found
        if isinstance(item, MealItem)
    }
    composition = {**compositions(products.values()), **(foods or {})}

    def portions(found: Sequence[MealItem | GenericItem]) -> list[Portion]:
        return [
            Portion(item.grams, composition[item.product_id])
            for item in found
            if item.grams is not None
        ]

    reports: list[MealReport] = []
    for kind, label in Meal.Kind.choices:
        found = list(items.get(kind, []))
        found_portions = portions(found)
        reports.append(
            MealReport(
                kind=kind,
                label=str(label),
                items=found,
                mass=sum((p.grams for p in found_portions), Decimal(0)),
                totals=add_up(found_portions),
            )
        )
    every = [p for found in items.values() for p in portions(list(found))]
    totals = add_up(every)

    profile = Profile.objects.filter(user=user).first()
    needs = daily_needs(profile) if profile is not None else None
    wanted = {code for meal in reports for code in meal.totals}
    if needs is not None:
        wanted |= {code for need in needs.nutrients for code in need.nutrients}
        wanted |= {
            code
            for ratio in needs.ratios
            for code in (*ratio.numerator, *ratio.denominator)
        }
    catalogue = Nutrient.objects.in_bulk(wanted)
    return DayReport(
        day=day,
        meals=reports,
        mass=sum((p.grams for p in every), Decimal(0)),
        totals=totals,
        needs=None
        if needs is None
        else needs_status(needs.nutrients, totals, catalogue),
        ratios=None
        if needs is None
        else ratios_status(needs.ratios, totals, catalogue),
        catalogue=catalogue,
    )
