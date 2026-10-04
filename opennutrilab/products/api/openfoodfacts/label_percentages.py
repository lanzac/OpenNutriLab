"""
Percentages as the label declares them.

OpenFoodFacts' `percent` is the share the label gives an ingredient, but not
always as written: when the label's percentages do not add up to 100, OFF
rescales them. The recorded muesli says 33 %, 26 %, 25 %... (99.4 % in all) and
OFF returns 33.199, 26.157, 25.151... Nothing in the response tells a rescaled
value from a raw one, and a rescaled value is an OFF computation, which this
project does not use.

The label's own text, which OFF returns too, is the reference. An OFF
percentage is kept only if it is a number that text declares: as it stands, or
as the number OFF rescaled it from. Anything else is left out.
"""

import re
from collections.abc import Sequence
from decimal import Decimal

# A number followed by %, with a comma or a point as its decimal separator and
# possibly a space (a non-breaking one in French typography) before the sign.
# The two lookbehinds keep "1,4 %" from also giving 4. Two decimals at most:
# that is what Ingredient.percentage stores.
_PERCENT = re.compile(r"(?<!\d)(?<!\d[.,])(\d+(?:[.,]\d{1,2})?)\s*%")

# OFF's percentages are floats of about fifteen digits; the label's have two at
# most, so values that are the same number differ by far less than this.
_TOLERANCE = 1e-6


def percentages_in(text: str) -> tuple[Decimal, ...]:
    """The distinct numbers `text` gives a percentage for, ascending."""
    return tuple(
        sorted({Decimal(found.replace(",", ".")) for found in _PERCENT.findall(text)})
    )


def declared_percentages(
    values: Sequence[float | None], numbers: Sequence[Decimal]
) -> list[Decimal | None]:
    """
    What the label declares for each of `values`, in the same order.

    `values` are OFF's `percent` for sibling ingredients (None where OFF gives
    none) and `numbers` what the label's text declares (see percentages_in).
    The result holds the label's number, or None where it cannot be told: a
    value outside 0-100 or one that the label does not back.
    """
    declared: list[Decimal | None] = [None] * len(values)
    unmatched: list[tuple[int, float]] = []
    for index, value in enumerate(values):
        if value is None or not 0 <= value <= 100:  # noqa: PLR2004
            continue
        number = _declared(value, numbers)
        if number is None:
            unmatched.append((index, value))
        else:
            declared[index] = number
    origins = _rescaled_from([value for _, value in unmatched], numbers)
    if origins is not None:
        for (index, _), origin in zip(unmatched, origins, strict=True):
            declared[index] = origin
    return declared


def _declared(value: float, numbers: Sequence[Decimal]) -> Decimal | None:
    return next((n for n in numbers if abs(float(n) - value) < _TOLERANCE), None)


def _rescaled_from(
    values: Sequence[float], numbers: Sequence[Decimal]
) -> list[Decimal] | None:
    """
    The label numbers OFF rescaled `values` from, if one factor explains them.

    That is the case when a single factor maps every value onto a number the
    label declares. Any one value fits some factor, so at least two are needed,
    and the factor has to be the only one that works: with several, which of
    them OFF applied cannot be told and nothing is recovered.
    """
    if len(values) < 2 or values[0] == 0:  # noqa: PLR2004
        return None
    solutions: list[list[Decimal]] = []
    for anchor in numbers:
        if anchor == 0:
            continue
        factor = values[0] / float(anchor)
        origins = [_declared(value / factor, numbers) for value in values]
        found = [origin for origin in origins if origin is not None]
        if len(found) == len(values):
            solutions.append(found)
    return solutions[0] if len(solutions) == 1 else None
