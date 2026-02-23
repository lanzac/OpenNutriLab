from django.db.models.manager import BaseManager
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router

from products.api import services
from products.api.schemas.inbound import ProductCreate
from products.api.schemas.inbound import ProductUpdate
from products.api.schemas.outbound import ProductOut
from products.models import Product

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
    return services.create_product(data)


@router.patch("/{product_id}", response=ProductOut)
def update_product(
    request: HttpRequest, product_id: str, payload: ProductUpdate
) -> Product:
    product = get_object_or_404(Product, barcode=product_id)

    for attr, value in payload.dict(exclude_unset=True).items():
        setattr(product, attr, value)

    product.save()
    return product


@router.delete(path="/{product_id}")
def delete_product(request: HttpRequest, product_id: int) -> dict[str, bool]:
    product: Product = get_object_or_404(Product, barcode=product_id)
    product.delete()
    return {"success": True}
