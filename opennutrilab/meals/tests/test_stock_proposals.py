"""
A day proposed from the inventory never uses more of a product than its stock holds.
"""

from datetime import date
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.test import Client

from opennutrilab.meals.models import Meal
from opennutrilab.meals.services import limits
from opennutrilab.meals.services import meal_services
from opennutrilab.meals.services import proposals
from opennutrilab.meals.services.limits import Limits
from opennutrilab.meals.services.proposals import StockLeft
from opennutrilab.meals.tests.conftest import make_product
from opennutrilab.meals.tests.conftest import make_profile
from opennutrilab.meals.tests.conftest import stock
from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Product
from opennutrilab.products.services import stock as stock_services
from opennutrilab.products.services.stored_estimates import Amount
from opennutrilab.users.models import User

pytestmark = pytest.mark.django_db

D = Decimal
BREAD = "3228857002245"
MUESLI = "3229820794556"
ON = date(2026, 10, 9)
ENERGY = {"energy": Amount(D(1233), D(1233), D(1233), D(100), declared=False)}
EVERY_DAY = Limits((), None, "", use_all=True)


def bread() -> Product:
    return Product(
        barcode=BREAD,
        name="Bread",
        serving_quantity=D("35.7"),
        serving_unit="g",
        package_quantity=D(375),
        package_unit="g",
    )


def count(user: User, product: Product, quantity: str | None) -> None:
    item = InventoryItem.objects.select_related("product").get(
        user=user, product=product
    )
    stock_services.set_stock(item, None if quantity is None else D(quantity))


# ----------------------------------------------------------------------------
# A product as the optimiser counts it
# ----------------------------------------------------------------------------
def test_what_is_left_caps_what_a_day_may_use():
    found = proposals.candidate_of(bread(), ENERGY, left=StockLeft(D(100)))

    assert found is not None
    # 6 servings of 35.7 g would be 214.2 g.
    assert found.max_grams == 100.0  # noqa: PLR2004


def test_a_stock_above_the_most_of_a_day_changes_nothing():
    found = proposals.candidate_of(bread(), ENERGY, left=StockLeft(D(900)))

    assert found is not None
    assert found.max_grams == pytest.approx(214.2)


def test_a_stock_not_counted_limits_nothing():
    counted = proposals.candidate_of(bread(), ENERGY, left=None)
    not_counted = proposals.candidate_of(bread(), ENERGY)

    assert counted == not_counted


def test_what_is_eaten_is_not_taken_off_the_stock_again():
    # The meals eaten took their share from the stock when they were eaten: only the
    # most of a day is what they come off.
    found = proposals.candidate_of(
        bread(), ENERGY, eaten_grams=D(100), left=StockLeft(D(300))
    )

    assert found is not None
    assert found.max_grams == pytest.approx(114.2)


def test_a_product_to_be_used_whole_is_a_package_or_what_is_left_of_it():
    two_packages = proposals.candidate_of(
        bread(), ENERGY, EVERY_DAY, left=StockLeft(D(750))
    )
    less_than_one = proposals.candidate_of(
        bread(), ENERGY, EVERY_DAY, left=StockLeft(D(200))
    )

    assert two_packages is not None
    assert two_packages.required_grams == 375.0  # noqa: PLR2004
    assert less_than_one is not None
    assert less_than_one.required_grams == 200.0  # noqa: PLR2004
    assert less_than_one.max_grams == 200.0  # noqa: PLR2004


# ----------------------------------------------------------------------------
# A day proposed
# ----------------------------------------------------------------------------
@pytest.fixture
def inventory(user: User, catalogue: None) -> list[Product]:
    products = [
        make_product(
            BREAD,
            serving="35.7",
            energy="1233",
            proteins="11",
            fat="8",
            carbohydrates="40",
        ),
        make_product(MUESLI, energy="1532", proteins="20", fat="9", carbohydrates="55"),
    ]
    stock(user, *products)
    make_profile(user)
    return products


def test_a_product_with_none_left_is_left_out_and_said_so(
    user: User, inventory: list[Product]
):
    bread_, muesli = inventory
    count(user, muesli, "0")

    loaded = proposals.load_inventory(user)
    proposal = proposals.propose_day(user, ON)

    assert {c.barcode for c in loaded.candidates} == {bread_.pk}
    assert [(s.barcode, s.reason) for s in loaded.skipped] == [
        (muesli.pk, proposals.OUT_OF_STOCK)
    ]
    assert muesli not in {item.product for item in proposal.items}
    assert (muesli.pk, proposals.OUT_OF_STOCK) in {
        (s.barcode, s.reason) for s in proposal.skipped
    }


def test_a_product_is_not_used_beyond_what_is_left_of_it(
    user: User, inventory: list[Product]
):
    _bread, muesli = inventory
    count(user, muesli, "30")

    proposal = proposals.propose_day(user, ON)

    used = sum(item.quantity for item in proposal.items if item.product == muesli)
    assert 0 < used <= D(30)


def test_a_product_not_counted_is_used_as_before(user: User, inventory: list[Product]):
    _bread, muesli = inventory
    count(user, muesli, None)

    loaded = proposals.load_inventory(user)

    candidate = next(c for c in loaded.candidates if c.barcode == muesli.pk)
    assert candidate.max_grams == 500.0  # noqa: PLR2004


def test_a_day_cannot_be_made_when_every_product_is_used_up(
    user: User, inventory: list[Product]
):
    for product in inventory:
        count(user, product, "0")

    proposal = proposals.propose_day(user, ON)

    assert (proposal.status, proposal.items) == ("no_candidates", [])
    assert {s.reason for s in proposal.skipped} == {proposals.OUT_OF_STOCK}


