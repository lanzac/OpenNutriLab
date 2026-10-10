from decimal import Decimal
from http import HTTPStatus
from typing import Any

import pytest
from allauth.account.models import EmailAddress
from django.test import Client

from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.api.schemas.outbound import ProductOut
from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.services import product_services
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

API = "/api/v1/products/"
PASSWORD = "a-Long-and-unguessable-passw0rd"  # noqa: S105 - a test user's


def _minimal_payload(barcode: str, name: str) -> dict[str, Any]:
    return {
        "barcode": barcode,
        "name": name,
        "description": "",
        "group_level_1": "",
        "group_level_2": "",
        "nutrients": {"energy": 100, "fat": "9.4"},
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
        {
            "barcode",
            "name",
            "image",
            "created_at",
            "group_level_1",
            "group_level_2",
            "in_inventory",
            "package",
        }
    ] * 2
    assert {item["barcode"] for item in response.json()} == {p1.barcode, p2.barcode}


@pytest.mark.django_db
def test_list_products_serves_the_photo_and_the_groups(
    api_client: Client, products_two: tuple[Product, Product]
):
    p1, p2 = products_two
    # Only the name of the file is set: nothing is written to the media folder.
    Product.objects.filter(pk=p1.pk).update(
        image="images/products/3229820794556.jpg",
        group_level_1="Cereals and potatoes",
        group_level_2="Breakfast cereals",
    )

    listed = {p["barcode"]: p for p in api_client.get(API).json()}

    # The URL the media folder is served from, whatever the settings make it.
    photo = Product.objects.get(pk=p1.pk).image
    assert listed[p1.barcode]["image"] == photo.url
    assert photo.url.endswith("/images/products/3229820794556.jpg")
    assert (
        listed[p1.barcode]["group_level_1"],
        listed[p1.barcode]["group_level_2"],
    ) == ("Cereals and potatoes", "Breakfast cereals")
    # A product with no photo says so, and one with no group has empty ones.
    assert listed[p2.barcode]["image"] is None
    assert listed[p2.barcode]["group_level_1"] == ""


@pytest.mark.django_db
def test_get_product(api_client: Client, products_two: tuple[Product, Product]):
    p1, _ = products_two

    response = api_client.get(f"{API}{p1.barcode}")

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert (data["barcode"], data["name"]) == (p1.barcode, p1.name)
    # Declared values carry their unit.
    assert {(n["code"], n["unit"], n["amount"]) for n in data["nutrients"]} == {
        ("energy", "kJ", "100.0000"),
        ("fat", "g", "9.4000"),
    }


@pytest.mark.django_db
def test_the_text_the_ingredients_were_read_from_is_written_and_served(
    api_client: Client,
):
    payload = _minimal_payload("3297760097969", "Created Via API")
    payload["ingredients_text"] = "Sucre 56,3 %, lait"
    api_client.post(API, payload, content_type="application/json")
    url = f"{API}{payload['barcode']}"

    assert api_client.get(url).json()["ingredients_text"] == "Sucre 56,3 %, lait"

    api_client.patch(url, {"name": "Renamed"}, content_type="application/json")
    assert api_client.get(url).json()["ingredients_text"] == "Sucre 56,3 %, lait"

    api_client.patch(
        url, {"ingredients_text": "Cacao"}, content_type="application/json"
    )
    assert api_client.get(url).json()["ingredients_text"] == "Cacao"


@pytest.mark.django_db
def test_the_places_left_out_of_the_text_and_its_language_are_written_and_served(
    api_client: Client,
):
    payload = _minimal_payload("3297760097969", "Created Via API")
    payload["ingredients_text"] = "Sucre 56,3 %, lait [zone]"
    payload["ingredients_language"] = "fr"
    payload["ingredients_ignored"] = [[18, 24]]
    api_client.post(API, payload, content_type="application/json")
    url = f"{API}{payload['barcode']}"

    served = api_client.get(url).json()
    assert (served["ingredients_language"], served["ingredients_ignored"]) == (
        "fr",
        [[18, 24]],
    )

    api_client.patch(url, {"name": "Renamed"}, content_type="application/json")
    assert api_client.get(url).json()["ingredients_ignored"] == [[18, 24]]

    api_client.patch(url, {"ingredients_ignored": []}, content_type="application/json")
    assert api_client.get(url).json()["ingredients_ignored"] == []


