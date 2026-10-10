from decimal import Decimal
from http import HTTPStatus

import pytest
from django.db import IntegrityError
from django.db import transaction
from django.test import Client

from opennutrilab.meals.models import ItemLimits
from opennutrilab.meals.services import limits
from opennutrilab.meals.services.limits import NO_LIMITS
from opennutrilab.meals.services.limits import InvalidMealError
from opennutrilab.meals.services.limits import Limits
from opennutrilab.meals.services.limits import NoPackageError
from opennutrilab.meals.services.meal_services import NoServingError
from opennutrilab.meals.services.meal_services import NotInInventoryError
from opennutrilab.meals.tests.conftest import make_product
from opennutrilab.meals.tests.conftest import stock
from opennutrilab.products.models import InventoryItem
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

D = Decimal
BARS = "5060088700112"
MUESLI = "3229820794556"


@pytest.fixture
def products(user: User, db: None) -> None:
    stock(user, make_product(BARS, serving="45", package="135"), make_product(MUESLI))


@pytest.mark.django_db
def test_a_product_with_no_limits_has_none(user: User, products: None):
    assert limits.limits_of(user) == {}


@pytest.mark.django_db
def test_the_meals_a_product_may_be_in_and_the_most_of_it_are_kept(
    user: User, products: None
):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product

    found = limits.set_limits(user, bars, ["snack", "breakfast"], D(2), "serving")

    # In the order of a day, whatever order they were given in.
    assert found == Limits(("breakfast", "snack"), D(2), "serving")
    assert limits.limits_of(user) == {BARS: found}


@pytest.mark.django_db
def test_allowing_every_meal_with_no_most_is_having_no_limits(
    user: User, products: None
):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product
    limits.set_limits(user, bars, ["snack"], None, None)

    cleared = limits.set_limits(
        user, bars, ["breakfast", "lunch", "snack", "dinner"], None, None
    )

    assert cleared == NO_LIMITS
    assert not ItemLimits.objects.exists()


@pytest.mark.django_db
def test_every_meal_with_a_most_keeps_the_most_and_means_any_meal(
    user: User, products: None
):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product

    found = limits.set_limits(
        user, bars, ["breakfast", "lunch", "snack", "dinner"], D(90), "g"
    )

    assert found == Limits((), D(90), "g")


@pytest.mark.django_db
def test_a_unit_with_no_quantity_is_no_most(user: User, products: None):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product

    found = limits.set_limits(user, bars, ["snack"], None, "g")

    assert found == Limits(("snack",), None, "")


@pytest.mark.django_db
def test_servings_cannot_be_the_unit_of_a_most_for_a_product_with_none(
    user: User, products: None
):
    muesli = InventoryItem.objects.get(user=user, product_id=MUESLI).product

    with pytest.raises(NoServingError):
        limits.set_limits(user, muesli, [], D(2), "serving")

    assert limits.set_limits(user, muesli, [], D(80), "g") == Limits((), D(80), "g")


@pytest.mark.django_db
def test_a_kind_of_meal_that_does_not_exist_is_refused(user: User, products: None):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product

    with pytest.raises(InvalidMealError, match="brunch"):
        limits.set_limits(user, bars, ["brunch"], None, None)


@pytest.mark.django_db
def test_limits_are_for_the_products_of_the_inventory(user: User, products: None):
    stranger = make_product("3017620422003")

    with pytest.raises(NotInInventoryError):
        limits.set_limits(user, stranger, ["lunch"], None, None)


@pytest.mark.django_db
def test_limits_go_with_the_product_taken_out_of_the_inventory(
    user: User, products: None
):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product
    limits.set_limits(user, bars, ["snack"], None, None)

    InventoryItem.objects.filter(user=user, product=bars).delete()

    assert not ItemLimits.objects.exists()


@pytest.mark.django_db
def test_limits_are_each_users_own(user: User, products: None):
    other = UserFactory()
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product
    stock(other, bars)
    limits.set_limits(user, bars, ["snack"], None, None)

    assert limits.limits_of(other) == {}


