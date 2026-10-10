"""
The stock of the inventory follows the meals that are eaten: a meal that is eaten
takes what is in it, and gives it back when it is not eaten any more.
"""

from decimal import Decimal

import pytest

from opennutrilab.meals.models import MealItem
from opennutrilab.meals.models import StockTaken
from opennutrilab.meals.services import meal_services
from opennutrilab.meals.tests.conftest import DAY
from opennutrilab.meals.tests.conftest import make_product
from opennutrilab.meals.tests.conftest import stock
from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Product
from opennutrilab.products.services import stock as stock_services
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

D = Decimal


@pytest.fixture
def muesli(user: User) -> Product:
    """A muesli of 375 g that has no serving, and a stock of 375 g."""
    product = make_product("1111111111116", package="375", energy="1532")
    stock(user, product)
    stock_services.set_stock(InventoryItem.objects.get(user=user), D(375))
    return product


@pytest.fixture
def bread(user: User) -> Product:
    """A bread of 500 g with a serving of 35.7 g, and a stock of 500 g."""
    product = make_product(
        "2222222222222", serving="35.7", package="500", energy="1233"
    )
    stock(user, product)
    stock_services.set_stock(
        InventoryItem.objects.get(user=user, product=product), D(500)
    )
    return product


def left(user: User, product: Product) -> Decimal | None:
    return InventoryItem.objects.get(user=user, product=product).stock_quantity


def count(user: User, product: Product, quantity: str | None) -> None:
    item = InventoryItem.objects.select_related("product").get(
        user=user, product=product
    )
    stock_services.set_stock(item, None if quantity is None else D(quantity))


def count_in(user: User, product: Product, quantity: str, unit: str | None = None):
    item = InventoryItem.objects.select_related("product").get(
        user=user, product=product
    )
    stock_services.set_stock(item, D(quantity), unit)


# ----------------------------------------------------------------------------
# A meal eaten, and not
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_meal_that_is_planned_takes_nothing_from_the_stock(
    user: User, muesli: Product
):
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")

    assert left(user, muesli) == D(375)


@pytest.mark.django_db
def test_a_meal_marked_eaten_takes_what_is_in_it_from_the_stock(
    user: User, muesli: Product, bread: Product
):
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")
    meal_services.add_item(user, DAY, "breakfast", bread, D(2))

    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)

    assert left(user, muesli) == D(315)
    # Two servings of 35.7 g.
    assert left(user, bread) == D("428.60")


@pytest.mark.django_db
def test_a_meal_marked_not_eaten_again_gives_back_what_it_took(
    user: User, muesli: Product
):
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)

    meal_services.set_eaten(user, DAY, "breakfast", eaten=False)

    assert left(user, muesli) == D(375)
    assert not StockTaken.objects.exists()


@pytest.mark.django_db
def test_a_meal_marked_eaten_twice_takes_once(user: User, muesli: Product):
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")

    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)
    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)

    assert left(user, muesli) == D(315)


@pytest.mark.django_db
def test_a_meal_skipped_takes_nothing(user: User, muesli: Product):
    meal_services.set_eaten(user, DAY, "snack", eaten=True)

    assert left(user, muesli) == D(375)


@pytest.mark.django_db
def test_a_product_added_to_a_meal_that_is_eaten_takes_from_the_stock(
    user: User, muesli: Product
):
    meal_services.set_eaten(user, DAY, "lunch", eaten=True)

    meal_services.add_item(user, DAY, "lunch", muesli, D(100), "g")

    assert left(user, muesli) == D(275)


@pytest.mark.django_db
def test_a_product_taken_out_of_a_meal_that_is_eaten_gives_back(
    user: User, muesli: Product
):
    meal_services.add_item(user, DAY, "lunch", muesli, D(100), "g")
    meal_services.set_eaten(user, DAY, "lunch", eaten=True)
    item = MealItem.objects.select_related("meal", "product").get()

    meal_services.remove_item(item)

    assert left(user, muesli) == D(375)
    assert not StockTaken.objects.exists()


@pytest.mark.django_db
def test_a_product_taken_out_of_a_meal_not_eaten_leaves_the_stock(
    user: User, muesli: Product
):
    meal_services.add_item(user, DAY, "lunch", muesli, D(100), "g")
    item = MealItem.objects.select_related("meal", "product").get()

    meal_services.remove_item(item)

    assert left(user, muesli) == D(375)


