from typing import cast

from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import QuerySet
from django.db.models import Subquery
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.api.schemas.inbound import ProductUpdate
from opennutrilab.products.api.schemas.inbound import StockInput
from opennutrilab.products.api.schemas.outbound import EstimateOut
from opennutrilab.products.api.schemas.outbound import InventoryItemOut
from opennutrilab.products.api.schemas.outbound import ProductListItemOut
from opennutrilab.products.api.schemas.outbound import ProductOut
from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Product
from opennutrilab.products.services import product_services
from opennutrilab.products.services.estimate_report import build_estimate
from opennutrilab.products.services.inventory import add_to_inventory
from opennutrilab.products.services.inventory import inventory_of
from opennutrilab.products.services.inventory import remove_from_inventory
from opennutrilab.products.services.stock import InvalidStockError
from opennutrilab.products.services.stock import set_stock
from opennutrilab.users.models import User

router = Router(tags=["Products"])
inventory_router = Router(tags=["Inventory"])


def _user(request: HttpRequest) -> User:
    """The user asking: every route needs one (see config.api)."""
    return cast("User", request.auth)  # pyright: ignore[reportAttributeAccessIssue]


@router.get(path="/", response=list[ProductListItemOut])
def list_products(request: HttpRequest) -> QuerySet[Product]:
    # Just what a list shows. The full product, ingredient tree included, is
    # one request per product away at /{barcode}.
    mine = InventoryItem.objects.filter(user=_user(request), product=OuterRef("pk"))
    return (
        Product.objects.only(
            "barcode",
            "name",
            "image",
            "created_at",
            "group_level_1",
            "group_level_2",
            "package_quantity",
            "package_unit",
            "serving_quantity",
            "serving_unit",
            "serving_name",
        )
        .annotate(
            in_inventory=Exists(mine),
            stock_quantity=Subquery(mine.values("stock_quantity")[:1]),
            stock_unit=Subquery(mine.values("stock_unit")[:1]),
        )
        .order_by("created_at")
    )


@router.get(path="/{product_id}", response=ProductOut)
def get_product(request: HttpRequest, product_id: str) -> Product:
    return get_object_or_404(Product, barcode=product_id)


@router.get(path="/{product_id}/estimate", response=EstimateOut)
def get_estimate(request: HttpRequest, product_id: str) -> EstimateOut:
    """
    What the product's ingredients say of its nutrients, set against its label.

    Worked out on each request (about a second for a product with a dozen
    ingredients), and never stored: the figures are intervals, each with the parts
    its confidence is made of.
    """
    return build_estimate(get_object_or_404(Product, barcode=product_id))


@router.post(path="/", response=ProductOut)
def create_product(request: HttpRequest, data: ProductCreate) -> Product:
    try:
        product = product_services.create_product(data).product
    except product_services.ProductAlreadyExistsError as e:
        raise HttpError(409, f"A product with barcode {data.barcode} exists.") from e
    except product_services.UnknownNutrientError as e:
        raise HttpError(422, str(e)) from e
    # Whoever adds a product has it at hand.
    add_to_inventory(_user(request), product)
    return product


@router.patch("/{product_id}", response=ProductOut)
def update_product(
    request: HttpRequest, product_id: str, data: ProductUpdate
) -> Product:
    product = get_object_or_404(Product, barcode=product_id)
    try:
        return product_services.update_product(product, data).product
    except product_services.UnknownNutrientError as e:
        raise HttpError(422, str(e)) from e


@router.delete(path="/{product_id}")
def delete_product(request: HttpRequest, product_id: str) -> dict[str, bool]:
    # Products form a catalogue shared by every user, so removing one is
    # reserved to staff.
    if not _user(request).is_staff:
        raise HttpError(403, "Only staff can delete products.")
    product: Product = get_object_or_404(Product, barcode=product_id)
    product.delete()
    return {"success": True}


# -------------------------
# The inventory of the user asking
# -------------------------
@inventory_router.get(path="/", response=list[InventoryItemOut])
def list_inventory(request: HttpRequest) -> QuerySet[InventoryItem]:
    return inventory_of(_user(request))


@inventory_router.put(path="/{product_id}", response=InventoryItemOut)
def add_to_my_inventory(request: HttpRequest, product_id: str) -> InventoryItem:
    """Put a product in the inventory. Putting one that is there changes nothing."""
    product = get_object_or_404(Product, barcode=product_id)
    return add_to_inventory(_user(request), product)


@inventory_router.put(path="/{product_id}/stock", response=InventoryItemOut)
def count_my_stock(
    request: HttpRequest, product_id: str, data: StockInput
) -> InventoryItem:
    """
    Say how much of a product of the inventory is at hand now, which is the stock from
    then on: the meals eaten take from it. A null quantity says it is not counted, and
    then nothing limits what a day uses of the product.
    """
    item = get_object_or_404(inventory_of(_user(request)), product_id=product_id)
    try:
        return set_stock(item, data.quantity, data.unit)
    except InvalidStockError as e:
        raise HttpError(
            422, "Servings must be whole, and the product must have a serving."
        ) from e


@inventory_router.delete(path="/{product_id}")
def remove_from_my_inventory(request: HttpRequest, product_id: str) -> dict[str, bool]:
    """Take a product out of the inventory, where it may not be."""
    product = get_object_or_404(Product, barcode=product_id)
    remove_from_inventory(_user(request), product)
    return {"in_inventory": False}
