from decimal import Decimal
from http import HTTPStatus

import pytest
from django.test import Client

from opennutrilab.meals.models import Meal
from opennutrilab.meals.models import MealItem
from opennutrilab.meals.services import limits
from opennutrilab.meals.services import proposals
from opennutrilab.meals.services.limits import Limits
from opennutrilab.meals.services.optimiser import KINDS
from opennutrilab.meals.tests.conftest import make_product
from opennutrilab.meals.tests.conftest import make_profile
from opennutrilab.meals.tests.conftest import stock
from opennutrilab.products.models import Product
from opennutrilab.products.services.stored_estimates import Amount
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

D = Decimal
BREAD = "3228857002245"
MUESLI = "3229820794556"
BARS = "5060088700112"
DAY = "2026-10-09"
API = f"/api/v1/meals/{DAY}"


def amount(value: str) -> Amount:
    return Amount(D(value), D(value), D(value), D(100), declared=False)


# ----------------------------------------------------------------------------
# A product as the optimiser counts it
# ----------------------------------------------------------------------------
def test_a_product_with_a_serving_is_counted_in_half_servings(db: None):
    bread = Product(
        barcode=BREAD, name="Bread", serving_quantity=D("35.7"), serving_unit="g"
    )

    found = proposals.candidate_of(
        bread, {"energy": amount("1233"), "fat": amount("8")}
    )

    assert found is not None
    assert found.unit == "serving"
    assert found.step_quantity == 0.5  # noqa: PLR2004
    assert found.step_grams == pytest.approx(17.85)
    # 6 servings is 214 g, less than the 500 g at most.
    assert found.max_grams == pytest.approx(214.2)
    assert found.meals == frozenset(KINDS)
    assert found.per_100g == {"energy": 1233.0, "fat": 8.0}


def test_a_product_with_no_serving_is_counted_in_steps_of_ten_grams(db: None):
    muesli = Product(barcode=MUESLI, name="Muesli")

    found = proposals.candidate_of(muesli, {"energy": amount("1532")})

    assert found is not None
    assert (found.unit, found.step_grams, found.step_quantity) == ("g", 10.0, 10.0)
    assert found.max_grams == proposals.DEFAULT_MAX_GRAMS


def test_a_big_serving_is_not_six_times_what_a_day_may_hold(db: None):
    gnocchi = Product(
        barcode="3270160860333",
        name="Gnocchi",
        serving_quantity=D(300),
        serving_unit="g",
    )

    found = proposals.candidate_of(gnocchi, {"energy": amount("861")})

    assert found is not None
    assert found.max_grams == proposals.DEFAULT_MAX_GRAMS


def test_the_limits_set_the_meals_and_the_most_in_servings_or_grams(db: None):
    bars = Product(barcode=BARS, name="Bars", serving_quantity=D(45), serving_unit="g")
    energy = {"energy": amount("1700")}

    in_servings = proposals.candidate_of(
        bars, energy, Limits(("snack",), D(2), "serving")
    )
    in_grams = proposals.candidate_of(bars, energy, Limits((), D(100), "g"))

    assert in_servings is not None
    assert in_grams is not None
    assert in_servings.meals == frozenset({"snack"})
    assert in_servings.max_grams == 90.0  # noqa: PLR2004
    assert in_grams.meals == frozenset(KINDS)
    assert in_grams.max_grams == 100.0  # noqa: PLR2004


def packaged(grams: str, unit: str = "g", **fields: object) -> Product:
    return Product(
        barcode=BREAD,
        name="Bread",
        serving_quantity=D("35.7"),
        serving_unit="g",
        package_quantity=D(grams),
        package_unit=unit,
        **fields,
    )


def test_the_whole_package_is_counted_in_grams_and_is_required(db: None):
    bread = packaged("500")

    found = proposals.candidate_of(
        bread, {"energy": amount("1233")}, Limits((), None, "", use_all=True)
    )

    assert found is not None
    # In grams though the product has a serving, and not capped by the default most.
    assert found.unit == "g"
    assert found.max_grams == 500.0  # noqa: PLR2004
    assert found.required_grams == 500.0  # noqa: PLR2004
    assert found.step_grams == found.step_quantity == 10.0  # noqa: PLR2004
    assert found.meals == frozenset(KINDS)