@pytest.mark.django_db
@pytest.mark.parametrize(("quantity", "stock_left"), [(80, 295), (30, 345)])
def test_more_or_less_of_a_product_eaten_takes_or_gives_the_difference(
    user: User, muesli: Product, quantity: int, stock_left: int
):
    meal_services.add_item(user, DAY, "lunch", muesli, D(50), "g")
    meal_services.set_eaten(user, DAY, "lunch", eaten=True)
    item = MealItem.objects.select_related("meal", "product").get()

    meal_services.change_item(item, D(quantity), "g")

    assert left(user, muesli) == D(stock_left)
    assert StockTaken.objects.get().quantity == D(quantity)


@pytest.mark.django_db
def test_the_unit_of_an_item_eaten_can_change(user: User, bread: Product):
    meal_services.add_item(user, DAY, "lunch", bread, D(2))
    meal_services.set_eaten(user, DAY, "lunch", eaten=True)
    item = MealItem.objects.select_related("meal", "product").get()

    # 100 g in place of two servings of 35.7 g.
    meal_services.change_item(item, D(100), "g")

    assert left(user, bread) == D(400)


@pytest.mark.django_db
def test_an_item_changed_in_a_meal_not_eaten_leaves_the_stock(
    user: User, muesli: Product
):
    meal_services.add_item(user, DAY, "lunch", muesli, D(50), "g")
    item = MealItem.objects.select_related("meal", "product").get()

    meal_services.change_item(item, D(80), "g")

    assert left(user, muesli) == D(375)


# ----------------------------------------------------------------------------
# What the stock holds
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_stock_stops_at_nothing_and_gives_back_only_what_it_gave(
    user: User, muesli: Product
):
    count(user, muesli, "50")
    meal_services.add_item(user, DAY, "lunch", muesli, D(80), "g")

    meal_services.set_eaten(user, DAY, "lunch", eaten=True)

    assert left(user, muesli) == D(0)
    assert StockTaken.objects.get().quantity == D(50)

    meal_services.set_eaten(user, DAY, "lunch", eaten=False)

    assert left(user, muesli) == D(50)


@pytest.mark.django_db
def test_a_product_with_no_stock_counted_is_not_taken_from(user: User):
    product = make_product("1111111111116", energy="1532")
    stock(user, product)
    meal_services.add_item(user, DAY, "lunch", product, D(80), "g")

    meal_services.set_eaten(user, DAY, "lunch", eaten=True)
    meal_services.set_eaten(user, DAY, "lunch", eaten=False)

    assert left(user, product) is None
    assert not StockTaken.objects.exists()


@pytest.mark.django_db
def test_a_serving_of_a_product_with_none_takes_nothing(user: User):
    product = make_product("1111111111116", serving="30", energy="1532")
    stock(user, product)
    count(user, product, "300")
    meal_services.add_item(user, DAY, "lunch", product, D(2))
    Product.objects.filter(pk=product.pk).update(serving_quantity=None, serving_unit="")

    meal_services.set_eaten(user, DAY, "lunch", eaten=True)

    assert left(user, product) == D(300)


@pytest.mark.django_db
def test_a_stock_in_ml_is_taken_from_by_the_density_of_the_product(user: User):
    oil = make_product("3270190008262", serving="14", energy="3700")
    Product.objects.filter(pk=oil.pk).update(
        package_quantity=D(1000), package_unit="ml", serving_unit="ml"
    )
    oil.refresh_from_db()
    stock(user, oil)
    count(user, oil, "500")
    meal_services.add_item(user, DAY, "lunch", oil, D(2))

    meal_services.set_eaten(user, DAY, "lunch", eaten=True)

    # No density is known: two servings of 14 ml weigh 28 g, which are 28 ml.
    assert left(user, oil) == D(472)


# ----------------------------------------------------------------------------
# A count is the truth as of then
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_meal_eaten_before_the_stock_was_counted_is_in_the_count(
    user: User, muesli: Product
):
    count(user, muesli, None)
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)

    # The user counts what is there after the breakfast.
    count(user, muesli, "300")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=False)

    # It took nothing, so it gives nothing: the 300 g are what is there.
    assert left(user, muesli) == D(300)


