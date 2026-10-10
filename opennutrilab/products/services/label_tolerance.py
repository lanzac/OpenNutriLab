"""
What a figure on a nutrition label can stand for.

A label does not say what a food holds to the last digit, and two things make the
true amount differ from the figure, both set by the European Commission's guidance
document on the tolerances for nutrient values declared on a label (December 2012,
for Regulation (EU) No 1169/2011, "no formal legal status" as it says itself):

- the rounding it is written with (Table 4): 33 is 32.5 to 33.5 (see
  rounding_margin), and a 0 stands for "less than 0.5 g" for fat, carbohydrates,
  sugars, fibre and proteins, "less than 0.1 g" for saturates, mono- and
  polyunsaturates, and so on. Those are the `rounded` ends;
- the tolerance (Table 1, which includes the uncertainty of measurement) around
  that: what an analysis may find against the declared figure, because a food is
  never exactly what is labelled (natural and seasonal variation, production,
  storage). It is applied to the ends of the rounding, as the guidance does in its
  example (8.5 g of sugars is 8.45 to 8.54, and 6.45 to 10.54 with the tolerance).
  Those are the `tolerated` ends.

The tolerance is wide on purpose, being a limit for control and not a spread, so
it is never what the shares are worked out with unless the rounding alone cannot
agree with the ingredients (see percentage_estimation). Energy has none in the
guidance, being worked out from the nutrients, and nor does a nutrient the
guidance does not name: only the rounding is allowed for them.
"""

from decimal import Decimal
from typing import NamedTuple

from opennutrilab.products.services.reference_composition import rounding_margin

Ends = tuple[Decimal, Decimal]


class Reading(NamedTuple):
    """The ends a label's figure can stand for: rounding alone, and with tolerance."""

    rounded: Ends
    tolerated: Ends


class Tier(NamedTuple):
    """
    The tolerance for a figure below `limit` (None: any), or up to it when
    `inclusive`: an `absolute` amount plus a `relative` share of the figure.
    """

    limit: Decimal | None
    absolute: Decimal
    relative: Decimal
    inclusive: bool = False

    def holds(self, amount: Decimal) -> bool:
        if self.limit is None:
            return True
        return amount < self.limit or (self.inclusive and amount == self.limit)


D = Decimal
_NONE = D(0)

# Table 4: the amount, per 100 g or ml, that a label's 0 stands for at most, by
# nutrient, in the unit the catalogue gives it in.
ZERO_STANDS_FOR: dict[str, Decimal] = {
    "fat": D("0.5"),
    "carbohydrates": D("0.5"),
    "sugars": D("0.5"),
    "fiber": D("0.5"),
    "proteins": D("0.5"),
    "saturated_fat": D("0.1"),
    "monounsaturated_fat": D("0.1"),
    "polyunsaturated_fat": D("0.1"),
    "salt": D("0.0125"),
    "sodium": D(5),  # mg
}

# Table 1: below 10 g an absolute amount, up to 40 g a fifth of the figure, above
# it an absolute amount again; the limits are those of the declared figure.
_MACRONUTRIENT = (
    Tier(D(10), D(2), _NONE),
    Tier(D(40), _NONE, D("0.2"), inclusive=True),
    Tier(None, D(8), _NONE),
)
_FAT = (Tier(D(10), D("1.5"), _NONE), *_MACRONUTRIENT[1:])
_FATTY_ACIDS = (Tier(D(4), D("0.8"), _NONE), Tier(None, _NONE, D("0.2")))
_TIERS: dict[str, tuple[Tier, ...]] = {
    "proteins": _MACRONUTRIENT,
    "carbohydrates": _MACRONUTRIENT,
    "sugars": _MACRONUTRIENT,
    "fiber": _MACRONUTRIENT,
    "fat": _FAT,
    "saturated_fat": _FATTY_ACIDS,
    "monounsaturated_fat": _FATTY_ACIDS,
    "polyunsaturated_fat": _FATTY_ACIDS,
    "salt": (Tier(D("1.25"), D("0.375"), _NONE), Tier(None, _NONE, D("0.2"))),
    "sodium": (Tier(D(500), D(150), _NONE), Tier(None, _NONE, D("0.2"))),  # mg
}
# Vitamins and minerals: a share of the figure, less below than above.
_BY_GROUP: dict[str, tuple[Decimal, Decimal]] = {
    "vitamin": (D("0.35"), D("0.5")),
    "mineral": (D("0.35"), D("0.45")),
}


def label_reading(code: str, group: str, amount: Decimal) -> Reading:
    """
    The ends a figure of a label stands for, by the code of its nutrient and the
    group the catalogue puts it in.
    """
    margin = rounding_margin(amount)
    low, high = max(D(0), amount - margin), amount + margin
    if amount == 0:
        high = ZERO_STANDS_FOR.get(code, _NONE)
    below, above = _tolerance(code, group, amount)
    return Reading((low, high), (max(D(0), low - below), high + above))


def _tolerance(code: str, group: str, amount: Decimal) -> Ends:
    """How far below and above a declared figure an analysis may find the amount."""
    for tier in _TIERS.get(code, ()):
        if tier.holds(amount):
            width = tier.absolute + tier.relative * amount
            return width, width
    if shares := _BY_GROUP.get(group):
        return shares[0] * amount, shares[1] * amount
    return _NONE, _NONE
