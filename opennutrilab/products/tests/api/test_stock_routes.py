"""The stock of the inventory, as the API counts it and serves it."""

from collections.abc import Mapping
from http import HTTPStatus

import pytest
from django.test import Client

from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Product
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

INVENTORY = "/api/v1/inventory/"
PRODUCTS = "/api/v1/products/"


@pytest.fixture
def api_client(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


@pytest.fixture
def muesli(user: User) -> Product:
    """A muesli of 375 g, in the inventory of the user."""
    product = Product.objects.create(
        barcode="3229820794556",
        name="Muesli",
        package_quantity=375,
        package_unit="g",
    )
    InventoryItem.objects.create(user=user, product=product)
    return product


def without_date(stock: Mapping[str, str | None]) -> dict[str, str | None]:
    """A stock as served, without the date it was counted on (see its own tests)."""
    return {key: value for key, value in stock.items() if key != "counted_at"}


def count(client: Client, product: Product, body: Mapping[str, str | None]):
    return client.put(
        f"{INVENTORY}{product.barcode}/stock", body, content_type="application/json"
    )


def test_a_stock_is_counted_and_served_with_the_inventory(
    api_client: Client, muesli: Product
):
    response = count(api_client, muesli, {"quantity": "300"})

    assert response.status_code == HTTPStatus.OK
    assert without_date(response.json()["stock"]) == {"quantity": "300.00", "unit": "g"}
    [listed] = api_client.get(INVENTORY).json()
    assert without_date(listed["stock"]) == {"quantity": "300.00", "unit": "g"}


def test_a_stock_is_served_with_the_day_it_was_counted(
    api_client: Client, muesli: Product
):
    [listed] = api_client.get(INVENTORY).json()
    assert listed["stock"]["counted_at"] is None

    counted = count(api_client, muesli, {"quantity": "300"}).json()["stock"]

    assert counted["counted_at"] is not None
    [listed] = api_client.get(INVENTORY).json()
    assert listed["stock"]["counted_at"] == counted["counted_at"]
    in_list = {p["barcode"]: p["stock"] for p in api_client.get(PRODUCTS).json()}
    assert in_list[muesli.barcode]["counted_at"] == counted["counted_at"]


def test_the_day_a_stock_was_counted_is_forgotten_when_it_is_not_counted_any_more(
    api_client: Client, muesli: Product
):
    count(api_client, muesli, {"quantity": "300"})

    stock = count(api_client, muesli, {"quantity": None}).json()["stock"]

    assert stock["counted_at"] is None


def test_a_stock_not_counted_is_served_with_the_unit_it_would_be_counted_in(
    api_client: Client, muesli: Product
):
    [listed] = api_client.get(INVENTORY).json()

    assert without_date(listed["stock"]) == {"quantity": None, "unit": "g"}


def test_the_unit_of_a_stock_is_the_one_of_the_package(api_client: Client, user: User):
    oil = Product.objects.create(
        barcode="3270190008262", name="Oil", package_quantity=1000, package_unit="ml"
    )
    InventoryItem.objects.create(user=user, product=oil)

    assert api_client.get(INVENTORY).json()[0]["stock"]["unit"] == "ml"
    assert without_date(
        count(api_client, oil, {"quantity": "400"}).json()["stock"]
    ) == {
        "quantity": "400.00",
        "unit": "ml",
    }


def test_a_stock_can_be_counted_in_another_unit(api_client: Client, muesli: Product):
    response = count(api_client, muesli, {"quantity": "2", "unit": "ml"})

    assert without_date(response.json()["stock"]) == {"quantity": "2.00", "unit": "ml"}


def test_a_stock_used_up_is_counted_as_nothing(api_client: Client, muesli: Product):
    count(api_client, muesli, {"quantity": "300"})

    response = count(api_client, muesli, {"quantity": "0"})

    assert response.status_code == HTTPStatus.OK
    assert response.json()["stock"]["quantity"] == "0.00"


def test_a_null_quantity_says_the_stock_is_not_counted(
    api_client: Client, muesli: Product
):
    count(api_client, muesli, {"quantity": "300"})

    response = count(api_client, muesli, {"quantity": None})

    assert without_date(response.json()["stock"]) == {"quantity": None, "unit": "g"}
    item = InventoryItem.objects.get()
    assert (item.stock_quantity, item.stock_unit, item.counted_at) == (None, "", None)


@pytest.mark.parametrize(
    "body", [{"quantity": "-1"}, {"quantity": "5", "unit": "kg"}, {"quantity": "x"}]
)
def test_a_stock_below_nothing_or_in_no_unit_is_refused(
    api_client: Client, muesli: Product, body: dict[str, str]
):
    response = count(api_client, muesli, body)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert InventoryItem.objects.get().stock_quantity is None


def test_a_product_that_is_not_in_the_inventory_has_no_stock_to_count(
    api_client: Client, muesli: Product
):
    InventoryItem.objects.all().delete()

    assert count(api_client, muesli, {"quantity": "300"}).status_code == (
        HTTPStatus.NOT_FOUND
    )


def test_a_stock_is_counted_by_a_signed_in_user_only(client: Client, muesli: Product):
    response = count(client, muesli, {"quantity": "300"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert InventoryItem.objects.get().stock_quantity is None


def test_the_stock_is_each_users_own(api_client: Client, user: User, muesli: Product):
    other = UserFactory()
    InventoryItem.objects.create(user=other, product=muesli)
    count(api_client, muesli, {"quantity": "300"})

    assert InventoryItem.objects.get(user=other).stock_quantity is None
    assert InventoryItem.objects.get(user=user).stock_quantity == 300  # noqa: PLR2004


def test_the_list_of_products_gives_the_stock_of_those_in_the_inventory(
    api_client: Client, muesli: Product
):
    other = Product.objects.create(barcode="7613032637620", name="Other")
    count(api_client, muesli, {"quantity": "300"})

    listed = {p["barcode"]: p["stock"] for p in api_client.get(PRODUCTS).json()}

    assert without_date(listed[muesli.barcode]) == {"quantity": "300.00", "unit": "g"}
    # Not in the inventory, so not counted.
    assert listed[other.barcode] is None


def test_the_list_of_products_gives_the_stock_of_the_user_asking(
    api_client: Client, muesli: Product
):
    other = UserFactory()
    InventoryItem.objects.create(user=other, product=muesli)
    count(api_client, muesli, {"quantity": "300"})

    listed = {p["barcode"]: p["stock"] for p in api_client.get(PRODUCTS).json()}

    assert listed[muesli.barcode]["quantity"] == "300.00"


# ----------------------------------------------------------------------------
# Servings: pots, slices
# ----------------------------------------------------------------------------
@pytest.fixture
def compote(user: User) -> Product:
    """A compote of 400 g in pots of 100 g, in the inventory of the user."""
    product = Product.objects.create(
        barcode="3245412890987",
        name="Compote",
        package_quantity=400,
        package_unit="g",
        serving_quantity=100,
        serving_unit="g",
        serving_name="1 pot",
    )
    InventoryItem.objects.create(user=user, product=product)
    return product


def test_a_product_with_pots_is_counted_in_pots_until_told_otherwise(
    api_client: Client, compote: Product
):
    [listed] = api_client.get(INVENTORY).json()

    assert without_date(listed["stock"]) == {"quantity": None, "unit": "serving"}
    assert listed["count_noun"] == "pot"


def test_a_product_with_no_named_serving_has_no_noun_to_count_by(
    api_client: Client, muesli: Product
):
    Product.objects.filter(pk=muesli.pk).update(
        serving_quantity=80, serving_unit="g", serving_name=""
    )

    [listed] = api_client.get(INVENTORY).json()

    assert listed["count_noun"] is None
    assert listed["stock"]["unit"] == "g"


def test_pots_are_counted(api_client: Client, compote: Product):
    response = count(api_client, compote, {"quantity": "4"})

    assert response.status_code == HTTPStatus.OK
    assert without_date(response.json()["stock"]) == {
        "quantity": "4.00",
        "unit": "serving",
    }


def test_a_product_with_pots_can_be_counted_in_grams(
    api_client: Client, compote: Product
):
    response = count(api_client, compote, {"quantity": "250", "unit": "g"})

    assert without_date(response.json()["stock"]) == {"quantity": "250.00", "unit": "g"}


def test_pots_are_not_cut(api_client: Client, compote: Product):
    response = count(api_client, compote, {"quantity": "2.5"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert InventoryItem.objects.get().stock_quantity is None


def test_servings_need_a_product_that_has_one(api_client: Client, muesli: Product):
    response = count(api_client, muesli, {"quantity": "2", "unit": "serving"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_the_list_of_products_serves_the_serving_and_what_it_is_counted_by(
    api_client: Client, compote: Product
):
    [listed] = api_client.get(PRODUCTS).json()

    assert listed["serving"] == {"quantity": "100.00", "unit": "g", "name": "1 pot"}
    assert listed["count_noun"] == "pot"
    assert without_date(listed["stock"]) == {"quantity": None, "unit": "serving"}
