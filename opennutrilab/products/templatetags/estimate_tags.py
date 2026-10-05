"""Filters for the table of a product's estimate (templates/products/components)."""

from collections.abc import Iterator
from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from django import template
from django.utils.formats import number_format

from opennutrilab.products.api.schemas.outbound import IngredientEstimateOut

register = template.Library()

# An estimate is not precise to more than that, whatever digits the solver gives.
SIGNIFICANT_DIGITS = 3


class _Span(Protocol):
    low: Decimal
    high: Decimal | None


@register.filter
def figure(value: Decimal | None) -> str:
    """
    An estimated figure to three significant digits, in the language served.

    The integer part is never rounded (1416.07 is 1416), and a figure that is a
    small fraction keeps its digits (0.012174 is 0.0122), which a fixed number of
    decimals would lose: amounts go from kJ to fractions of a µg.
    """
    if value is None:
        return ""
    if value == 0:
        return "0"
    places = max(0, SIGNIFICANT_DIGITS - 1 - value.adjusted())
    return number_format(round(value, places).normalize(), use_l10n=True)


@register.filter
def plain(value: Decimal | None) -> str:
    """
    A figure as it was written, without the zeros a decimal field pads it with:
    9.4000 is 9.4 and 1532.0000 is 1532.
    """
    if value is None:
        return ""
    return number_format(value.normalize(), use_l10n=True)


@register.filter
def span(value: _Span | None) -> str:
    """A range as low to high, or "≥ low" when no upper end is known."""
    if value is None:
        return ""
    if value.high is None:
        return f"≥ {figure(value.low)}"
    return f"{figure(value.low)} \u2013 {figure(value.high)}"


@register.filter
def walk(
    ingredients: Sequence[IngredientEstimateOut],
) -> Iterator[tuple[int, IngredientEstimateOut]]:
    """The ingredients tree as (depth, ingredient) in the order of the label."""

    def visit(
        level: Sequence[IngredientEstimateOut], depth: int
    ) -> Iterator[tuple[int, IngredientEstimateOut]]:
        for ingredient in level:
            yield depth, ingredient
            yield from visit(ingredient.sub_ingredients, depth + 1)

    return visit(ingredients, 0)
