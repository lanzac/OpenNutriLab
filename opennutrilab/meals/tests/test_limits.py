from decimal import Decimal
from http import HTTPStatus

import pytest
from django.test import Client

from opennutrilab.meals.models import ItemLimits
from opennutrilab.meals.services import limits
from opennutrilab.meals.services.limits import NO_LIMITS
from opennutrilab.meals.services.limits import InvalidMealError
from opennutrilab.meals.services.limits import Limits
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
    stock(user, make_product(BARS, serving="45"), make_product(MUESLI))


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