@pytest.mark.parametrize(
    ("grams", "step"),
    [
        ("500", 10.0),
        ("900", 10.0),
        ("375", 5.0),
        ("135", 5.0),
        ("1000", 10.0),
        ("12.5", 0.5),
        ("33", 1.0),
        ("33.3", 0.1),
        ("12.34", 0.01),
    ],
)
def test_the_step_of_a_whole_package_is_the_coarsest_that_makes_it_whole(
    db: None, grams: str, step: float
):
    found = proposals.candidate_of(
        packaged(grams),
        {"energy": amount("1233")},
        Limits((), None, "", use_all=True),
    )

    assert found is not None
    assert found.step_grams == step
    assert found.required_grams is not None
    assert found.required_grams / found.step_grams == pytest.approx(
        round(found.required_grams / found.step_grams)
    )


def test_a_package_in_ml_is_counted_in_as_many_grams(db: None):
    milk = packaged("1000", unit="ml")

    found = proposals.candidate_of(
        milk, {"energy": amount("200")}, Limits((), None, "", use_all=True)
    )

    assert found is not None
    assert found.required_grams == 1000.0  # noqa: PLR2004


def test_the_whole_package_is_in_the_meals_the_limits_say(db: None):
    found = proposals.candidate_of(
        packaged("500"),
        {"energy": amount("1233")},
        Limits(("lunch", "dinner"), None, "", use_all=True),
    )

    assert found is not None
    assert found.meals == frozenset({"lunch", "dinner"})


def test_the_whole_package_of_a_product_with_none_is_not_required(db: None):
    bread = Product(
        barcode=BREAD, name="Bread", serving_quantity=D("35.7"), serving_unit="g"
    )

    found = proposals.candidate_of(
        bread, {"energy": amount("1233")}, Limits((), None, "", use_all=True)
    )

    assert found is not None
    assert found.required_grams is None
    assert found.unit == "serving"


def test_a_product_with_no_energy_to_count_is_left_out(db: None):
    water = Product(barcode="1111111111116", name="Water")

    assert proposals.candidate_of(water, {}) is None
    assert proposals.candidate_of(water, {"energy": amount("0")}) is None


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
            fiber="8.7",
        ),
        make_product(
            MUESLI,
            energy="1532",
            proteins="20",
            fat="9",
            carbohydrates="55",
            fiber="10",
        ),
        make_product(
            BARS,
            serving="45",
            energy="1700",
            proteins="15",
            fat="21",
            carbohydrates="30",
        ),
    ]
    stock(user, *products)
    return products


def test_a_day_cannot_be_proposed_without_a_profile(
    user: User, inventory: list[Product]
):
    with pytest.raises(proposals.NoProfileError):
        proposals.propose_day(user)


def test_a_day_is_proposed_from_the_inventory_for_the_needs(
    user: User, inventory: list[Product]
):
    make_profile(user)

    proposal = proposals.propose_day(user)

    assert proposal.status == "optimal"
    assert proposal.items
    assert {item.product.pk for item in proposal.items} <= {p.pk for p in inventory}
    assert {item.kind for item in proposal.items} <= set(KINDS)
    # Nothing is written.
    assert not Meal.objects.exists()
    # The energy of the day is the person's: 2651 kcal, within 5 % either way, or
    # a little more where steps of half a serving do not fall exactly on it.
    kilojoules = sum(
        (
            item.product.declared_nutrients.get(nutrient_id="energy").amount
            * _grams(item)
            / 100
            for item in proposal.items
        ),
        D(0),
    )
    needed = D("2651") * D("4.184")
    assert needed * D("0.9") <= kilojoules <= needed * D("1.1")


def _grams(item: proposals.ProposedItem) -> Decimal:
    if item.unit == "serving":
        assert item.product.serving_quantity is not None
        return item.quantity * item.product.serving_quantity
    return item.quantity


