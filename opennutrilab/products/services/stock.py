"""
How much of a product a user has at hand, as they counted it (InventoryItem.stock_*).

A stock is counted in grams, in millilitres, or in servings of the product when its
label names them (a pot, a slice, a bottle): those are whole things, which a meal
takes whole, so that 4 pots are 3 after a serving, and 3 again after half of one. A
count is what the user has now: setting one is the truth from then on, whatever was
eaten before. The meals that are eaten take from it, and give back when they are not
eaten any more (see meals.services.meal_services). A stock that was never counted is
not limited: it takes nothing and gives nothing.
"""

import math
import re
from decimal import Decimal

from django.utils import timezone

from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Product

ZERO = Decimal(0)
# An amount of servings that is a hair over a whole number is that whole number: 3
# servings of 35.7 g are 107.1 g, and 107.1 g are 3 servings, not 3.0000001.
TOLERANCE = Decimal("0.001")

# What a label calls a serving, with or without the "one" of a thing: "1 pot", "un
# sachet", "portion".
_NAME = re.compile(r"^\s*(?P<one>(?:1|un|une)\s+)?(?P<noun>\S.*?)\s*$", re.IGNORECASE)
# What it calls it when it is a measure and not a thing to count: "1 portion", "1 cs".
_MEASURE = re.compile(
    r"^(?:portions?|parts?|rations?|servings?|doses?|cuill\w*|c\.|càs|càc|cs|cc|"
    r"tbsp|tsp|verres?|pincées?|gouttes?)(?:\s|\.|$)",
    re.IGNORECASE,
)
# How far a package may be from a whole number of servings, as a share of it.
_WHOLE = Decimal("0.02")


class InvalidStockError(ValueError):
    """A stock below nothing, in an unknown unit, or in servings that are not whole."""


def counting_noun(product: Product) -> str | None:
    """
    What the product's serving is called when it is a thing that is counted ("pot",
    "tranche", "bouteille"), or None: a serving that has no name, or says several
    things ("2 biscuits"), is counted in grams.

    The label says "1 pot" of a thing. A name that is a measure ("1 portion", "1 cs",
    "part"), or has no "1" ("pot"), is a thing only where the product says so itself:
    its name gives how many of them the package holds ("8 portions panées"), which
    is what keeps a pasta served in "1 portion" of 80 g counted in grams.
    """
    if product.serving_quantity is None:
        return None
    found = _NAME.match(product.serving_name or "")
    if found is None:
        return None
    noun = found["noun"]
    if not any(c.isalpha() for c in noun) or noun[0].isdigit():
        return None
    if found["one"] and not _MEASURE.match(noun):
        return noun
    return noun if _counted_in_name(product, noun) else None


def _counted_in_name(product: Product, noun: str) -> bool:
    """
    Whether the name of the product says how many servings its package holds, in the
    noun of the serving: "8 portions panées de Colin" for 400 g in servings of 50 g.
    """
    package, serving = product.package_quantity, product.serving_quantity
    if not package or not serving or product.package_unit != product.serving_unit:
        return False
    ratio = package / serving
    whole = round(ratio)
    if whole < 1 or abs(ratio - whole) > _WHOLE * whole:
        return False
    word = re.escape(noun.split()[0])
    return any(
        int(found[1]) == whole
        for found in re.finditer(
            rf"(?<!\d)(\d+)\s+{word}[sx]?\b", product.name, re.IGNORECASE
        )
    )


def default_unit(product: Product) -> str:
    """
    The unit a stock is counted in until the user says: servings for a product whose
    label names its serving as a thing, else the package's unit.
    """
    if counting_noun(product) is not None:
        return InventoryItem.StockUnit.SERVING.value
    return product.package_unit or InventoryItem.StockUnit.GRAM.value


def unit_of(item: InventoryItem) -> str:
    """The unit the stock is counted in, or would be."""
    return item.stock_unit or default_unit(item.product)


def set_stock(
    item: InventoryItem, quantity: Decimal | None, unit: str | None = None
) -> InventoryItem:
    """
    Count the stock of an item: how much there is now, in `unit` (the unit it was
    counted in, or the one it would be). None says it is not counted, which leaves
    nothing to limit what a day uses. Servings are whole, and the product has one.
    """
    if quantity is None:
        item.stock_quantity = None
        item.stock_unit = ""
        item.counted_at = None
    else:
        unit = unit or unit_of(item)
        if quantity < 0 or unit not in InventoryItem.StockUnit.values:
            raise InvalidStockError(quantity, unit)
        if unit == InventoryItem.StockUnit.SERVING.value and (
            item.product.serving_quantity is None or quantity % 1 != 0
        ):
            raise InvalidStockError(quantity, unit)
        item.stock_quantity = quantity.quantize(Decimal("0.01"))
        item.stock_unit = unit
        item.counted_at = timezone.now()
    item.save(update_fields=["stock_quantity", "stock_unit", "counted_at"])
    return item


def grams_in_stock(item: InventoryItem) -> Decimal | None:
    """
    What the stock weighs, in grams (a volume weighs what the density says, servings
    what a serving does), or None when it is not counted, or is counted in servings of
    a product that has none any more.
    """
    if item.stock_quantity is None:
        return None
    product = item.product
    if item.stock_unit == InventoryItem.StockUnit.SERVING.value:
        if product.serving_quantity is None:
            return None
        return item.stock_quantity * product.grams_of(
            product.serving_quantity, product.serving_unit
        )
    return product.grams_of(item.stock_quantity, item.stock_unit)


def needed_from_stock(
    item: InventoryItem, grams: Decimal | None, servings: Decimal | None
) -> Decimal | None:
    """
    What an amount of the product takes from the stock, in the unit it is counted in:
    its mass, its volume, or the whole servings it needs (half a serving takes one,
    an opened pot being a pot gone). None when the amount cannot be told in that unit
    (no mass, or no serving).
    """
    if item.stock_unit == InventoryItem.StockUnit.SERVING.value:
        if servings is None:
            return None
        return Decimal(max(math.ceil(servings - TOLERANCE), 0))
    if grams is None:
        return None
    if item.stock_unit == InventoryItem.StockUnit.MILLILITRE.value:
        return item.product.quantity_of(grams, item.stock_unit)
    return grams


def take_from_stock(item: InventoryItem, amount: Decimal) -> Decimal:
    """
    Take `amount`, in the unit the stock is counted in, as far as it goes: the stock
    stops at nothing, not below. Returns what was taken, which is nothing for a stock
    that is not counted. The caller holds the row (select_for_update).
    """
    if item.stock_quantity is None:
        return ZERO
    taken = min(amount, item.stock_quantity)
    if taken <= 0:
        return ZERO
    item.stock_quantity -= taken
    item.save(update_fields=["stock_quantity"])
    return taken


def give_back_to_stock(item: InventoryItem, amount: Decimal) -> None:
    """Put `amount`, in the unit the stock is counted in, back, if it is counted."""
    if item.stock_quantity is None:
        return
    item.stock_quantity += amount
    item.save(update_fields=["stock_quantity"])
