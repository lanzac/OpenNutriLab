from django.db.models.manager import BaseManager
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from products.api.schemas.inbound import ProductCreate
from products.api.schemas.inbound import ProductUpdate
from products.api.schemas.outbound import ProductOut
from products.models import Product
from products.services import product_services

router = Router(tags=["Products CRUD"])


@router.get(path="/", response=list[ProductOut])
def list_products(request: HttpRequest) -> BaseManager[Product]:
    return Product.objects.prefetch_related(
        "productmacronutrient_set__macronutrient",
    ).all()


@router.get(path="/{product_id}", response=ProductOut)
def get_product(request: HttpRequest, product_id: str) -> Product:
    return get_object_or_404(Product, barcode=product_id)


@router.post(path="/", response=ProductOut)
def create_product(request: HttpRequest, data: ProductCreate) -> Product:
    try:
        return product_services.create_product(data).product
    except product_services.ProductAlreadyExistsError as e:
        raise HttpError(409, f"A product with barcode {data.barcode} exists.") from e
    except product_services.UnknownMacronutrientError as e:
        raise HttpError(422, str(e)) from e


@router.patch("/{product_id}", response=ProductOut)
def update_product(
    request: HttpRequest, product_id: str, data: ProductUpdate
) -> Product:
    product = get_object_or_404(Product, barcode=product_id)
    try:
        return product_services.update_product(product, data).product
    except product_services.UnknownMacronutrientError as e:
        raise HttpError(422, str(e)) from e


@router.delete(path="/{product_id}")
def delete_product(request: HttpRequest, product_id: str) -> dict[str, bool]:
    product: Product = get_object_or_404(Product, barcode=product_id)
    product.delete()
    return {"success": True}