@pytest.mark.django_db
@pytest.mark.parametrize("place", [[5, 2], [-1, 3], [4, 4], [1, 2, 3]])
def test_a_place_that_is_not_one_is_refused(api_client: Client, place: list[int]):
    payload = _minimal_payload("3297760097969", "Created Via API")
    payload["ingredients_ignored"] = [place]

    response = api_client.post(API, payload, content_type="application/json")

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_an_ingredient_is_served_as_the_one_it_is(api_client: Client):
    """
    No name and no OpenFoodFacts data of its own: what it is says it all. One whose
    parts the label lists is a preparation, one that has none a reference.
    """
    payload = _minimal_payload("3297760097969", "Created Via API")
    payload["ingredients"] = [
        {
            "name": "Dates",
            "percentage": "7",
            "sub_ingredients": [{"name": "rice flour"}],
        }
    ]
    api_client.post(API, payload, content_type="application/json")
    ReferenceIngredient.objects.filter(name_en="rice flour").update(
        status=ReferenceIngredient.Status.CURATED
    )

    response = api_client.get(f"{API}{payload['barcode']}")

    [dates] = response.json()["ingredients"]
    assert set(dates) == {
        "percentage",
        "reference",
        "preparation",
        "additive",
        "sub_ingredients",
    }
    # It lists its parts: a preparation, and the other two are null.
    assert dates["reference"] is None
    assert dates["additive"] is None
    assert dates["percentage"] == "7.00"
    assert dates["preparation"] == {
        "id": Preparation.objects.get(name_en="Dates").pk,
        "name": "Dates",
        "status": "to_review",
    }
    [rice] = dates["sub_ingredients"]
    assert (rice["reference"]["name"], rice["reference"]["status"]) == (
        "rice flour",
        "curated",
    )


@pytest.mark.django_db
def test_a_products_tree_is_read_in_a_fixed_number_of_queries(
    django_assert_max_num_queries: Any,
):
    """One per level, not one per ingredient (or per reference)."""
    product = product_services.create_product(
        ProductCreate.model_validate(
            {
                **_minimal_payload("3297760097969", "Tree"),
                "ingredients": [
                    {
                        "name": "A",
                        "sub_ingredients": [
                            {"name": "B", "sub_ingredients": [{"name": "C"}]},
                            {"name": "D"},
                        ],
                    },
                    {"name": "E"},
                    {"name": "F", "sub_ingredients": [{"name": "G"}]},
                ],
            }
        )
    ).product

    # The product's nutrients, the top level, then one query per level below.
    with django_assert_max_num_queries(5):
        tree = ProductOut.from_orm(product).model_dump()["ingredients"]

    def names(ingredients: list[dict[str, Any]]) -> list[Any]:
        return [
            ((i["reference"] or i["preparation"])["name"], names(i["sub_ingredients"]))
            for i in ingredients
        ]

    assert names(tree) == [
        ("A", [("B", [("C", [])]), ("D", [])]),
        ("E", []),
        ("F", [("G", [])]),
    ]


@pytest.mark.django_db
def test_the_serving_is_written_served_kept_and_cleared(api_client: Client):
    payload = _minimal_payload("3297760097969", "Created Via API")
    url = f"{API}{payload['barcode']}"
    api_client.post(API, payload, content_type="application/json")
    assert api_client.get(url).json()["serving"] is None

    api_client.patch(
        url,
        {"serving": {"quantity": "35.7", "name": "1 tranche"}},
        content_type="application/json",
    )
    served = {"quantity": "35.70", "unit": "g", "name": "1 tranche"}
    assert api_client.get(url).json()["serving"] == served

    api_client.patch(url, {"name": "Renamed"}, content_type="application/json")
    assert api_client.get(url).json()["serving"] == served

    api_client.patch(url, {"serving": None}, content_type="application/json")
    assert api_client.get(url).json()["serving"] is None