def test_the_limits_of_a_product_are_kept_in_the_proposal(
    user: User, inventory: list[Product]
):
    make_profile(user)
    bars = inventory[2]
    limits.set_limits(user, bars, ["snack"], D(1), "serving")

    proposal = proposals.propose_day(user)

    found = [item for item in proposal.items if item.product == bars]
    assert {item.kind for item in found} <= {"snack"}
    assert sum(item.quantity for item in found) <= 1


def test_a_product_left_out_is_not_in_the_proposed_day(
    user: User, inventory: list[Product]
):
    make_profile(user)
    bars = inventory[2]
    limits.set_limits(user, bars, [], None, None, enabled=False)

    loaded = proposals.load_inventory(user)
    proposal = proposals.propose_day(user)

    assert bars.pk not in {candidate.barcode for candidate in loaded.candidates}
    # It is the user's choice: it is not left aside for what it lacks.
    assert bars.pk not in {skipped.barcode for skipped in loaded.skipped}
    assert proposal.items
    assert bars not in {item.product for item in proposal.items}


def test_a_day_cannot_be_made_of_products_that_are_all_left_out(
    user: User, inventory: list[Product]
):
    make_profile(user)
    limits.set_all_enabled(user, enabled=False)

    proposal = proposals.propose_day(user)

    assert proposal.status == "no_candidates"
    assert proposal.items == []


def test_a_product_asked_for_whole_is_all_in_the_proposed_day(
    user: User, inventory: list[Product]
):
    make_profile(user)
    bars = inventory[2]
    Product.objects.filter(pk=bars.pk).update(package_quantity=D(135), package_unit="g")
    bars.refresh_from_db()
    limits.set_limits(user, bars, ["lunch", "snack"], None, None, use_all=True)

    proposal = proposals.propose_day(user)

    found = [item for item in proposal.items if item.product == bars]
    assert found
    assert {item.kind for item in found} <= {"lunch", "snack"}
    assert {item.unit for item in found} == {"g"}
    assert sum(item.quantity for item in found) == D(135)


def test_the_inventory_of_others_is_not_used(user: User, inventory: list[Product]):
    make_profile(user)
    other = UserFactory()
    stranger = make_product("3017620422003", energy="2500")
    stock(other, stranger)

    proposal = proposals.propose_day(user)

    assert stranger.pk not in {item.product.pk for item in proposal.items}


def test_a_product_with_no_energy_is_said_to_be_left_out(
    user: User, inventory: list[Product]
):
    make_profile(user)
    nothing = make_product("1111111111116")
    stock(user, nothing)

    proposal = proposals.propose_day(user)

    assert [(s.barcode, s.reason) for s in proposal.skipped] == [
        (nothing.pk, proposals.NO_ENERGY)
    ]


def test_an_inventory_with_nothing_to_count_gives_no_day(user: User, catalogue: None):
    make_profile(user)
    stock(user, make_product("1111111111116"))

    proposal = proposals.propose_day(user)

    assert (proposal.status, proposal.items) == ("no_candidates", [])
    assert [s.barcode for s in proposal.skipped] == ["1111111111116"]


