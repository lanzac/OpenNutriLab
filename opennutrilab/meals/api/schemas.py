"""What the meals API serves and takes."""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Literal

from ninja import Field
from ninja import Schema

from opennutrilab.meals.models import Meal
from opennutrilab.meals.models import MealItem
from opennutrilab.meals.services.day_report import DayReport
from opennutrilab.meals.services.day_report import GenericItem
from opennutrilab.meals.services.day_report import MealReport
from opennutrilab.meals.services.day_report import NeedStatus
from opennutrilab.meals.services.day_report import RatioStatus
from opennutrilab.meals.services.day_report import Total
from opennutrilab.meals.services.needs import Kind
from opennutrilab.meals.services.proposals import Proposal
from opennutrilab.meals.services.suggestions import Suggestions
from opennutrilab.products.api.schemas.outbound import PackageOut
from opennutrilab.products.api.schemas.outbound import ServingOut
from opennutrilab.products.api.schemas.outbound import package_of
from opennutrilab.products.api.schemas.outbound import serving_of
from opennutrilab.products.models import Nutrient


class ItemIn(Schema):
    barcode: str
    quantity: Decimal = Field(gt=0, max_digits=7, decimal_places=2)
    unit: Literal["serving", "g"] = "serving"


class PlacedItemIn(Schema):
    """A product in a meal of a day that is put in place of the day's."""

    kind: Literal["breakfast", "lunch", "snack", "dinner"]
    barcode: str
    quantity: Decimal = Field(gt=0, max_digits=7, decimal_places=2)
    unit: Literal["serving", "g"] = "serving"


class DayIn(Schema):
    items: list[PlacedItemIn]


class MealIn(Schema):
    """What is changed of a meal of a day."""

    eaten: bool


class ItemChange(Schema):
    quantity: Decimal = Field(gt=0, max_digits=7, decimal_places=2)
    unit: Literal["serving", "g"]


class LimitsIn(Schema):
    # Empty, any meal.
    meals: list[Literal["breakfast", "lunch", "snack", "dinner"]] = []
    max_quantity: Decimal | None = Field(
        default=None, gt=0, max_digits=7, decimal_places=2
    )
    max_unit: Literal["serving", "g"] | None = None
    # All of the package in the day, in place of a most.
    use_all: bool = False
    # False, the product is left out of the days proposed.
    enabled: bool = True


class AllEnabledIn(Schema):
    """Every product of the inventory left out of the days proposed, or put in."""

    enabled: bool


class LimitsOut(Schema):
    barcode: str
    meals: list[str]
    max_quantity: Decimal | None
    max_unit: str
    use_all: bool
    enabled: bool


class TotalOut(Schema):
    """An amount in the nutrient's unit, with its interval and coverage."""

    amount: Decimal
    low: Decimal
    # None when no upper end is known.
    high: Decimal | None
    # The share of the mass, in percent, whose product gives a value.
    coverage: Decimal


class NutrientOut(Schema):
    name: str
    unit: str


class MealItemOut(Schema):
    # None for an item of a day that is only proposed.
    id: int | None
    barcode: str
    name: str
    # The product's photo, when it has one.
    image: str | None = None
    quantity: Decimal
    unit: str
    # None for servings of a product that has no serving any more.
    grams: Decimal | None
    serving: ServingOut | None
    # What the product's package holds, which an item is a share of, and what that
    # weighs: the same for a package in g, and for one in ml what its density says
    # (the same number when it is not known), in the grams `grams` is in.
    package: PackageOut | None = None
    package_grams: Decimal | None = None
    # A food of a table that a suggestion names, and not a product: it has no serving,
    # and its sheet in the table is at `url`.
    generic: bool = False
    url: str = ""


class MealOut(Schema):
    kind: str
    label: str
    items: list[MealItemOut]
    mass: Decimal
    totals: dict[str, TotalOut]
    # Whether the meal is marked eaten: behind the user, and kept by a proposal.
    eaten: bool