@pytest.mark.django_db
def test_the_package_is_written_served_kept_and_cleared(api_client: Client):
    payload = _minimal_payload("3297760097969", "Created Via API")
    url = f"{API}{payload['barcode']}"
    api_client.post(API, payload, content_type="application/json")
    assert api_client.get(url).json()["package"] is None

    api_client.patch(
        url, {"package": {"quantity": "500"}}, content_type="application/json"
    )
    served = {"quantity": "500.00", "unit": "g"}
    assert api_client.get(url).json()["package"] == served

    api_client.patch(url, {"name": "Renamed"}, content_type="application/json")
    assert api_client.get(url).json()["package"] == served

    api_client.patch(
        url,
        {"package": {"quantity": "1.5", "unit": "ml"}},
        content_type="application/json",
    )
    assert api_client.get(url).json()["package"] == {"quantity": "1.50", "unit": "ml"}

    api_client.patch(url, {"package": None}, content_type="application/json")
    assert api_client.get(url).json()["package"] is None


@pytest.mark.django_db
def test_the_package_is_written_on_creation_and_listed(api_client: Client):
    payload = _minimal_payload("3297760097969", "Created Via API")
    payload["package"] = {"quantity": "375", "unit": "g"}

    created = api_client.post(API, payload, content_type="application/json")
    listed = api_client.get(API).json()

    [package] = [item["package"] for item in listed]
    assert package == {"quantity": "375.00", "unit": "g"}
    assert Decimal(created.json()["package"]["quantity"]) == Decimal(375)


