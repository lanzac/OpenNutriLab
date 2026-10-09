"""
A product's package, read from the quantity OpenFoodFacts has for it.

OpenFoodFacts keeps the quantity as its contributors typed it from the packaging
(`quantity`: "500 g", "6 x 125 g", "1,5 L" with the sign of an estimated quantity),
and its own reading of it
(`product_quantity`), which is not read: as for the serving (see services.servings)
the text is read here, and strictly. A text that is not one of these forms is not
read at all, and the quantity is entered by hand:

- a quantity: "500 g", "500g", "1,5 kg", "75 cl";
- a number of packs of a quantity: "6 x 125 g", "6x125g", "6 * 125 g": the total;
- either of them, with the sign of an estimated quantity (an "e", or U+212E) and/or
  a note in parentheses after it: "250 g e (3 x 80 g)", "135 g (3 portions)", which
  are not read, the first quantity being the package's.

A mass is kept in grams and a volume in millilitres. A volume counts as the same
number of grams where the amounts of a day are worked out, as for a serving.
"""

import re
from decimal import Decimal
from typing import NamedTuple

from opennutrilab.products.services.servings import QUANTITY
from opennutrilab.products.services.servings import UNITS

# The number of packs (x, the multiplication sign U+00D7 or *), then the quantity of
# one.
_COUNT = r"(?:(\d{1,3})\s*[x\u00d7*]\s*)?"
# The sign of an estimated quantity ("e", or U+212E), which may stand on either side
# of a note.
_ESTIMATED = r"\s*[e\u212e]?\s*"
_PACKAGE = re.compile(
    rf"{_COUNT}{QUANTITY}{_ESTIMATED}(?:\([^()]*\))?{_ESTIMATED}", re.IGNORECASE
)
# What a Product's package quantity can hold: 9 digits, 2 of them decimals.
MOST = Decimal("9999999.99")


class Package(NamedTuple):
    # More than 0, in `unit`.
    quantity: Decimal
    # A value of Product.ServingUnit: "g" or "ml".
    unit: str


def read_package(text: str | None) -> Package | None:
    """The package `text` gives, or None when it is not one of the forms."""
    match = _PACKAGE.fullmatch((text or "").strip())
    if match is None:
        return None
    count, number, unit = match.groups()
    stored_unit, factor = UNITS[unit.lower()]
    quantity = Decimal(number.replace(",", ".")) * factor * int(count or 1)
    if not 0 < quantity <= MOST:
        return None
    return Package(quantity=quantity, unit=stored_unit)
