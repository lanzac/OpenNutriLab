"""What the meals API serves and takes."""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Literal

from ninja import Field
from ninja import Schema

from opennutrilab.meals.services.day_report import DayReport
from opennutrilab.meals.services.day_report import MealReport
from opennutrilab.meals.services.day_report import NeedStatus
from opennutrilab.meals.services.day_report import RatioStatus
from opennutrilab.meals.services.day_report import Total
from opennutrilab.meals.services.needs import Kind
from opennutrilab.products.api.schemas.outbound import ServingOut
from opennutrilab.products.api.schemas.outbound import serving_of
from opennutrilab.products.models import Nutrient


class ItemIn(Schema):
    barcode: str
    quantity: Decimal = Field(gt=0, max_digits=7, decimal_places=2)
    unit: Literal["serving", "g"] = "serving"


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


class LimitsOut(Schema):
    barcode: str
    meals: list[str]
    max_quantity: Decimal | None
    max_unit: str


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
    quantity: Decimal
    unit: str
    # None for servings of a product that has no serving any more.
    grams: Decimal | None
    serving: ServingOut | None


class MealOut(Schema):
    kind: str
    label: str
    items: list[MealItemOut]
    mass: Decimal
    totals: dict[str, TotalOut]


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


def _meal(meal: MealReport) -> MealOut:
    return MealOut(
        kind=meal.kind,
        label=meal.label,
        items=[
            MealItemOut(
                id=item.id,
                barcode=item.product_id,
                name=item.product.name,
                quantity=item.quantity,
                unit=item.unit,
                grams=item.grams,
                serving=serving_of(item.product),
            )
            for item in meal.items
        ],
        mass=meal.mass,
        totals=_totals(meal.totals),
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