@pytest.mark.django_db
def test_a_meal_eaten_then_counted_since_gives_nothing_back(
    user: User, muesli: Product
):
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)
    assert left(user, muesli) == D(315)

    count(user, muesli, "300")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=False)

    assert left(user, muesli) == D(300)
    assert not StockTaken.objects.exists()


@pytest.mark.django_db
def test_an_item_eaten_before_a_count_is_left_alone_when_it_changes(
    user: User, muesli: Product
):
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)
    count(user, muesli, "300")
    item = MealItem.objects.select_related("meal", "product").get()

    meal_services.change_item(item, D(90), "g")
    meal_services.remove_item(item)

    assert left(user, muesli) == D(300)


@pytest.mark.django_db
def test_an_item_eaten_before_stock_existed_is_left_alone_when_it_changes(
    user: User,
):
    product = make_product("1111111111116", energy="1532")
    stock(user, product)
    meal_services.add_item(user, DAY, "breakfast", product, D(60), "g")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)
    count(user, product, "300")
    item = MealItem.objects.select_related("meal", "product").get()

    meal_services.change_item(item, D(90), "g")

    assert left(user, product) == D(300)


@pytest.mark.django_db
def test_a_meal_eaten_again_after_a_count_takes_from_that_count(
    user: User, muesli: Product
):
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)
    count(user, muesli, "300")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=False)

    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)

    assert left(user, muesli) == D(240)


# ----------------------------------------------------------------------------
# Whose stock, and what else writes meals
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_meals_of_a_user_take_from_their_own_stock_only(
    user: User, muesli: Product
):
    other = UserFactory()
    stock(other, muesli)
    count(other, muesli, "375")
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")

    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)

    assert left(user, muesli) == D(315)
    assert left(other, muesli) == D(375)


@pytest.mark.django_db
def test_a_product_taken_out_of_the_inventory_leaves_the_meal_to_change(
    user: User, muesli: Product
):
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)
    InventoryItem.objects.filter(user=user).delete()

    meal_services.set_eaten(user, DAY, "breakfast", eaten=False)

    assert not StockTaken.objects.exists()


@pytest.mark.django_db
def test_a_product_put_back_in_the_inventory_does_not_get_what_was_eaten_before(
    user: User, muesli: Product
):
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)
    InventoryItem.objects.filter(user=user).delete()
    stock(user, muesli)
    count(user, muesli, "200")

    meal_services.set_eaten(user, DAY, "breakfast", eaten=False)

    assert left(user, muesli) == D(200)


@pytest.mark.django_db
def test_putting_a_day_in_place_leaves_the_stock_and_the_meals_eaten(
    user: User, muesli: Product, bread: Product
):
    meal_services.add_item(user, DAY, "breakfast", muesli, D(60), "g")
    meal_services.set_eaten(user, DAY, "breakfast", eaten=True)
    meal_services.add_item(user, DAY, "dinner", bread, D(2))

    meal_services.replace_day(user, DAY, [("lunch", bread, D(4), "serving")])

    assert left(user, muesli) == D(315)
    assert left(user, bread) == D(500)
    assert StockTaken.objects.count() == 1


# ----------------------------------------------------------------------------
# A stock counted in servings: pots, slices, which are whole
# ----------------------------------------------------------------------------
@pytest.fixture
def compote(user: User) -> Product:
    """A compote of 400 g in pots of 100 g, and a stock of 4 pots."""
    product = make_product("3333333333338", serving="100", package="400", energy="300")
    Product.objects.filter(pk=product.pk).update(serving_name="1 pot")
    product.refresh_from_db()
    stock(user, product)
    item = InventoryItem.objects.select_related("product").get(
        user=user, product=product
    )
    stock_services.set_stock(item, D(4))
    assert item.stock_unit == "serving"
    return product


@pytest.mark.django_db
def test_a_serving_eaten_takes_a_pot_and_gives_it_back(user: User, compote: Product):
    meal_services.add_item(user, DAY, "lunch", compote, D(1))

    meal_services.set_eaten(user, DAY, "lunch", eaten=True)

    assert left(user, compote) == D(3)
    assert StockTaken.objects.get().quantity == D(1)

    meal_services.set_eaten(user, DAY, "lunch", eaten=False)

    assert left(user, compote) == D(4)