def test_a_product_left_out_by_the_user_is_not_said_to_be_used_up(
    user: User, inventory: list[Product]
):
    _bread, muesli = inventory
    count(user, muesli, "0")
    limits.set_limits(user, muesli, [], None, None, enabled=False)

    loaded = proposals.load_inventory(user)

    assert loaded.skipped == []


def test_the_meals_eaten_leave_the_rest_of_the_stock_to_the_day(
    user: User, inventory: list[Product]
):
    _bread, muesli = inventory
    count(user, muesli, "100")
    meal_services.add_item(user, date(2026, 10, 9), "breakfast", muesli, D(60), "g")
    meal_services.set_eaten(user, ON, "breakfast", eaten=True)

    proposal = proposals.propose_day(user, ON)

    # 40 g are left, and a day proposed does not use more of them.
    assert Meal.objects.get(user=user, kind="breakfast").eaten
    used = sum(item.quantity for item in proposal.items if item.product == muesli)
    assert used <= D(40)


# ----------------------------------------------------------------------------
# The API
# ----------------------------------------------------------------------------
def test_the_proposal_says_which_products_are_used_up(
    client: Client, user: User, inventory: list[Product]
):
    _bread, muesli = inventory
    count(user, muesli, "0")
    client.force_login(user)

    response = client.post("/api/v1/meals/2026-10-09/propose")

    assert response.status_code == HTTPStatus.OK
    assert {"barcode": muesli.pk, "name": muesli.name, "reason": "out_of_stock"} in (
        response.json()["skipped"]
    )


def test_a_meal_marked_eaten_through_the_api_takes_from_the_stock(
    client: Client, user: User, inventory: list[Product]
):
    _bread, muesli = inventory
    count(user, muesli, "375")
    client.force_login(user)
    client.post(
        "/api/v1/meals/2026-10-09/breakfast/items",
        {"barcode": muesli.pk, "quantity": "60", "unit": "g"},
        content_type="application/json",
    )

    eaten = client.patch(
        "/api/v1/meals/2026-10-09/breakfast",
        {"eaten": True},
        content_type="application/json",
    )
    assert eaten.status_code == HTTPStatus.OK
    after_eating = client.get("/api/v1/inventory/").json()
    client.patch(
        "/api/v1/meals/2026-10-09/breakfast",
        {"eaten": False},
        content_type="application/json",
    )
    after_undoing = client.get("/api/v1/inventory/").json()

    def stock_of(listing: list[dict]) -> dict:
        return next(i["stock"] for i in listing if i["barcode"] == muesli.pk)

    assert stock_of(after_eating) == {"quantity": "315.00", "unit": "g"}
    assert stock_of(after_undoing) == {"quantity": "375.00", "unit": "g"}


# ----------------------------------------------------------------------------
# A stock counted in servings
# ----------------------------------------------------------------------------
def test_a_stock_in_servings_is_counted_in_whole_servings():
    found = proposals.candidate_of(
        bread(), ENERGY, left=StockLeft(D("107.1"), in_servings=True)
    )

    assert found is not None
    assert (found.unit, found.step_quantity) == ("serving", 1.0)
    assert found.step_grams == pytest.approx(35.7)
    assert found.max_grams == pytest.approx(107.1)


def test_a_stock_in_grams_is_still_counted_in_half_servings():
    found = proposals.candidate_of(bread(), ENERGY, left=StockLeft(D(500)))

    assert found is not None
    assert found.step_quantity == 0.5  # noqa: PLR2004


@pytest.fixture
def compote(user: User, inventory: list[Product]) -> Product:
    """A compote in pots of 100 g, on top of the bread and the muesli."""
    product = make_product(
        "3333333333338", serving="100", package="400", energy="300", carbohydrates="14"
    )
    Product.objects.filter(pk=product.pk).update(serving_name="1 pot")
    product.refresh_from_db()
    stock(user, product)
    return product


def test_a_day_proposed_takes_whole_pots_and_no_more_than_are_left(
    user: User, compote: Product
):
    item = InventoryItem.objects.select_related("product").get(
        user=user, product=compote
    )
    stock_services.set_stock(item, D(2))

    loaded = proposals.load_inventory(user)
    proposal = proposals.propose_day(user, ON)

    candidate = next(c for c in loaded.candidates if c.barcode == compote.pk)
    assert (candidate.unit, candidate.step_quantity) == ("serving", 1.0)
    assert candidate.max_grams == 200.0  # noqa: PLR2004
    pots = [item for item in proposal.items if item.product == compote]
    assert {item.unit for item in pots} <= {"serving"}
    quantities = [item.quantity for item in pots]
    assert all(quantity == int(quantity) for quantity in quantities)
    assert sum(quantities) <= D(2)


def test_pots_that_are_all_gone_leave_the_product_out(user: User, compote: Product):
    item = InventoryItem.objects.select_related("product").get(
        user=user, product=compote
    )
    stock_services.set_stock(item, D(0))

    loaded = proposals.load_inventory(user)

    assert (compote.pk, proposals.OUT_OF_STOCK) in {
        (s.barcode, s.reason) for s in loaded.skipped
    }


def test_a_stock_counted_in_grams_of_a_product_with_pots_is_still_in_halves(
    user: User, compote: Product
):
    item = InventoryItem.objects.select_related("product").get(
        user=user, product=compote
    )
    stock_services.set_stock(item, D(250), "g")

    loaded = proposals.load_inventory(user)

    candidate = next(c for c in loaded.candidates if c.barcode == compote.pk)
    assert candidate.step_quantity == 0.5  # noqa: PLR2004
    assert candidate.max_grams == 250.0  # noqa: PLR2004