# ----------------------------------------------------------------------------
# The whole package
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_whole_package_can_be_asked_for_of_a_product_that_has_one(
    user: User, products: None
):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product

    found = limits.set_limits(user, bars, ["lunch", "dinner"], None, None, use_all=True)

    assert found == Limits(("lunch", "dinner"), None, "", use_all=True)
    assert limits.limits_of(user) == {BARS: found}


@pytest.mark.django_db
def test_the_whole_package_is_asked_for_with_every_meal_too(user: User, products: None):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product

    found = limits.set_limits(user, bars, [], None, None, use_all=True)

    # Not "no limits": the row is kept, as it says something.
    assert found == Limits((), None, "", use_all=True)
    assert ItemLimits.objects.get().use_all


@pytest.mark.django_db
def test_the_whole_package_takes_the_place_of_a_most(user: User, products: None):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product
    limits.set_limits(user, bars, [], D(2), "serving")

    found = limits.set_limits(user, bars, [], D(2), "serving", use_all=True)

    assert found == Limits((), None, "", use_all=True)
    kept = ItemLimits.objects.get()
    assert (kept.max_quantity, kept.max_unit, kept.use_all) == (None, "", True)


@pytest.mark.django_db
def test_a_product_with_no_total_quantity_cannot_be_asked_for_whole(
    user: User, products: None
):
    muesli = InventoryItem.objects.get(user=user, product_id=MUESLI).product

    with pytest.raises(NoPackageError):
        limits.set_limits(user, muesli, [], None, None, use_all=True)

    assert not ItemLimits.objects.exists()


@pytest.mark.django_db
def test_not_asking_for_the_whole_package_any_more_clears_a_row_with_nothing_else(
    user: User, products: None
):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product
    limits.set_limits(user, bars, [], None, None, use_all=True)

    cleared = limits.set_limits(user, bars, [], None, None)

    assert cleared == NO_LIMITS
    assert not ItemLimits.objects.exists()


@pytest.mark.django_db
def test_the_database_does_not_keep_a_most_with_the_whole_package(
    user: User, products: None
):
    item = InventoryItem.objects.get(user=user, product_id=BARS)

    with pytest.raises(IntegrityError), transaction.atomic():
        ItemLimits.objects.create(
            inventory_item=item, max_quantity=D(2), max_unit="g", use_all=True
        )


# ----------------------------------------------------------------------------
# The API
# ----------------------------------------------------------------------------
API = "/api/v1/meals/limits/"


@pytest.fixture
def api_client(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def put(client: Client, barcode: str, **body: object):
    return client.put(f"{API}{barcode}", body, content_type="application/json")


@pytest.mark.django_db
def test_the_limits_are_set_served_and_cleared(api_client: Client, products: None):
    assert api_client.get(API).json() == []

    response = put(
        api_client,
        BARS,
        meals=["snack", "breakfast"],
        max_quantity="2",
        max_unit="serving",
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "barcode": BARS,
        "meals": ["breakfast", "snack"],
        "max_quantity": "2.00",
        "max_unit": "serving",
        "use_all": False,
        "enabled": True,
    }
    assert api_client.get(API).json() == [response.json()]

    cleared = put(api_client, BARS, meals=[])

    assert cleared.json()["meals"] == []
    assert api_client.get(API).json() == []


@pytest.mark.django_db
def test_what_cannot_be_set_is_said(api_client: Client, products: None):
    stranger = make_product("3017620422003")

    not_stocked = put(api_client, stranger.pk, meals=["lunch"])
    unknown = put(api_client, "9999999999999", meals=["lunch"])
    no_serving = put(api_client, MUESLI, max_quantity="2", max_unit="serving")
    bad_meal = put(api_client, BARS, meals=["brunch"])
    zero = put(api_client, BARS, max_quantity="0", max_unit="g")

    assert not_stocked.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert unknown.status_code == HTTPStatus.NOT_FOUND
    assert no_serving.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert bad_meal.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert zero.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_the_limits_need_a_signed_in_user(client: Client, products: None):
    assert client.get(API).status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
def test_the_whole_package_is_set_and_served(api_client: Client, products: None):
    response = put(api_client, BARS, meals=["lunch"], use_all=True)

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "barcode": BARS,
        "meals": ["lunch"],
        "max_quantity": None,
        "max_unit": "",
        "use_all": True,
        "enabled": True,
    }
    assert api_client.get(API).json() == [response.json()]


