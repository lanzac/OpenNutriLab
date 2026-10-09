"""
Each user's inventory: the products they have at hand, which their meals are
made of. The products themselves are a catalogue every user shares.
"""

from django.db.models import QuerySet

from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Product
from opennutrilab.users.models import User


def add_to_inventory(user: User, product: Product) -> InventoryItem:
    """Put a product in a user's inventory, where it may already be."""
    item, _created = InventoryItem.objects.get_or_create(user=user, product=product)
    return item


def remove_from_inventory(user: User, product: Product) -> None:
    """Take a product out of a user's inventory, where it may not be."""
    InventoryItem.objects.filter(user=user, product=product).delete()


def inventory_of(user: User) -> QuerySet[InventoryItem]:
    """A user's inventory, with its products, in the order they were added."""
    return InventoryItem.objects.filter(user=user).select_related("product")
