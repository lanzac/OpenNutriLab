from decimal import Decimal

import pytest

from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Product
from opennutrilab.products.services import stock
from opennutrilab.users.models import User

pytestmark = pytest.mark.django_db

D = Decimal


def item_of(  # noqa: PLR0913
    user: User,
    *,
    package: str | None = "500",
    unit: str = "g",
    serving: str | None = None,
    name: str = "",
    barcode: str = "3017620422003",
) -> InventoryItem:
    product = Product.objects.create(
        barcode=barcode,
        name="Muesli",
        package_quantity=None if package is None else D(package),
        package_unit="" if package is None else unit,
        serving_quantity=None if serving is None else D(serving),
        serving_unit="" if serving is None else unit,
        serving_name=name,
    )
    return InventoryItem.objects.create(user=user, product=product)


def pots_of(user: User) -> InventoryItem:
    """A compote of 400 g in pots of 100 g."""
    return item_of(user, package="400", serving="100", name="1 pot")


def with_density(item: InventoryItem, low: str, high: str) -> None:
    """The density the product's kept estimate gives (Product.density)."""
    vars(item.product)["density"] = (D(low), D(high))


# ----------------------------------------------------------------------------
# What a serving is called
# ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "noun"),
    [
        ("1 pot", "pot"),
        ("1 tranche", "tranche"),
        ("1 bouteille", "bouteille"),
        ("1 oeuf", "oeuf"),
        ("un sachet", "sachet"),
        ("1 tranche de pain", "tranche de pain"),
        ("1 Pot", "Pot"),
        # A measure is not a thing that is counted.
        ("1 portion", None),
        ("1 cs", None),
        ("1 cuillère à soupe", None),
        ("1 part", None),
        # Nor is a serving of several things, which the pot of one is not the unit of.
        ("2 biscuits", None),
        ("3 tranches", None),
        ("", None),
        ("pot", None),
    ],
)
def test_a_serving_is_counted_by_what_the_label_calls_it_when_it_is_a_thing(
    user: User, name: str, noun: str | None
):
    item = item_of(user, serving="100", name=name)

    assert stock.counting_noun(item.product) == noun


def test_a_product_with_no_serving_has_nothing_to_count_by(user: User):
    item = item_of(user)
    item.product.serving_name = "1 pot"

    assert stock.counting_noun(item.product) is None


def test_a_stock_is_counted_in_servings_when_the_label_names_them(user: User):
    assert stock.default_unit(pots_of(user).product) == "serving"


def test_a_stock_is_counted_in_grams_when_the_serving_has_no_name(user: User):
    pasta = item_of(user, package="1000", serving="80")

    assert stock.default_unit(pasta.product) == "g"


def test_a_stock_is_counted_in_grams_when_the_name_is_a_measure(user: User):
    item = item_of(user, package="450", serving="25", name="1 portion")

    assert stock.default_unit(item.product) == "g"


def test_a_stock_is_counted_in_the_unit_of_the_package_otherwise(user: User):
    oil = item_of(user, package="1000", unit="ml")

    assert stock.default_unit(oil.product) == "ml"


# ----------------------------------------------------------------------------
# Counting a stock
# ----------------------------------------------------------------------------
def test_a_stock_is_counted_in_the_unit_of_the_package_until_told_otherwise(
    user: User,
):
    item = item_of(user, package="1000", unit="ml")

    stock.set_stock(item, D(400))

    item.refresh_from_db()
    assert (item.stock_quantity, item.stock_unit) == (D(400), "ml")
    assert item.counted_at is not None


def test_a_product_with_no_package_is_counted_in_grams(user: User):
    item = item_of(user, package=None)

    stock.set_stock(item, D("37.5"))

    item.refresh_from_db()
    assert (item.stock_quantity, item.stock_unit) == (D("37.50"), "g")


def test_a_stock_keeps_the_unit_it_was_counted_in(user: User):
    item = item_of(user, package="1000", unit="ml")
    stock.set_stock(item, D(400), "g")

    stock.set_stock(item, D(300))

    assert item.stock_unit == "g"


def test_pots_are_counted_as_servings_by_default(user: User):
    item = pots_of(user)

    stock.set_stock(item, D(4))

    item.refresh_from_db()
    assert (item.stock_quantity, item.stock_unit) == (D(4), "serving")


def test_a_product_with_pots_can_still_be_counted_in_grams(user: User):
    item = pots_of(user)

    stock.set_stock(item, D(250), "g")

    item.refresh_from_db()
    assert (item.stock_quantity, item.stock_unit) == (D(250), "g")


def test_a_stock_used_up_is_nothing_and_not_unknown(user: User):
    item = item_of(user)

    stock.set_stock(item, D(0))

    item.refresh_from_db()
    assert item.stock_quantity == D(0)
    assert stock.grams_in_stock(item) == D(0)


def test_a_stock_can_be_left_uncounted_again(user: User):
    item = item_of(user)
    stock.set_stock(item, D(200))

    stock.set_stock(item, None)

    item.refresh_from_db()
    assert (item.stock_quantity, item.stock_unit, item.counted_at) == (None, "", None)
    assert stock.grams_in_stock(item) is None


@pytest.mark.parametrize(("quantity", "unit"), [(D(-1), None), (D(5), "kg")])
def test_a_stock_below_nothing_or_in_another_unit_is_refused(
    user: User, quantity: Decimal, unit: str | None
):
    item = item_of(user)

    with pytest.raises(stock.InvalidStockError):
        stock.set_stock(item, quantity, unit)

    item.refresh_from_db()
    assert item.stock_quantity is None


