"""
What a user allows of the products of their inventory when a day is proposed: the
meals a product may be in, and the most of it a day. The optimiser reads them
(services.optimiser); a product with none is in any meal, up to the default most.
"""

from decimal import Decimal
from typing import NamedTuple

from opennutrilab.meals.models import ItemLimits
from opennutrilab.meals.models import Meal
from opennutrilab.meals.models import MealItem
from opennutrilab.meals.services.meal_services import NoServingError
from opennutrilab.meals.services.meal_services import NotInInventoryError
from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Product
from opennutrilab.users.models import User


class InvalidMealError(ValueError):
    """A kind of meal that is none of Meal.Kind."""


class Limits(NamedTuple):
    # Empty, any meal.
    meals: tuple[str, ...]
    max_quantity: Decimal | None
    # "serving" or "g", "" with no most.
    max_unit: str


NO_LIMITS = Limits((), None, "")


def limits_of(user: User) -> dict[str, Limits]:
    """The limits a user has set, by barcode, for the products that have some."""
    return {
        found.inventory_item.product_id: Limits(
            tuple(found.meals), found.max_quantity, found.max_unit
        )
        for found in ItemLimits.objects.filter(
            inventory_item__user=user
        ).select_related("inventory_item")
    }


def set_limits(
    user: User,
    product: Product,
    meals: list[str],
    max_quantity: Decimal | None,
    max_unit: str | None,
) -> Limits:
    """
    Set what a user allows of a product of their inventory. Allowing every meal
    and no most is having no limits, which clears them.
    """
    item = InventoryItem.objects.filter(user=user, product=product).first()
    if item is None:
        raise NotInInventoryError(product.pk)
    kinds = {str(value) for value in Meal.Kind.values}
    unknown = sorted(set(meals) - kinds)
    if unknown:
        msg = f"Unknown meals: {', '.join(unknown)}"
        raise InvalidMealError(msg)
    chosen = tuple(kind for kind in Meal.Kind.values if kind in set(meals))
    # Every meal is any meal.
    if len(chosen) == len(kinds):
        chosen = ()
    if max_quantity is None:
        max_unit = ""
    else:
        # As the database keeps it, so that what is returned is what is read.
        max_quantity = max_quantity.quantize(Decimal("0.01"))
        if max_unit == MealItem.Unit.SERVING and product.serving_quantity is None:
            raise NoServingError(product.pk)
    if not chosen and max_quantity is None:
        ItemLimits.objects.filter(inventory_item=item).delete()
        return NO_LIMITS
    ItemLimits.objects.update_or_create(
        inventory_item=item,
        defaults={
            "meals": list(chosen),
            "max_quantity": max_quantity,
            "max_unit": max_unit or "",
        },
    )
    return Limits(chosen, max_quantity, max_unit or "")
