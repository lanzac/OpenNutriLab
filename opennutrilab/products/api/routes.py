from django.db.models.manager import BaseManager
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.api.schemas.inbound import ProductUpdate
from opennutrilab.products.api.schemas.outbound import ProductListItemOut
from opennutrilab.products.api.schemas.outbound import ProductOut
from opennutrilab.products.models import Product
from opennutrilab.products.services import product_services

router = Router(tags=["Products"])


@router.get(path="/", response=list[ProductListItemOut])
def list_products(request: HttpRequest) -> BaseManager[Product]:
    # Just what a list shows. The full product, ingredient tree included, is
    # one request per product away at /{barcode}.
    return Product.objects.only("barcode", "name", "created_at").order_by("created_at")


@router.get(path="/{product_id}", response=ProductOut)
def get_product(request: HttpRequest, product_id: str) -> Product:
    return get_object_or_404(Product, barcode=product_id)


@router.post(path="/", response=ProductOut)
def create_product(request: HttpRequest, data: ProductCreate) -> Product:
    try:
        return product_services.create_product(data).product
    except product_services.ProductAlreadyExistsError as e:
        raise HttpError(409, f"A product with barcode {data.barcode} exists.") from e
    except product_services.UnknownNutrientError as e:
        raise HttpError(422, str(e)) from e


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
    if not request.auth.is_staff:  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        raise HttpError(403, "Only staff can delete products.")
    product: Product = get_object_or_404(Product, barcode=product_id)
    product.delete()
    return {"success": True}