# ----------------------------------------------------------------------------
# The API
# ----------------------------------------------------------------------------
@pytest.fixture
def api_client(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def test_a_proposal_comes_with_the_report_of_the_day_it_makes_and_saves_nothing(
    api_client: Client, user: User, inventory: list[Product]
):
    make_profile(user)

    response = api_client.post(f"{API}/propose")

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["status"] == "optimal"
    assert body["items"]
    first = body["items"][0]
    assert set(first) == {"kind", "barcode", "quantity", "unit"}
    # The day as it would be, with no id to its items: it is not saved.
    items = [i for meal in body["day"]["meals"] for i in meal["items"]]
    assert len(items) == len(body["items"])
    assert all(item["id"] is None for item in items)
    assert body["day"]["needs"] is not None
    assert not Meal.objects.exists()


def test_a_product_asked_for_whole_is_all_in_the_proposal_of_the_page(
    api_client: Client, user: User, inventory: list[Product]
):
    make_profile(user)
    bars = inventory[2]
    Product.objects.filter(pk=bars.pk).update(package_quantity=D(135), package_unit="g")
    bars.refresh_from_db()
    limits.set_limits(user, bars, [], None, None, use_all=True)

    response = api_client.post(f"{API}/propose")

    body = response.json()
    assert response.status_code == HTTPStatus.OK
    whole = [item for item in body["items"] if item["barcode"] == bars.pk]
    assert {item["unit"] for item in whole} == {"g"}
    assert sum(D(item["quantity"]) for item in whole) == D(135)
    # And the day it makes is reported with the same quantity.
    reported = [
        item
        for meal in body["day"]["meals"]
        for item in meal["items"]
        if item["barcode"] == bars.pk
    ]
    assert sum(D(item["quantity"]) for item in reported) == D(135)


def test_a_proposal_needs_a_profile(api_client: Client, inventory: list[Product]):
    response = api_client.post(f"{API}/propose")

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "profile" in response.json()["detail"]


def test_a_proposal_needs_a_signed_in_user(client: Client, db: None):
    assert client.post(f"{API}/propose").status_code == HTTPStatus.UNAUTHORIZED


def put(client: Client, items: list[dict[str, object]]):
    return client.put(API, {"items": items}, content_type="application/json")


def test_a_day_is_put_in_place_of_what_it_was(
    api_client: Client, user: User, inventory: list[Product]
):
    other_day = Meal.objects.create(user=user, date="2026-10-08", kind="lunch")
    MealItem.objects.create(
        meal=other_day, product_id=BREAD, quantity=1, unit="serving"
    )
    api_client.post(
        f"{API}/lunch/items",
        {"barcode": MUESLI, "quantity": 50, "unit": "g"},
        content_type="application/json",
    )

    response = put(
        api_client,
        [
            {"kind": "breakfast", "barcode": BREAD, "quantity": "2", "unit": "serving"},
            {"kind": "snack", "barcode": BARS, "quantity": "0.5", "unit": "serving"},
        ],
    )

    assert response.status_code == HTTPStatus.OK
    meals = {m["kind"]: m for m in response.json()["meals"]}
    assert [i["barcode"] for i in meals["breakfast"]["items"]] == [BREAD]
    assert [i["barcode"] for i in meals["snack"]["items"]] == [BARS]
    # What was in the day is gone, and another day is not touched.
    assert meals["lunch"]["items"] == []
    assert MealItem.objects.filter(meal=other_day).count() == 1


def test_a_day_that_cannot_be_put_in_place_is_left_as_it_was(
    api_client: Client, user: User, inventory: list[Product]
):
    stranger = make_product("3017620422003", energy="1")
    api_client.post(
        f"{API}/lunch/items",
        {"barcode": MUESLI, "quantity": 50, "unit": "g"},
        content_type="application/json",
    )

    not_stocked = put(
        api_client,
        [
            {"kind": "breakfast", "barcode": BREAD, "quantity": "1", "unit": "serving"},
            {"kind": "snack", "barcode": stranger.pk, "quantity": "1", "unit": "g"},
        ],
    )
    twice = put(
        api_client,
        [
            {"kind": "snack", "barcode": BARS, "quantity": "1", "unit": "serving"},
            {"kind": "snack", "barcode": BARS, "quantity": "2", "unit": "serving"},
        ],
    )
    no_serving = put(
        api_client,
        [{"kind": "snack", "barcode": MUESLI, "quantity": "1", "unit": "serving"}],
    )
    unknown = put(
        api_client,
        [{"kind": "snack", "barcode": "9999999999999", "quantity": "1", "unit": "g"}],
    )

    assert not_stocked.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert twice.status_code == HTTPStatus.CONFLICT
    assert no_serving.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert unknown.status_code == HTTPStatus.NOT_FOUND
    # Still the muesli at lunch, and nothing else.
    assert [
        (i.product_id, i.meal.kind) for i in MealItem.objects.select_related("meal")
    ] == [(MUESLI, "lunch")]


def test_an_empty_day_empties_the_day(api_client: Client, inventory: list[Product]):
    api_client.post(
        f"{API}/lunch/items",
        {"barcode": MUESLI, "quantity": 50, "unit": "g"},
        content_type="application/json",
    )

    response = put(api_client, [])

    assert response.status_code == HTTPStatus.OK
    assert all(meal["items"] == [] for meal in response.json()["meals"])
    assert not MealItem.objects.exists()
