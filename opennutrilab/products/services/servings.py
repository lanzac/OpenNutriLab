"""
A product's serving, read from the text OpenFoodFacts has for it.

OpenFoodFacts keeps the serving as its contributors typed it from the label
(`serving_size`: "35.7 g (1 tranche)", "1 portion (30 g)", "250 ml"), and its own
reading of the number (`serving_quantity`), which is not read: as the ingredients
are (see label_parser), the text is read here, and strictly. A text that is not
one of these three forms is not read at all, and the serving is entered by hand:

- a quantity: "30 g", "30g", "250 ml";
- a quantity and its name in parentheses: "35.7 g (1 tranche)";
- a name and its quantity in parentheses: "1 portion (30 g)".

A name holds a letter, and no quantity or parenthesis of its own: "40 g (40 g +
125 ml de lait)" gives two quantities, and which one is the product's is not for
this code to guess.
"""

import re
from decimal import Decimal
from typing import NamedTuple

# At most two decimals, as Product.serving_quantity keeps.
NUMBER = r"(\d{1,5}(?:[.,]\d{1,2})?)"
# Every way of writing a unit, and the unit and factor it is read as. Shared with the
# reading of a package (services.packages).
UNITS: dict[str, tuple[str, int]] = {
    "g": ("g", 1),
    "gr": ("g", 1),
    "grs": ("g", 1),
    "gram": ("g", 1),
    "grams": ("g", 1),
    "gramme": ("g", 1),
    "grammes": ("g", 1),
    "ml": ("ml", 1),
    "kg": ("g", 1000),
    "cl": ("ml", 10),
    "dl": ("ml", 100),
    "l": ("ml", 1000),
}
UNIT = "(" + "|".join(sorted(UNITS, key=len, reverse=True)) + ")"
QUANTITY = rf"{NUMBER}\s*{UNIT}"

_ALONE = re.compile(rf"{QUANTITY}", re.IGNORECASE)
_NAME_AFTER = re.compile(rf"{QUANTITY}\s*\(([^()]*)\)", re.IGNORECASE)
_NAME_BEFORE = re.compile(rf"([^()]*?)\s*\({QUANTITY}\)", re.IGNORECASE)
# A quantity anywhere in a name, which makes it no name.
_ANY_QUANTITY = re.compile(rf"\d\s*{UNIT}\b", re.IGNORECASE)


class Serving(NamedTuple):
    # More than 0, in `unit`.
    quantity: Decimal
    # A value of Product.ServingUnit: "g" or "ml".
    unit: str
    # What the label calls it ("1 tranche"), or "".
    name: str = ""


def read_serving(text: str | None) -> Serving | None:
    """The serving `text` gives, or None when it is not one of the three forms."""
    text = (text or "").strip()
    if match := _ALONE.fullmatch(text):
        return _serving(*match.groups())
    if match := _NAME_AFTER.fullmatch(text):
        number, unit, name = match.groups()
        return _serving(number, unit, name)
    if match := _NAME_BEFORE.fullmatch(text):
        name, number, unit = match.groups()
        return _serving(number, unit, name)
    return None


def _serving(number: str, unit: str, name: str = "") -> Serving | None:
    stored_unit, factor = UNITS[unit.lower()]
    quantity = Decimal(number.replace(",", ".")) * factor
    if quantity <= 0:
        return None
    name = name.strip().rstrip(".").strip()
    if name and (
        not any(c.isalpha() for c in name) or _ANY_QUANTITY.search(name) is not None
    ):
        return None
    return Serving(quantity=quantity, unit=stored_unit, name=name)
