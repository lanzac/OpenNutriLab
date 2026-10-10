"""
What a user allows of the products of their inventory when a day is proposed: the
meals a product may be in, and the most of it a day, or that all of its package is to
be used, or that it is left out. The optimiser reads them (services.optimiser); a
product with none is in any meal, up to the default most.
"""

from decimal import Decimal
from typing import NamedTuple

from django.db import transaction

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


class NoPackageError(ValueError):
    """The whole package was asked for of a product that has no total quantity."""


class Limits(NamedTuple):
    # Empty, any meal.
    meals: tuple[str, ...]
    max_quantity: Decimal | None
    # "serving" or "g", "" with no most.
    max_unit: str
    # All of the package in the day, which is then the quantity: there is no most.
    use_all: bool = False
    # Off, the product is left out of the days proposed.
    enabled: bool = True


NO_LIMITS = Limits((), None, "")


def limits_of(user: User) -> dict[str, Limits]:
    """The limits a user has set, by barcode, for the products that have some."""
    return {
        found.inventory_item.product_id: Limits(
            tuple(found.meals),
            found.max_quantity,
            found.max_unit,
            found.use_all,
            found.enabled,
        )
        for found in ItemLimits.objects.filter(
            inventory_item__user=user
        ).select_related("inventory_item")
    }


def set_limits(  # noqa: PLR0913
    user: User,
    product: Product,
    meals: list[str],
    max_quantity: Decimal | None,
    max_unit: str | None,
    *,
    use_all: bool = False,
    enabled: bool = True,
) -> Limits:
    """
    Set what a user allows of a product of their inventory. Allowing every meal
    and no most is having no limits, which clears them. Asking for all of the package
    takes the place of a most, and needs the product to have a total quantity. A
    product that is left out keeps the rest, for when it is not any more.
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
    if use_all:
        if product.package_quantity is None:
            raise NoPackageError(product.pk)
        max_quantity = None
    if max_quantity is None:
        max_unit = ""
    else:
        # As the database keeps it, so that what is returned is what is read.
        max_quantity = max_quantity.quantize(Decimal("0.01"))
        if max_unit == MealItem.Unit.SERVING and product.serving_quantity is None:
            raise NoServingError(product.pk)
    if enabled and not chosen and max_quantity is None and not use_all:
        ItemLimits.objects.filter(inventory_item=item).delete()
        return NO_LIMITS
    ItemLimits.objects.update_or_create(
        inventory_item=item,
        defaults={
            "meals": list(chosen),
            "max_quantity": max_quantity,
            "max_unit": max_unit or "",
            "use_all": use_all,
            "enabled": enabled,
        },
    )
    return Limits(chosen, max_quantity, max_unit or "", use_all, enabled)


@transaction.atomic
def set_all_enabled(user: User, *, enabled: bool) -> dict[str, Limits]:
    """
    Leave every product of the user's inventory out of the days proposed, or put them
    all back in; what else was set of each is kept. Returns the limits that are left
    (the products left out have some, being left out).
    """
    held = ItemLimits.objects.filter(inventory_item__user=user)
    if enabled:
        held.update(enabled=True)
        # A row that holds nothing else is having no limits.
        held.filter(meals=[], max_quantity__isnull=True, use_all=False).delete()
    else:
        ItemLimits.objects.bulk_create(
            ItemLimits(inventory_item=item)
            for item in InventoryItem.objects.filter(user=user, limits__isnull=True)
        )
        held.update(enabled=False)
    return limits_of(user)
