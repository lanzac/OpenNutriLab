"""
The only code that writes a user's meals.

A meal is made of products from the user's inventory. They are counted in servings
of the product, which needs a serving (see Product.serving_quantity), or in grams.

A meal that is eaten takes what is in it from the stock of the products, where the
user counted it (see products.services.stock), in the unit they counted it in: the
mass in grams, the volume in millilitres, the whole servings in servings. It gives it
back when the meal is not eaten any more, or when an item is changed or taken out.
What an item took is kept (StockTaken) to give back exactly that; an item with
nothing kept, because the stock was not counted when it was eaten, or has been counted
since, neither takes nor gives.
"""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from django.db import IntegrityError
from django.db import transaction

from opennutrilab.meals.models import Meal
from opennutrilab.meals.models import MealItem
from opennutrilab.meals.models import StockTaken
from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Product
from opennutrilab.products.services import stock
from opennutrilab.users.models import User


class NotInInventoryError(Exception):
    """The product is not in the user's inventory."""


class NoServingError(Exception):
    """Servings were asked of a product that has no serving."""


class AlreadyInMealError(Exception):
    """The product is in the meal already: change its quantity."""


class MealEatenError(Exception):
    """Something was put in place of a meal that is eaten, which is not to change."""


def add_item(  # noqa: PLR0913
    user: User,
    day: date,
    kind: str,
    product: Product,
    quantity: Decimal,
    unit: str = MealItem.Unit.SERVING,
) -> MealItem:
    """Put a product of the user's inventory in a meal of a day."""
    if not InventoryItem.objects.filter(user=user, product=product).exists():
        raise NotInInventoryError(product.pk)
    _check_unit(product, unit)
    try:
        with transaction.atomic():
            meal, _created = Meal.objects.get_or_create(user=user, date=day, kind=kind)
            item = MealItem.objects.create(
                meal=meal, product=product, quantity=quantity, unit=unit
            )
            if meal.eaten:
                _take_from_stock(user.pk, item)
            return item
    except IntegrityError as e:
        raise AlreadyInMealError(product.pk) from e


def set_eaten(user: User, day: date, kind: str, *, eaten: bool) -> Meal:
    """
    Mark a meal of a day as eaten, or as not eaten. An empty meal can be: skipped.
    What is in a meal that becomes eaten is taken from the stock, and given back when it
    becomes not eaten.
    """
    with transaction.atomic():
        meal, _created = Meal.objects.get_or_create(user=user, date=day, kind=kind)
        # Held, so that two requests for the same change do not take twice.
        meal = Meal.objects.select_for_update().get(pk=meal.pk)
        if meal.eaten != eaten:
            meal.eaten = eaten
            meal.save(update_fields=["eaten"])
            for item in meal.items.select_related("product"):
                if eaten:
                    _take_from_stock(user.pk, item)
                else:
                    _give_back_to_stock(item)
    return meal


def replace_day(
    user: User, day: date, items: Iterable[tuple[str, Product, Decimal, str]]
) -> None:
    """
    Make the meals of a day that are not eaten what `items` say, (kind, product,
    quantity, unit) each, in place of what they were; the meals that are eaten stay as
    they are, and nothing can be put in them. All or nothing: an item that cannot be
    put in a meal leaves the day as it was.
    """
    with transaction.atomic():
        eaten = set(
            Meal.objects.filter(user=user, date=day, eaten=True).values_list(
                "kind", flat=True
            )
        )
        Meal.objects.filter(user=user, date=day, eaten=False).delete()
        for kind, product, quantity, unit in items:
            if kind in eaten:
                raise MealEatenError(kind)
            add_item(user, day, kind, product, quantity, unit)


def change_item(item: MealItem, quantity: Decimal, unit: str) -> MealItem:
    """Change how much of a product is in a meal."""
    _check_unit(item.product, unit)
    with transaction.atomic():
        item.quantity = quantity
        item.unit = unit
        item.save(update_fields=["quantity", "unit"])
        if item.meal.eaten:
            _retake_from_stock(item)
    return item


def remove_item(item: MealItem) -> None:
    """Take a product out of a meal. A meal left empty is left, and costs nothing."""
    with transaction.atomic():
        if item.meal.eaten:
            _give_back_to_stock(item)
        item.delete()


def _check_unit(product: Product, unit: str) -> None:
    if unit == MealItem.Unit.SERVING and product.serving_quantity is None:
        raise NoServingError(product.pk)


def _locked_stock(user_id: int, product_id: str) -> InventoryItem | None:
    """The stock of a user's product, held until the end of the transaction."""
    return (
        InventoryItem.objects.select_for_update(of=("self",))
        .select_related("product")
        .filter(user_id=user_id, product_id=product_id)
        .first()
    )


def _kept(item: MealItem) -> tuple[StockTaken, InventoryItem] | None:
    """
    What the item took from the stock and that stock (held), or None when it took
    nothing that the stock still holds. A stock counted since is the truth as of then,
    with what was eaten before it: what the item took is not in it to give back.
    """
    taken = StockTaken.objects.filter(meal_item=item).first()
    if taken is None:
        return None
    held = (
        InventoryItem.objects.select_for_update(of=("self",))
        .select_related("product")
        .get(pk=taken.inventory_item_id)
    )
    if held.counted_at is None or taken.at < held.counted_at:
        taken.delete()
        return None
    return taken, held


def _needed(held: InventoryItem, item: MealItem) -> Decimal:
    """What the item takes from the stock, in the unit the stock is counted in."""
    return stock.needed_from_stock(held, item.grams, item.servings) or Decimal(0)


def _take_from_stock(user_id: int, item: MealItem) -> None:
    """The item has just been eaten: take what it needs from the stock, if counted."""
    held = _locked_stock(user_id, item.product_id)
    if held is None:
        return
    taken = stock.take_from_stock(held, _needed(held, item))
    if taken > 0:
        StockTaken.objects.update_or_create(
            meal_item=item, defaults={"inventory_item": held, "quantity": taken}
        )


def _give_back_to_stock(item: MealItem) -> None:
    """The item is not eaten any more: give back what it took."""
    kept = _kept(item)
    if kept is not None:
        taken, held = kept
        stock.give_back_to_stock(held, taken.quantity)
        taken.delete()


def _retake_from_stock(item: MealItem) -> None:
    """An item that is eaten changed: take the more, or give back the less."""
    kept = _kept(item)
    if kept is None:
        return
    taken, held = kept
    wanted = _needed(held, item)
    if wanted > taken.quantity:
        taken.quantity += stock.take_from_stock(held, wanted - taken.quantity)
    elif wanted < taken.quantity:
        stock.give_back_to_stock(held, taken.quantity - wanted)
        taken.quantity = wanted
    if taken.quantity > 0:
        taken.save(update_fields=["quantity", "at"])
    else:
        taken.delete()