@pytest.mark.django_db
def test_the_whole_package_of_a_product_with_none_is_refused(
    api_client: Client, products: None
):
    response = put(api_client, MUESLI, meals=[], use_all=True)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "total quantity" in response.json()["detail"]
    assert api_client.get(API).json() == []


# ----------------------------------------------------------------------------
# A product left out of the days proposed
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_product_is_in_use_unless_it_was_left_out(user: User, products: None):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product

    assert NO_LIMITS.enabled
    found = limits.set_limits(user, bars, [], None, None, enabled=False)

    # Left out with nothing else set is still something to keep.
    assert found == Limits((), None, "", enabled=False)
    assert limits.limits_of(user) == {BARS: found}


@pytest.mark.django_db
def test_a_product_left_out_keeps_the_rest_for_when_it_is_back(
    user: User, products: None
):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product
    limits.set_limits(user, bars, ["snack"], D(2), "serving")

    limits.set_limits(user, bars, ["snack"], D(2), "serving", enabled=False)
    back = limits.set_limits(user, bars, ["snack"], D(2), "serving")

    assert back == Limits(("snack",), D(2), "serving")


@pytest.mark.django_db
def test_putting_a_product_back_with_nothing_else_set_clears_its_row(
    user: User, products: None
):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product
    limits.set_limits(user, bars, [], None, None, enabled=False)

    back = limits.set_limits(user, bars, [], None, None)

    assert back == NO_LIMITS
    assert not ItemLimits.objects.exists()


@pytest.mark.django_db
def test_leaving_every_product_out_keeps_what_was_set_of_each(
    user: User, products: None
):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product
    limits.set_limits(user, bars, ["snack"], D(2), "serving")

    found = limits.set_all_enabled(user, enabled=False)

    assert found == {
        BARS: Limits(("snack",), D(2), "serving", enabled=False),
        MUESLI: Limits((), None, "", enabled=False),
    }


@pytest.mark.django_db
def test_putting_every_product_back_keeps_the_limits_and_drops_the_empty_rows(
    user: User, products: None
):
    bars = InventoryItem.objects.get(user=user, product_id=BARS).product
    limits.set_limits(user, bars, ["snack"], D(2), "serving")
    limits.set_all_enabled(user, enabled=False)

    found = limits.set_all_enabled(user, enabled=True)

    assert found == {BARS: Limits(("snack",), D(2), "serving")}
    assert ItemLimits.objects.count() == 1


@pytest.mark.django_db
def test_switching_every_product_is_each_users_own(user: User, products: None):
    other = UserFactory()
    stock(other, make_product("3017620422003"))

    limits.set_all_enabled(user, enabled=False)

    assert limits.limits_of(other) == {}


@pytest.mark.django_db
def test_a_product_left_out_is_set_and_served(api_client: Client, products: None):
    response = put(api_client, BARS, meals=["lunch"], enabled=False)

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "barcode": BARS,
        "meals": ["lunch"],
        "max_quantity": None,
        "max_unit": "",
        "use_all": False,
        "enabled": False,
    }
    assert api_client.get(API).json() == [response.json()]
    # A request that says nothing of it puts the product back.
    assert put(api_client, BARS, meals=["lunch"]).json()["enabled"] is True


@pytest.mark.django_db
def test_every_product_is_left_out_or_put_back_in_one_request(
    api_client: Client, products: None
):
    off = api_client.put(API, {"enabled": False}, content_type="application/json")

    assert off.status_code == HTTPStatus.OK
    assert {found["barcode"]: found["enabled"] for found in off.json()} == {
        BARS: False,
        MUESLI: False,
    }
    assert api_client.get(API).json() == off.json()

    on = api_client.put(API, {"enabled": True}, content_type="application/json")

    assert on.json() == []
    assert api_client.get(API).json() == []


@pytest.mark.django_db
def test_switching_every_product_needs_a_signed_in_user(client: Client, products: None):
    response = client.put(API, {"enabled": False}, content_type="application/json")

    assert response.status_code == HTTPStatus.UNAUTHORIZED
