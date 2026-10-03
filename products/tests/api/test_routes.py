from http import HTTPStatus
from typing import Any

import pytest
from allauth.account.models import EmailAddress
from django.test import Client

from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory
from products.api.schemas.inbound import ProductCreate
from products.models import Product
from products.services import product_services

API = "/api/v1/products/"
PASSWORD = "a-Long-and-unguessable-passw0rd"  # noqa: S105 - a test user's


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
def products_two(db: None) -> tuple[Product, Product]:
    p1 = product_services.create_product(
        ProductCreate.model_validate(_minimal_payload("3229820794556", "TestProd One"))
    )
    p2 = product_services.create_product(
        ProductCreate.model_validate(_minimal_payload("7613032637620", "TestProd Two"))
    )
    return p1.product, p2.product


@pytest.fixture
def api_client(client: Client, user: User) -> Client:
    """A browser-like client: logged in through the Django session."""
    client.force_login(user)
    return client


@pytest.fixture
def staff_client(client: Client) -> Client:
    client.force_login(UserFactory(is_staff=True))
    return client


# -----------------------
# Authentication
# -----------------------
@pytest.mark.django_db
def test_anonymous_requests_are_refused(client: Client):
    assert client.get(API).status_code == HTTPStatus.UNAUTHORIZED
    response = client.post(
        API, _minimal_payload("3017620422003", "N"), content_type="application/json"
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
def test_session_writes_need_the_csrf_token(user: User):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    response = client.post(
        API, _minimal_payload("3017620422003", "N"), content_type="application/json"
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert not Product.objects.exists()


@pytest.mark.django_db
def test_the_mobile_app_logs_in_through_allauth_and_sends_its_token(client: Client):
    """
    The flow a native client follows: log in on allauth's headless app API,
    then authenticate API calls with the session token it hands back.
    """
    user = UserFactory(password=PASSWORD)
    EmailAddress.objects.create(
        user=user, email=user.email, verified=True, primary=True
    )

    login = client.post(
        "/_allauth/app/v1/auth/login",
        {"username": user.username, "password": PASSWORD},
        content_type="application/json",
    )
    assert login.status_code == HTTPStatus.OK, login.json()
    token = login.json()["meta"]["session_token"]

    # A fresh client: no session cookie, only the header.
    response = Client().get(API, headers={"X-Session-Token": token})

    assert response.status_code == HTTPStatus.OK
    assert Client().get(API).status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
def test_cors_is_answered_for_the_api_and_allauth_only(client: Client, settings: Any):
    settings.CORS_ALLOWED_ORIGINS = ["https://app.example"]
    preflight = {
        "Origin": "https://app.example",
        "Access-Control-Request-Method": "GET",
    }

    for path in (API, "/_allauth/app/v1/config"):
        response = client.options(path, headers=preflight)
        assert response["Access-Control-Allow-Origin"] == "https://app.example", path

    page = client.options("/products/", headers=preflight)
    assert not page.has_header("Access-Control-Allow-Origin")


@pytest.mark.django_db
def test_docs_are_for_staff(client: Client, user: User):
    client.force_login(user)
    assert client.get("/api/v1/docs").status_code == HTTPStatus.FOUND

    client.force_login(UserFactory(is_staff=True))
    assert client.get("/api/v1/docs").status_code == HTTPStatus.OK


# -----------------------
# Products
# -----------------------
@pytest.mark.django_db
def test_list_products(api_client: Client, products_two: tuple[Product, Product]):
    response = api_client.get(API)

    assert response.status_code == HTTPStatus.OK
    p1, p2 = products_two
    # Only what a list shows: no nested nutritional values or ingredients.
    assert [set(item) for item in response.json()] == [
        {"barcode", "name", "created_at"}
    ] * 2
    assert {item["barcode"] for item in response.json()} == {p1.barcode, p2.barcode}


@pytest.mark.django_db
def test_get_product(api_client: Client, products_two: tuple[Product, Product]):
    p1, _ = products_two

    response = api_client.get(f"{API}{p1.barcode}")

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert (data["barcode"], data["name"]) == (p1.barcode, p1.name)
    assert "nutritional_values" in data


@pytest.mark.django_db
def test_update_product(api_client: Client, products_two: tuple[Product, Product]):
    p1, _ = products_two

    response = api_client.patch(
        f"{API}{p1.barcode}",
        {"name": "Updated Name", "nutritional_values": {"macronutrients": []}},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["name"] == "Updated Name"
    p1.refresh_from_db()
    assert p1.name == "Updated Name"


@pytest.mark.django_db
def test_create_product(api_client: Client):
    payload = _minimal_payload("3297760097969", "Created Via API")

    response = api_client.post(API, payload, content_type="application/json")

    assert response.status_code == HTTPStatus.OK
    assert response.json()["barcode"] == payload["barcode"]
    assert Product.objects.filter(barcode=payload["barcode"]).exists()


@pytest.mark.django_db
def test_create_product_refuses_an_existing_barcode(
    api_client: Client, products_two: tuple[Product, Product]
):
    p1, _ = products_two
    payload = _minimal_payload(p1.barcode, "Overwrite attempt")

    response = api_client.post(API, payload, content_type="application/json")

    assert response.status_code == HTTPStatus.CONFLICT
    p1.refresh_from_db()
    assert p1.name == "TestProd One"


@pytest.mark.django_db
def test_create_product_rejects_an_unknown_macronutrient(api_client: Client):
    payload = _minimal_payload("3017620422003", "Nutella")
    payload["nutritional_values"]["macronutrients"] = [
        {"name": "unobtainium", "amount_g": 1}
    ]

    response = api_client.post(API, payload, content_type="application/json")

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not Product.objects.filter(barcode="3017620422003").exists()


@pytest.mark.django_db
def test_create_product_rejects_an_image_url_outside_openfoodfacts(
    api_client: Client,
):
    payload = _minimal_payload("3017620422003", "Nutella")
    payload["image_url"] = "http://redis:6379/"

    response = api_client.post(API, payload, content_type="application/json")

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_only_staff_delete_products(
    api_client: Client, products_two: tuple[Product, Product]
):
    """The catalogue is shared by every user."""
    _, p2 = products_two

    assert api_client.delete(f"{API}{p2.barcode}").status_code == HTTPStatus.FORBIDDEN
    assert Product.objects.filter(barcode=p2.barcode).exists()


@pytest.mark.django_db
def test_staff_delete_a_product_with_a_leading_zero(staff_client: Client):
    # EAN-13 codes may start with 0. The path parameter used to be typed int,
    # which turned "0123456789012" into 123456789012 and missed the product.
    barcode = "0123456789012"
    Product.objects.create(barcode=barcode, name="Leading zero", energy_kj=100)

    response = staff_client.delete(f"{API}{barcode}")

    assert response.status_code == HTTPStatus.OK
    assert not Product.objects.filter(barcode=barcode).exists()
