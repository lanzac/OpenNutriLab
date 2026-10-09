from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.derived_nutrients import ensure_derivations
from opennutrilab.users.models import User

CONSTITUENTS_FILE = (
    Path(__file__).parents[2] / "products" / "tests" / "data" / "ciqual_const_2025.xml"
)
DAY = date(2026, 10, 9)


@pytest.fixture
def catalogue(db: None) -> None:
    """The nutrients CIQUAL gives, with the derivations set up."""
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    ensure_derivations()


def make_product(
    barcode: str,
    *,
    serving: str | None = None,
    **declared: str,
) -> Product:
    """
    A product with no ingredient, whose composition is what its label declares:
    `declared` are amounts per 100 g by nutrient code.
    """
    product = Product.objects.create(
        barcode=barcode,
        name=f"Product {barcode}",
        serving_quantity=None if serving is None else Decimal(serving),
        serving_unit="" if serving is None else "g",
    )
    for code, amount in declared.items():
        ProductNutrient.objects.create(
            product=product, nutrient=Nutrient.objects.get(code=code), amount=amount
        )
    return product


def stock(user: User, *products: Product) -> None:
    """Put products in a user's inventory."""
    for product in products:
        InventoryItem.objects.create(user=user, product=product)
