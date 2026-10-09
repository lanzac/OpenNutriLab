from decimal import Decimal

import pytest

from opennutrilab.meals.models import Meal
from opennutrilab.meals.models import MealItem
from opennutrilab.meals.services import meal_services
from opennutrilab.meals.tests.conftest import DAY
from opennutrilab.meals.tests.conftest import make_product
from opennutrilab.meals.tests.conftest import stock
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

D = Decimal


@pytest.mark.django_db
def test_a_product_of_the_inventory_is_put_in_a_meal_made_for_it(user: User):
    product = make_product("1111111111116", serving="35.7")
    stock(user, product)

    item = meal_services.add_item(user, DAY, "breakfast", product, D("1.5"))

    meal = Meal.objects.get(user=user)
    assert (meal.date, meal.kind) == (DAY, "breakfast")
    assert (item.meal, item.quantity, item.unit) == (meal, D("1.5"), "serving")
    assert item.grams == D("53.55")


@pytest.mark.django_db
def test_two_products_share_a_meal(user: User):
    first, second = make_product("1111111111116"), make_product("2222222222222")
    stock(user, first, second)

    meal_services.add_item(user, DAY, "lunch", first, D(100), "g")
    meal_services.add_item(user, DAY, "lunch", second, D(50), "g")

    assert Meal.objects.count() == 1
    assert MealItem.objects.count() == 2  # noqa: PLR2004


@pytest.mark.django_db
def test_a_product_that_is_not_in_the_inventory_is_refused(user: User):
    product = make_product("1111111111116", serving="50")
    stock(UserFactory(), product)

    with pytest.raises(meal_services.NotInInventoryError):
        meal_services.add_item(user, DAY, "lunch", product, D(1))

    assert not Meal.objects.exists()


@pytest.mark.django_db
def test_servings_of_a_product_with_no_serving_are_refused_and_grams_are_not(
    user: User,
):
    product = make_product("1111111111116")
    stock(user, product)

    with pytest.raises(meal_services.NoServingError):
        meal_services.add_item(user, DAY, "lunch", product, D(1), "serving")
    assert not Meal.objects.exists()

    item = meal_services.add_item(user, DAY, "lunch", product, D(80), "g")
    assert item.grams == D(80)


@pytest.mark.django_db
def test_a_product_is_in_a_meal_once(user: User):
    product = make_product("1111111111116", serving="50")
    stock(user, product)
    meal_services.add_item(user, DAY, "lunch", product, D(1))

    with pytest.raises(meal_services.AlreadyInMealError):
        meal_services.add_item(user, DAY, "lunch", product, D(2))

    assert MealItem.objects.get().quantity == D(1)
    # It can be in another meal.
    meal_services.add_item(user, DAY, "dinner", product, D(2))
    assert MealItem.objects.count() == 2  # noqa: PLR2004


@pytest.mark.django_db
def test_how_much_is_changed_in_servings_or_grams(user: User):
    product = make_product("1111111111116", serving="50")
    stock(user, product)
    item = meal_services.add_item(user, DAY, "lunch", product, D(1))

    meal_services.change_item(item, D(120), "g")

    item.refresh_from_db()
    assert (item.quantity, item.unit, item.grams) == (D(120), "g", D(120))


@pytest.mark.django_db
def test_servings_cannot_be_asked_of_a_product_with_none_when_changing_either(
    user: User,
):
    product = make_product("1111111111116")
    stock(user, product)
    item = meal_services.add_item(user, DAY, "lunch", product, D(100), "g")

    with pytest.raises(meal_services.NoServingError):
        meal_services.change_item(item, D(2), "serving")

    item.refresh_from_db()
    assert (item.quantity, item.unit) == (D(100), "g")


@pytest.mark.django_db
def test_a_product_taken_out_leaves_the_meal(user: User):
    product = make_product("1111111111116")
    stock(user, product)
    item = meal_services.add_item(user, DAY, "lunch", product, D(100), "g")

    meal_services.remove_item(item)

    assert not MealItem.objects.exists()
    # The inventory is not touched by what is eaten.
    assert user.inventory.count() == 1  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.django_db
def test_a_product_deleted_leaves_the_meals_it_was_in(user: User):
    product = make_product("1111111111116")
    stock(user, product)
    meal_services.add_item(user, DAY, "lunch", product, D(100), "g")

    product.delete()

    assert not MealItem.objects.exists()
    assert Meal.objects.count() == 1


@pytest.mark.django_db
def test_a_quantity_of_nothing_is_refused_by_the_database(user: User):
    from django.db import IntegrityError
    from django.db import transaction

    product = make_product("1111111111116")
    stock(user, product)
    meal = Meal.objects.create(user=user, date=DAY, kind="lunch")

    with transaction.atomic(), pytest.raises(IntegrityError):
        MealItem.objects.create(meal=meal, product=product, quantity=0, unit="g")