def test_servings_are_not_cut(user: User):
    item = pots_of(user)

    with pytest.raises(stock.InvalidStockError):
        stock.set_stock(item, D("2.5"))

    item.refresh_from_db()
    assert item.stock_quantity is None


def test_servings_need_a_product_that_has_one(user: User):
    item = item_of(user)

    with pytest.raises(stock.InvalidStockError):
        stock.set_stock(item, D(2), "serving")


# ----------------------------------------------------------------------------
# What it weighs
# ----------------------------------------------------------------------------
def test_pots_weigh_what_a_serving_does(user: User):
    item = pots_of(user)
    stock.set_stock(item, D(3))

    assert stock.grams_in_stock(item) == D(300)


def test_servings_of_a_product_that_has_lost_its_serving_weigh_nothing_known(
    user: User,
):
    item = pots_of(user)
    stock.set_stock(item, D(3))
    Product.objects.filter(pk=item.product_id).update(
        serving_quantity=None, serving_unit="", serving_name=""
    )
    item.refresh_from_db()

    assert stock.grams_in_stock(item) is None


def test_a_stock_in_ml_weighs_what_the_density_says(user: User):
    item = item_of(user, package="1000", unit="ml")
    with_density(item, "0.908", "0.912")
    stock.set_stock(item, D(500))

    assert stock.grams_in_stock(item) == D("455.00")


def test_a_millilitre_counts_as_a_gram_where_no_density_is_known(user: User):
    item = item_of(user, package="1000", unit="ml")
    stock.set_stock(item, D(500))

    assert stock.grams_in_stock(item) == D(500)


# ----------------------------------------------------------------------------
# What an amount of the product takes from it
# ----------------------------------------------------------------------------
def test_grams_take_grams(user: User):
    item = item_of(user)
    stock.set_stock(item, D(400))

    assert stock.needed_from_stock(item, D(60), None) == D(60)


def test_grams_take_millilitres_by_the_density(user: User):
    item = item_of(user, package="1000", unit="ml")
    with_density(item, "0.908", "0.912")
    stock.set_stock(item, D(500))

    # 91 g of oil are 100 ml of it.
    assert stock.needed_from_stock(item, D(91), None) == D(100)


def test_servings_take_the_servings_they_need_and_whole_ones(user: User):
    item = pots_of(user)
    stock.set_stock(item, D(4))

    assert stock.needed_from_stock(item, None, D(1)) == D(1)
    assert stock.needed_from_stock(item, None, D(2)) == D(2)
    # A pot opened is a pot gone.
    assert stock.needed_from_stock(item, None, D("0.5")) == D(1)
    assert stock.needed_from_stock(item, None, D("1.2")) == D(2)


def test_a_hair_over_a_whole_serving_is_that_serving(user: User):
    item = pots_of(user)
    stock.set_stock(item, D(4))

    assert stock.needed_from_stock(item, None, D("2.0000001")) == D(2)


def test_nothing_is_taken_of_what_cannot_be_told_in_the_unit(user: User):
    pots = pots_of(user)
    grams = item_of(user, package="500", barcode="7613032637620")
    stock.set_stock(pots, D(4))
    stock.set_stock(grams, D(400))

    assert stock.needed_from_stock(pots, D(100), None) is None
    assert stock.needed_from_stock(grams, None, D(1)) is None


# ----------------------------------------------------------------------------
# Taking from it, and giving back
# ----------------------------------------------------------------------------
def test_what_is_taken_comes_off_the_stock(user: User):
    item = item_of(user)
    stock.set_stock(item, D(375))

    taken = stock.take_from_stock(item, D(60))

    item.refresh_from_db()
    assert taken == D(60)
    assert item.stock_quantity == D(315)


def test_pots_are_taken_whole(user: User):
    item = pots_of(user)
    stock.set_stock(item, D(4))

    stock.take_from_stock(item, D(1))

    item.refresh_from_db()
    assert item.stock_quantity == D(3)


def test_the_stock_stops_at_nothing_and_says_what_it_gave(user: User):
    item = item_of(user)
    stock.set_stock(item, D(50))

    taken = stock.take_from_stock(item, D(80))

    item.refresh_from_db()
    assert taken == D(50)
    assert item.stock_quantity == D(0)


def test_nothing_is_taken_from_a_stock_that_was_not_counted(user: User):
    item = item_of(user)

    assert stock.take_from_stock(item, D(60)) == D(0)

    item.refresh_from_db()
    assert item.stock_quantity is None


def test_what_is_given_back_goes_to_the_stock(user: User):
    item = item_of(user)
    stock.set_stock(item, D(315))

    stock.give_back_to_stock(item, D(60))

    item.refresh_from_db()
    assert item.stock_quantity == D(375)


def test_nothing_is_given_back_to_a_stock_that_was_not_counted(user: User):
    item = item_of(user)

    stock.give_back_to_stock(item, D(60))

    item.refresh_from_db()
    assert item.stock_quantity is None


def test_quantity_of_undoes_grams_of_to_a_hundredth():
    oil = Product(barcode="3270190008262", name="Oil")
    vars(oil)["density"] = (D("0.908"), D("0.915"))

    grams = oil.grams_of(D(250), "ml")

    # The grams are kept to a hundredth, so the millilitres come back to one.
    assert abs(oil.quantity_of(grams, "ml") - D(250)) <= D("0.01")
    assert oil.quantity_of(grams, "g") == grams