class NeedOut(Schema):
    name: str
    unit: str
    group: str
    group_label: str
    low: Decimal | None
    high: Decimal | None
    # What each end is, in words, with its source: "Adequate intake (anses-2021)".
    ends: list[str]
    # The share of the energy it is given as, in percent, for those that are.
    share_low: Decimal | None
    share_high: Decimal | None
    total: TotalOut
    # How much of the total the meals eaten brought; None when no meal is eaten.
    eaten: Decimal | None
    status: str
    # Whether the whole interval of the total says the same.
    certain: bool


class RatioOut(Schema):
    numerator: str
    denominator: str
    # In moles, for sodium over potassium.
    molar: bool
    low: Decimal | None
    high: Decimal | None
    end: str
    value: Decimal | None
    value_low: Decimal | None
    value_high: Decimal | None
    status: str
    certain: bool


class DayOut(Schema):
    day: date
    meals: list[MealOut]
    mass: Decimal
    totals: dict[str, TotalOut]
    # The name and unit of every nutrient the totals and the needs name.
    nutrients: dict[str, NutrientOut]
    # None without a profile to work them out from.
    needs: list[NeedOut] | None
    ratios: list[RatioOut] | None


class HelpOut(Schema):
    """What a suggested food closes of something the day misses."""

    name: str
    unit: str
    amount: Decimal
    # The share of what the day should bring that this food brings: 1 is all of it.
    share: Decimal
    # For a ratio, the nutrients that are raised to close it.
    raised: str


class SuggestedMealOut(Schema):
    kind: str
    label: str
    grams: Decimal


class SuggestedFoodOut(Schema):
    code: str
    name: str
    group: str
    url: str
    grams: Decimal
    meals: list[SuggestedMealOut]
    helps: list[HelpOut]


class SuggestionsOut(Schema):
    # "optimal", "time_limit", "failed", "no_gaps" (the inventory misses nothing),
    # "no_foods", "no_suggestion" (none is worth its price) or "nothing_to_fill"
    # (every meal is eaten).
    status: str
    # How many of the `total` needs and ratios the day misses, from the inventory
    # alone and with the suggested foods.
    missed_before: int
    missed_after: int
    total: int
    foods: list[SuggestedFoodOut]
    # The day with the suggested foods, which are items that are not products.
    day: DayOut


def suggestions_out(found: Suggestions) -> SuggestionsOut:
    """Suggestions, with the report of the day they make."""
    labels = {str(value): str(label) for value, label in Meal.Kind.choices}
    return SuggestionsOut(
        status=found.status,
        missed_before=found.missed_before,
        missed_after=found.missed_after,
        total=found.total,
        foods=[
            SuggestedFoodOut(
                code=item.food.code,
                name=item.food.name,
                group=item.food.group,
                url=item.food.url,
                grams=item.grams,
                meals=[
                    SuggestedMealOut(kind=kind, label=labels[kind], grams=grams)
                    for kind, grams in item.picks
                ],
                helps=[
                    HelpOut(
                        name=h.name,
                        unit=h.unit,
                        amount=h.amount,
                        share=h.share,
                        raised=h.raised,
                    )
                    for h in item.helps
                ],
            )
            for item in found.foods
        ],
        day=day_out(found.report),
    )


class ProposedItemOut(Schema):
    kind: str
    barcode: str
    quantity: Decimal
    unit: str


class SkippedOut(Schema):
    """A product of the inventory the day could not be made of: why, in a code."""

    barcode: str
    name: str
    reason: str


class ProposalOut(Schema):
    # "optimal", "time_limit" (the best found when the time was up), "failed",
    # "no_candidates" or "nothing_to_fill" (every meal is eaten).
    status: str
    # What the day misses, weighed; lower is closer to the needs.
    objective: float | None
    items: list[ProposedItemOut]
    skipped: list[SkippedOut]
    # The proposed day as it would be, not saved: the items proposed have no id. The
    # meals eaten are in it as they are.
    day: DayOut


