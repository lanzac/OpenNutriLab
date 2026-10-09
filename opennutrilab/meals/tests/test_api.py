from decimal import Decimal
from http import HTTPStatus
from typing import Any

import pytest
from django.test import Client

from opennutrilab.meals.models import Meal
from opennutrilab.meals.models import MealItem
from opennutrilab.meals.models import Profile
from opennutrilab.meals.tests.conftest import make_product
from opennutrilab.meals.tests.conftest import stock
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

D = Decimal
DAY = "2026-10-09"
API = "/api/v1/meals/"
BREAD = "3228857002245"
MUESLI = "3229820794556"


@pytest.fixture
def api_client(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


@pytest.fixture
def products(user: User, catalogue: None) -> None:
    stock(
        user,
        make_product(BREAD, serving="35.7", energy="1233", proteins="11"),
        make_product(MUESLI, energy="1532", proteins="20"),
    )


def add(client: Client, kind: str, barcode: str, quantity: str, unit: str = "serving"):
    return client.post(
        f"{API}{DAY}/{kind}/items",
        {"barcode": barcode, "quantity": quantity, "unit": unit},
        content_type="application/json",
    )


def test_the_meals_need_a_signed_in_user(client: Client, db: None):
    assert client.get(f"{API}{DAY}").status_code == HTTPStatus.UNAUTHORIZED
    assert add(client, "lunch", BREAD, "1").status_code == HTTPStatus.UNAUTHORIZED


def test_an_empty_day_has_its_four_meals(api_client: Client, products: None):
    response = api_client.get(f"{API}{DAY}")

    assert response.status_code == HTTPStatus.OK
    day = response.json()
    assert day["day"] == DAY
    assert [meal["kind"] for meal in day["meals"]] == [
        "breakfast",
        "lunch",
        "snack",
        "dinner",
    ]
    assert day["meals"][0]["label"] == "Breakfast"
    assert day["totals"] == {}
    # No profile, no needs to set it against.
    assert (day["needs"], day["ratios"]) == (None, None)


def test_a_product_added_comes_back_with_the_day_it_makes(
    api_client: Client, products: None
):
    response = add(api_client, "breakfast", BREAD, "2")

    assert response.status_code == HTTPStatus.OK
    breakfast = response.json()["meals"][0]
    [item] = breakfast["items"]
    assert (item["barcode"], item["quantity"], item["unit"]) == (
        BREAD,
        "2.00",
        "serving",
    )
    assert D(item["grams"]) == D("71.4")
    assert item["serving"] == {"quantity": "35.70", "unit": "g", "name": ""}
    # 1233 kJ per 100 g, for 71.4 g.
    energy = breakfast["totals"]["energy"]
    assert round(float(energy["amount"]), 1) == 880.4  # noqa: PLR2004
    assert energy["coverage"].startswith("100")
    assert response.json()["nutrients"]["energy"] == {"name": "Energy", "unit": "kJ"}
    assert D(response.json()["mass"]) == D("71.4")


def test_grams_are_taken_for_a_product_with_no_serving(
    api_client: Client, products: None
):
    refused = add(api_client, "breakfast", MUESLI, "1")
    accepted = add(api_client, "breakfast", MUESLI, "60", "g")

    assert refused.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "no serving" in refused.json()["detail"]
    assert accepted.status_code == HTTPStatus.OK


def test_what_cannot_be_added_is_said(api_client: Client, products: None, user: User):
    stranger = make_product("5060088700112", energy="1")
    add(api_client, "breakfast", BREAD, "1")

    not_stocked = add(api_client, "lunch", stranger.pk, "1", "g")
    twice = add(api_client, "breakfast", BREAD, "1")
    unknown = add(api_client, "lunch", "3017620422003", "1", "g")
    bad_kind = add(api_client, "brunch", BREAD, "1")
    zero = add(api_client, "lunch", BREAD, "0")
    bad_unit = add(api_client, "lunch", BREAD, "1", "cups")

    assert not_stocked.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "inventory" in not_stocked.json()["detail"]
    assert twice.status_code == HTTPStatus.CONFLICT
    assert unknown.status_code == HTTPStatus.NOT_FOUND
    assert bad_kind.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert zero.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert bad_unit.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert MealItem.objects.count() == 1


def test_how_much_is_changed_and_a_product_taken_out(
    api_client: Client, products: None
):
    first = add(api_client, "breakfast", BREAD, "1").json()
    item_id = first["meals"][0]["items"][0]["id"]

    changed = api_client.patch(
        f"{API}items/{item_id}",
        {"quantity": "100", "unit": "g"},
        content_type="application/json",
    )
    no_serving = api_client.patch(
        f"{API}items/{item_id}",
        {"quantity": "2", "unit": "serving"},
        content_type="application/json",
    )

    assert changed.status_code == HTTPStatus.OK
    assert D(changed.json()["meals"][0]["items"][0]["grams"]) == D(100)
    assert D(changed.json()["mass"]) == D(100)
    assert no_serving.status_code == HTTPStatus.OK  # bread has a serving

    removed = api_client.delete(f"{API}items/{item_id}")

    assert removed.status_code == HTTPStatus.OK
    assert removed.json()["meals"][0]["items"] == []
    assert removed.json()["totals"] == {}


def test_a_change_to_servings_of_a_product_with_none_is_refused(
    api_client: Client, products: None
):
    item_id = add(api_client, "lunch", MUESLI, "60", "g").json()["meals"][1]["items"][
        0
    ]["id"]

    response = api_client.patch(
        f"{API}items/{item_id}",
        {"quantity": "1", "unit": "serving"},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert MealItem.objects.get().unit == "g"


def test_the_items_of_others_are_not_found(api_client: Client, products: None):
    other = UserFactory()
    meal = Meal.objects.create(user=other, date="2026-10-09", kind="lunch")
    item = MealItem.objects.create(
        meal=meal, product_id=BREAD, quantity=1, unit="serving"
    )

    changed = api_client.patch(
        f"{API}items/{item.pk}",
        {"quantity": "2", "unit": "g"},
        content_type="application/json",
    )
    removed = api_client.delete(f"{API}items/{item.pk}")

    assert changed.status_code == HTTPStatus.NOT_FOUND
    assert removed.status_code == HTTPStatus.NOT_FOUND
    assert MealItem.objects.get().quantity == 1


def test_a_day_is_set_against_the_needs_of_the_profile(
    api_client: Client, products: None, user: User
):
    Profile.objects.create(
        user=user,
        sex="male",
        birth_year=1995,
        height=180,
        weight=61,
        activity_level=1.7,
    )
    add(api_client, "breakfast", MUESLI, "200", "g")

    day: dict[str, Any] = api_client.get(f"{API}{DAY}").json()

    needs = {need["name"]: need for need in day["needs"]}
    energy = needs["Energy"]
    assert (energy["unit"], energy["status"], energy["certain"]) == (
        "kJ",
        "below",
        True,
    )
    assert energy["group_label"] == "Energy"
    assert round(float(energy["low"])) == 10536  # noqa: PLR2004
    assert energy["ends"] == ["Energy need (anses-2016)"]
    protein = needs["Protein"]
    assert (protein["share_low"], protein["share_high"]) == ("10", "20")
    assert D(protein["total"]["amount"]) == D(40)
    ratios = {(r["numerator"], r["denominator"]): r for r in day["ratios"]}
    assert len(ratios) == 4  # noqa: PLR2004
    molar = [r for r in day["ratios"] if r["molar"]]
    assert [r["numerator"] for r in molar] == ["Sodium"]
    assert all(r["status"] == "unknown" for r in day["ratios"] if r["value"] is None)