@pytest.mark.django_db
def test_two_servings_take_two_pots(user: User, compote: Product):
    meal_services.add_item(user, DAY, "lunch", compote, D(2))

    meal_services.set_eaten(user, DAY, "lunch", eaten=True)

    assert left(user, compote) == D(2)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("grams", "pots"), [("100", 1), ("200", 2), ("150", 2), ("30", 1), ("401", 5)]
)
def test_grams_eaten_take_the_pots_they_need_and_a_pot_opened_is_gone(
    user: User, compote: Product, grams: str, pots: int
):
    meal_services.add_item(user, DAY, "lunch", compote, D(grams), "g")

    meal_services.set_eaten(user, DAY, "lunch", eaten=True)

    assert left(user, compote) == max(D(4) - pots, D(0))


@pytest.mark.django_db
def test_half_a_serving_takes_a_whole_pot(user: User, compote: Product):
    meal_services.add_item(user, DAY, "lunch", compote, D("0.5"))

    meal_services.set_eaten(user, DAY, "lunch", eaten=True)

    assert left(user, compote) == D(3)


@pytest.mark.django_db
def test_slices_in_grams_are_counted_whole_whatever_the_decimals(user: User):
    bread = make_product("2222222222222", serving="35.7", package="500", energy="1233")
    Product.objects.filter(pk=bread.pk).update(serving_name="1 tranche")
    bread.refresh_from_db()
    stock(user, bread)
    count_in(user, bread, "14")
    meal_services.add_item(user, DAY, "lunch", bread, D("107.1"), "g")

    meal_services.set_eaten(user, DAY, "lunch", eaten=True)

    # 107.1 g are three slices of 35.7 g, not three and a hair.
    assert left(user, bread) == D(11)


@pytest.mark.django_db
def test_more_or_fewer_servings_of_a_meal_eaten_take_or_give_pots(
    user: User, compote: Product
):
    meal_services.add_item(user, DAY, "lunch", compote, D(1))
    meal_services.set_eaten(user, DAY, "lunch", eaten=True)
    item = MealItem.objects.select_related("meal", "product").get()

    meal_services.change_item(item, D(3), "serving")
    assert left(user, compote) == D(1)

    meal_services.change_item(item, D(1), "serving")
    assert left(user, compote) == D(3)


@pytest.mark.django_db
def test_pots_stop_at_nothing_and_give_back_only_what_they_gave(
    user: User, compote: Product
):
    meal_services.add_item(user, DAY, "lunch", compote, D(6))

    meal_services.set_eaten(user, DAY, "lunch", eaten=True)

    assert left(user, compote) == D(0)
    assert StockTaken.objects.get().quantity == D(4)

    meal_services.set_eaten(user, DAY, "lunch", eaten=False)

    assert left(user, compote) == D(4)


@pytest.mark.django_db
def test_pots_given_back_are_the_pots_taken_whatever_the_serving_became(
    user: User, compote: Product
):
    meal_services.add_item(user, DAY, "lunch", compote, D(2))
    meal_services.set_eaten(user, DAY, "lunch", eaten=True)
    Product.objects.filter(pk=compote.pk).update(serving_quantity=D(125))

    meal_services.set_eaten(user, DAY, "lunch", eaten=False)

    assert left(user, compote) == D(4)


@pytest.mark.django_db
def test_a_count_in_another_unit_is_a_new_count(user: User, compote: Product):
    meal_services.add_item(user, DAY, "lunch", compote, D(1))
    meal_services.set_eaten(user, DAY, "lunch", eaten=True)
    item = InventoryItem.objects.select_related("product").get(user=user)

    # The user now weighs what is left: 300 g, counted in grams.
    stock_services.set_stock(item, D(300), "g")
    meal_services.set_eaten(user, DAY, "lunch", eaten=False)

    # The pot taken was in the first count: nothing is given back to the second.
    item.refresh_from_db()
    assert (item.stock_quantity, item.stock_unit) == (D(300), "g")


@pytest.mark.django_db
def test_grams_of_a_product_counted_in_pots_without_a_serving_take_nothing(
    user: User, compote: Product
):
    meal_services.add_item(user, DAY, "lunch", compote, D(100), "g")
    Product.objects.filter(pk=compote.pk).update(
        serving_quantity=None, serving_unit="", serving_name=""
    )

    meal_services.set_eaten(user, DAY, "lunch", eaten=True)

    assert left(user, compote) == D(4)