@pytest.mark.django_db
def test_a_package_of_nothing_is_refused(api_client: Client):
    payload = _minimal_payload("3297760097969", "Created Via API")
    payload["package"] = {"quantity": "0"}

    response = api_client.post(API, payload, content_type="application/json")

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_update_product(api_client: Client, products_two: tuple[Product, Product]):
    p1, _ = products_two

    response = api_client.patch(
        f"{API}{p1.barcode}",
        {"name": "Updated Name", "nutrients": {"fat": None, "salt": "0.03"}},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["name"] == "Updated Name"
    # fat: null clears it; salt: added; energy: left out, so untouched.
    assert {n["code"] for n in response.json()["nutrients"]} == {"energy", "salt"}
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
def test_create_product_rejects_an_unknown_nutrient(api_client: Client):
    payload = _minimal_payload("3017620422003", "Nutella")
    payload["nutrients"] = {"unobtainium": 1}

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
    Product.objects.create(barcode=barcode, name="Leading zero")

    response = staff_client.delete(f"{API}{barcode}")

    assert response.status_code == HTTPStatus.OK
    assert not Product.objects.filter(barcode=barcode).exists()


# -----------------------
# The estimate
# -----------------------
@pytest.mark.django_db
def test_the_estimate_needs_a_signed_in_user(client: Client):
    response = client.get(f"{API}3229820794556/estimate")

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
def test_the_estimate_of_an_unknown_product_is_not_found(api_client: Client):
    response = api_client.get(f"{API}3229820794556/estimate")

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_the_estimate_is_served_with_its_parts(api_client: Client):
    payload = _minimal_payload("3297760097969", "Created Via API")
    payload["ingredients"] = [
        {
            "name": "Dates",
            "percentage": "7",
            "sub_ingredients": [{"name": "rice flour"}],
        }
    ]
    api_client.post(API, payload, content_type="application/json")

    response = api_client.get(f"{API}{payload['barcode']}/estimate")

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert set(data) == {
        "barcode",
        "used_nutrition",
        "warnings",
        "nutrients",
        "ingredients",
        "sources",
        "caveat",
    }
    # No reference has a composition yet, so nothing is estimated, and it is said.
    assert [w["problem"] for w in data["warnings"]] == ["no_composition"]
    assert not data["used_nutrition"]
    [dates] = data["ingredients"]
    assert set(dates) == {
        "reference",
        "preparation",
        "additive",
        "declared",
        "estimated",
        "sub_ingredients",
    }
    assert dates["reference"] is None
    assert dates["additive"] is None
    # The label's figure and the estimate are two fields.
    assert dates["declared"] == "7.00"
    assert dates["estimated"] == {"low": "6.50", "point": "7.00", "high": "7.50"}
    [rice] = dates["sub_ingredients"]
    assert rice["declared"] is None
    assert rice["estimated"] is not None
    # What the label declares comes with a check, and no estimate to meet.
    energy = next(n for n in data["nutrients"] if n["code"] == "energy")
    assert energy["estimated"] is None
    assert energy["declared"]["amount"] == "100.0000"
    assert energy["check"]["verdict"] == "not_estimated"


@pytest.mark.django_db
def test_the_estimate_is_for_reading_only(
    api_client: Client, products_two: tuple[Product, Product]
):
    p1, _ = products_two
    url = f"{API}{p1.barcode}/estimate"

    assert api_client.post(url, {}, content_type="application/json").status_code == (
        HTTPStatus.METHOD_NOT_ALLOWED
    )
    assert api_client.delete(url).status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_an_ingredient_that_is_a_preparation_is_served_as_one(
    api_client: Client, products_two: tuple[Product, Product]
):
    product, _ = products_two
    mozzarella = Preparation.objects.create(name_en="mozzarella")
    Ingredient.objects.create(product=product, preparation=mozzarella)

    [ingredient] = api_client.get(f"{API}{product.barcode}").json()["ingredients"]

    assert ingredient["reference"] is None
    assert ingredient["preparation"] == {
        "id": mozzarella.pk,
        "name": "mozzarella",
        "status": "to_review",
    }


@pytest.mark.django_db
def test_an_ingredient_that_is_an_additive_is_served_as_one(
    api_client: Client, products_two: tuple[Product, Product]
):
    product, _ = products_two
    citric = Additive.objects.create(
        name_en="citric acid",
        code="E330",
        function=Additive.Function.ACID,
        status=Additive.Status.CURATED,
    )
    Ingredient.objects.create(product=product, additive=citric)

    [ingredient] = api_client.get(f"{API}{product.barcode}").json()["ingredients"]

    assert ingredient["reference"] is None
    assert ingredient["preparation"] is None
    assert ingredient["additive"] == {
        "id": citric.pk,
        "name": "citric acid",
        "code": "E330",
        "function": "acid",
        "status": "curated",
    }


# -----------------------
# The inventory of the user asking
# -----------------------
@pytest.mark.django_db
def test_the_inventory_is_each_users_own(
    api_client: Client, user: User, products_two: tuple[Product, Product]
):
    p1, p2 = products_two
    other = UserFactory()
    InventoryItem.objects.create(user=other, product=p2)

    assert api_client.get("/api/v1/inventory/").json() == []

    response = api_client.put(f"/api/v1/inventory/{p1.barcode}")

    assert response.status_code == HTTPStatus.OK
    assert response.json()["barcode"] == p1.barcode
    assert [i["barcode"] for i in api_client.get("/api/v1/inventory/").json()] == [
        p1.barcode
    ]
    # The list of products says which are in it, for the user asking only.
    listed = {p["barcode"]: p["in_inventory"] for p in api_client.get(API).json()}
    assert listed == {p1.barcode: True, p2.barcode: False}


@pytest.mark.django_db
def test_the_inventory_gives_the_food_groups_of_its_products(
    api_client: Client, user: User, products_two: tuple[Product, Product]
):
    p1, _ = products_two
    Product.objects.filter(pk=p1.pk).update(
        group_level_1="Fruits and vegetables", group_level_2="Fruits"
    )
    api_client.put(f"/api/v1/inventory/{p1.barcode}")

    found = api_client.get("/api/v1/inventory/").json()[0]

    assert found["group_level_1"] == "Fruits and vegetables"
    assert found["group_level_2"] == "Fruits"


@pytest.mark.django_db
def test_putting_a_product_in_twice_or_taking_one_out_twice_changes_nothing(
    api_client: Client, user: User, products_two: tuple[Product, Product]
):
    p1, _ = products_two

    api_client.put(f"/api/v1/inventory/{p1.barcode}")
    api_client.put(f"/api/v1/inventory/{p1.barcode}")
    assert InventoryItem.objects.filter(user=user).count() == 1

    for _ in range(2):
        response = api_client.delete(f"/api/v1/inventory/{p1.barcode}")
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"in_inventory": False}
    assert not InventoryItem.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_an_unknown_product_cannot_be_put_in_the_inventory(api_client: Client):
    assert api_client.put("/api/v1/inventory/3017620422003").status_code == 404  # noqa: PLR2004


@pytest.mark.django_db
def test_the_inventory_needs_a_signed_in_user(client: Client):
    assert client.get("/api/v1/inventory/").status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
def test_a_product_created_through_the_api_is_in_the_inventory_of_its_creator(
    api_client: Client, user: User
):
    payload = _minimal_payload("3297760097969", "Created Via API")

    api_client.post(API, payload, content_type="application/json")

    assert InventoryItem.objects.filter(
        user=user, product_id=payload["barcode"]
    ).exists()