def proposal_out(proposal: Proposal, report: DayReport) -> ProposalOut:
    """A proposal, with the report of the day it makes."""
    return ProposalOut(
        status=proposal.status,
        objective=proposal.objective,
        items=[
            ProposedItemOut(
                kind=item.kind,
                barcode=item.product.pk,
                quantity=item.quantity,
                unit=item.unit,
            )
            for item in proposal.items
        ],
        skipped=[
            SkippedOut(barcode=found.barcode, name=found.name, reason=found.reason)
            for found in proposal.skipped
        ],
        day=day_out(report),
    )


def day_out(report: DayReport) -> DayOut:
    """The report of a day, as the API serves it."""
    labels = {str(value): str(label) for value, label in Kind.choices}
    groups = {str(value): str(label) for value, label in Nutrient.Group.choices}
    return DayOut(
        day=report.day,
        meals=[_meal(meal) for meal in report.meals],
        mass=report.mass,
        totals=_totals(report.totals),
        nutrients={
            code: NutrientOut(name=nutrient.name, unit=nutrient.unit)
            for code, nutrient in report.catalogue.items()
        },
        needs=(
            None
            if report.needs is None
            else [_need(status, labels, groups) for status in report.needs]
        ),
        ratios=(
            None
            if report.ratios is None
            else [_ratio(status, labels) for status in report.ratios]
        ),
    )


def _totals(totals: Mapping[str, Total]) -> dict[str, TotalOut]:
    return {code: _total(total) for code, total in totals.items()}


def _total(total: Total) -> TotalOut:
    return TotalOut(
        amount=total.amount, low=total.low, high=total.high, coverage=total.coverage
    )


def _package_grams(item: MealItem | GenericItem) -> Decimal | None:
    """What the package of the product of an item weighs, in grams, if it has one."""
    if not isinstance(item, MealItem):
        return None
    product = item.product
    if product.package_quantity is None:
        return None
    return product.grams_of(product.package_quantity, product.package_unit)


def _meal(meal: MealReport) -> MealOut:
    return MealOut(
        kind=meal.kind,
        label=meal.label,
        items=[
            MealItemOut(
                id=item.id,
                barcode=item.product_id,
                name=item.product.name,
                image=(
                    item.product.image.url
                    if isinstance(item, MealItem) and item.product.image
                    else None
                ),
                quantity=item.quantity,
                unit=item.unit,
                grams=item.grams,
                serving=(
                    serving_of(item.product) if isinstance(item, MealItem) else None
                ),
                package=(
                    package_of(item.product) if isinstance(item, MealItem) else None
                ),
                package_grams=_package_grams(item),
                generic=isinstance(item, GenericItem),
                url=item.food.url if isinstance(item, GenericItem) else "",
            )
            for item in meal.items
        ],
        mass=meal.mass,
        totals=_totals(meal.totals),
        eaten=meal.eaten,
    )


def _need(
    status: NeedStatus, labels: Mapping[str, str], groups: Mapping[str, str]
) -> NeedOut:
    need = status.need
    share = need.energy_share
    return NeedOut(
        name=status.name,
        unit=status.unit,
        group=status.group,
        group_label=groups[status.group],
        low=need.low,
        high=need.high,
        ends=_ends(
            labels,
            (need.low_kind, need.low_source),
            (need.high_kind, need.high_source),
        ),
        share_low=None if share is None else share.low,
        share_high=None if share is None else share.high,
        total=_total(status.total),
        eaten=status.eaten,
        status=status.verdict.status,
        certain=status.verdict.certain,
    )


def _ratio(status: RatioStatus, labels: Mapping[str, str]) -> RatioOut:
    ratio = status.ratio
    return RatioOut(
        numerator=status.numerator,
        denominator=status.denominator,
        molar=any(weight != 1 for weight in ratio.numerator.values()),
        low=ratio.low,
        high=ratio.high,
        end=_ends(labels, (ratio.kind, ratio.source))[0],
        value=status.value,
        value_low=status.low,
        value_high=status.high,
        status=status.verdict.status,
        certain=status.verdict.certain,
    )


def _ends(labels: Mapping[str, str], *ends: tuple[str, str]) -> list[str]:
    """What the ends of a need are, each said once: "Adequate intake (anses-2021)"."""
    return list(
        dict.fromkeys(f"{labels[kind]} ({source})" for kind, source in ends if kind)
    )
