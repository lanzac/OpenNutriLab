from typing import TYPE_CHECKING
from typing import Any

import pytest
from ninja.testing import TestClient

from products.api.api_ninja_crud import router
from products.api.schemas.inbound import ProductCreate
from products.models import Product
from products.services import product_services

if TYPE_CHECKING:
    from ninja.testing.client import NinjaResponse

client = TestClient(router)


@pytest.fixture
def api_client() -> TestClient:
    return client


def _minimal_payload(barcode: str, name: str) -> dict[str, Any]:
    return {
        "barcode": barcode,
        "name": name,
        "description": "",
        "group_level_1": "",
        "group_level_2": "",
        "nutritional_values": {
            "energy_kj": 100,
            "macronutrients": [],
        },
    }


@pytest.fixture
@pytest.mark.django_db
def products_two() -> tuple[Product, Product]:
    """
    Create two products via the real service layer.
    Returned products are saved in DB and can be reused by tests.
    """
    p1_payload: dict[str, Any] = _minimal_payload("3229820794556", "TestProd One")
    p2_payload: dict[str, Any] = _minimal_payload("7613032637620", "TestProd Two")

    p1 = product_services.create_product(ProductCreate.model_validate(p1_payload))
    p2 = product_services.create_product(ProductCreate.model_validate(p2_payload))
    return p1.product, p2.product


@pytest.mark.django_db
def test_list_products(api_client: TestClient, products_two: tuple[Product, Product]):
    resp: NinjaResponse = api_client.get("/")  # pyright: ignore[reportUnknownMemberType]
    assert resp.status_code == 200  # noqa: PLR2004
    data: list[dict[str, Any]] = resp.json()
    assert isinstance(data, list)
    barcodes = {item["barcode"] for item in data}
    p1, p2 = products_two
    assert p1.barcode in barcodes
    assert p2.barcode in barcodes


@pytest.mark.django_db
def test_get_product(api_client: TestClient, products_two: tuple[Product, Product]):
    p1, _ = products_two
    resp: NinjaResponse = api_client.get(f"/{p1.barcode}")  # pyright: ignore[reportUnknownMemberType]
    assert resp.status_code == 200  # noqa: PLR2004
    data = resp.json()
    assert data["barcode"] == p1.barcode
    assert data["name"] == p1.name


@pytest.mark.django_db
def test_update_product(api_client: TestClient, products_two: tuple[Product, Product]):
    p1, _ = products_two
    update_payload: dict[str, str | dict[str, list[Any] | None]] = {
        "name": "Updated Name",
        "nutritional_values": {"energy_kj": None, "macronutrients": []},
    }
    # send through API (which will call product_services.update_product internally)
    resp = api_client.patch(f"/{p1.barcode}", json=update_payload)  # pyright: ignore[reportUnknownMemberType]
    assert resp.status_code == 200  # noqa: PLR2004
    data = resp.json()
    assert data["name"] == "Updated Name"

    # verify DB persisted
    p1.refresh_from_db()
    assert p1.name == "Updated Name"


@pytest.mark.django_db
def test_create_product_via_api(api_client: TestClient):
    new_payload = _minimal_payload("3297760097969", "Created Via API")
    resp = api_client.post("/", json=new_payload)  # pyright: ignore[reportUnknownMemberType]
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["barcode"] == new_payload["barcode"]
    # check DB
    assert Product.objects.filter(barcode=new_payload["barcode"]).exists()


@pytest.mark.django_db
def test_delete_product(api_client: TestClient, products_two: tuple[Product, Product]):
    _, p2 = products_two
    resp = api_client.delete(f"/{p2.barcode}")  # pyright: ignore[reportUnknownMemberType]
    assert resp.status_code in (200, 204)
    assert not Product.objects.filter(barcode=p2.barcode).exists()


@pytest.mark.django_db
def test_delete_product_with_a_leading_zero(api_client: TestClient):
    # EAN-13 codes may start with 0. The path parameter used to be typed int,
    # which turned "0123456789012" into 123456789012 and missed the product.
    barcode = "0123456789012"
    Product.objects.create(barcode=barcode, name="Leading zero", energy_kj=100)

    resp = api_client.delete(f"/{barcode}")  # pyright: ignore[reportUnknownMemberType]

    assert resp.status_code == 200  # noqa: PLR2004
    assert not Product.objects.filter(barcode=barcode).exists()


@pytest.mark.django_db
def test_create_product_refuses_an_existing_barcode(
    api_client: TestClient, products_two: tuple[Product, Product]
):
    p1, _ = products_two
    payload = _minimal_payload(p1.barcode, "Overwrite attempt")

    resp = api_client.post("/", json=payload)  # pyright: ignore[reportUnknownMemberType]

    assert resp.status_code == 409  # noqa: PLR2004
    p1.refresh_from_db()
    assert p1.name == "TestProd One"


@pytest.mark.django_db
def test_create_product_rejects_an_unknown_macronutrient(api_client: TestClient):
    payload = _minimal_payload("3017620422003", "Nutella")
    payload["nutritional_values"]["macronutrients"] = [
        {"name": "unobtainium", "amount_g": 1}
    ]

    resp = api_client.post("/", json=payload)  # pyright: ignore[reportUnknownMemberType]

    assert resp.status_code == 422  # noqa: PLR2004
    assert not Product.objects.filter(barcode="3017620422003").exists()


@pytest.mark.django_db
def test_create_product_rejects_an_image_url_outside_openfoodfacts(
    api_client: TestClient,
):
    payload = _minimal_payload("3017620422003", "Nutella")
    payload["image_url"] = "http://redis:6379/"

    resp = api_client.post("/", json=payload)  # pyright: ignore[reportUnknownMemberType]

    assert resp.status_code == 422  # noqa: PLR2004
