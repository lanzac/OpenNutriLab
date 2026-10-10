"""
The only code that writes a user's meals.

A meal is made of products from the user's inventory. They are counted in servings
of the product, which needs a serving (see Product.serving_quantity), or in grams.
"""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from django.db import IntegrityError
from django.db import transaction

from opennutrilab.meals.models import Meal
from opennutrilab.meals.models import MealItem
from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Product
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
            return MealItem.objects.create(
                meal=meal, product=product, quantity=quantity, unit=unit
            )
    except IntegrityError as e:
        raise AlreadyInMealError(product.pk) from e


def set_eaten(user: User, day: date, kind: str, *, eaten: bool) -> Meal:
    """Mark a meal of a day as eaten, or as not eaten. An empty meal can be: skipped."""
    meal, _created = Meal.objects.update_or_create(
        user=user, date=day, kind=kind, defaults={"eaten": eaten}
    )
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
    item.quantity = quantity
    item.unit = unit
    item.save(update_fields=["quantity", "unit"])
    return item


def remove_item(item: MealItem) -> None:
    """Take a product out of a meal. A meal left empty is left, and costs nothing."""
    item.delete()


def _check_unit(product: Product, unit: str) -> None:
    if unit == MealItem.Unit.SERVING and product.serving_quantity is None:
        raise NoServingError(product.pk)
