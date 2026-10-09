"""
The food groups OpenFoodFacts files a product under, named in the language served.

A product keeps the two levels it came with (`Product.group_level_1` and
`group_level_2`, OpenFoodFacts' `pnns_groups_1` and `pnns_groups_2`): English
words that are not shown as they are. The lists below are OpenFoodFacts'
taxonomy of the PNNS (the French national nutrition programme); a group that is
not in them is shown as it was stored.
"""

from django.utils.translation import gettext as _


def pnns_group_names() -> dict[str, str]:
    """Every group of both levels, from OpenFoodFacts' word to the name served."""
    return {
        # First level.
        "Beverages": _("Beverages"),
        "Cereals and potatoes": _("Cereals and potatoes"),
        "Composite foods": _("Composite foods"),
        "Fat and sauces": _("Fat and sauces"),
        "Fish Meat Eggs": _("Fish, meat and eggs"),
        "Fruits and vegetables": _("Fruits and vegetables"),
        "Milk and dairy products": _("Milk and dairy products"),
        "Salty snacks": _("Salty snacks"),
        "Sugary snacks": _("Sugary snacks"),
        # Second level.
        "Alcoholic beverages": _("Alcoholic beverages"),
        "Appetizers": _("Appetizers"),
        "Artificially sweetened beverages": _("Artificially sweetened beverages"),
        "Biscuits and cakes": _("Biscuits and cakes"),
        "Bread": _("Bread"),
        "Breakfast cereals": _("Breakfast cereals"),
        "Cereals": _("Cereals"),
        "Cheese": _("Cheese"),
        "Chocolate products": _("Chocolate products"),
        "Dairy desserts": _("Dairy desserts"),
        "Dressings and sauces": _("Dressings and sauces"),
        "Dried fruits": _("Dried fruits"),
        "Eggs": _("Eggs"),
        "Fats": _("Fats"),
        "Fish and seafood": _("Fish and seafood"),
        "Fruit juices": _("Fruit juices"),
        "Fruit nectars": _("Fruit nectars"),
        "Fruits": _("Fruits"),
        "Ice cream": _("Ice cream"),
        "Legumes": _("Legumes"),
        "Meat": _("Meat"),
        "Milk and yogurt": _("Milk and yogurt"),
        "Non-sugared beverages": _("Non-sugared beverages"),
        "Nuts": _("Nuts"),
        "Offals": _("Offals"),
        "One-dish meals": _("One-dish meals"),
        "Pastries": _("Pastries"),
        "Pizza pies and quiche": _("Pizza pies and quiche"),
        "Potatoes": _("Potatoes"),
        "Processed meat": _("Processed meat"),
        "Salty and fatty products": _("Salty and fatty products"),
        "Sandwiches": _("Sandwiches"),
        "Soups": _("Soups"),
        "Sweetened beverages": _("Sweetened beverages"),
        "Sweets": _("Sweets"),
        "Tripe dishes": _("Tripe dishes"),
        "Vegetables": _("Vegetables"),
        "Waters and flavored waters": _("Waters and flavored waters"),
    }
