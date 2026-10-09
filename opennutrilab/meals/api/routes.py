from datetime import date
from typing import Literal
from typing import cast

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from opennutrilab.meals.api.schemas import DayIn
from opennutrilab.meals.api.schemas import DayOut
from opennutrilab.meals.api.schemas import ItemChange
from opennutrilab.meals.api.schemas import ItemIn
from opennutrilab.meals.api.schemas import LimitsIn
from opennutrilab.meals.api.schemas import LimitsOut
from opennutrilab.meals.api.schemas import ProposalOut
from opennutrilab.meals.api.schemas import SuggestionsOut
from opennutrilab.meals.api.schemas import day_out
from opennutrilab.meals.api.schemas import proposal_out
from opennutrilab.meals.api.schemas import suggestions_out
from opennutrilab.meals.models import MealItem
from opennutrilab.meals.services import limits as limits_services
from opennutrilab.meals.services import meal_services
from opennutrilab.meals.services import proposals
from opennutrilab.meals.services import suggestions
from opennutrilab.meals.services.day_report import day_report
from opennutrilab.meals.services.day_report import report_of
from opennutrilab.products.models import Product
from opennutrilab.users.models import User

router = Router(tags=["Meals"])

MealKind = Literal["breakfast", "lunch", "snack", "dinner"]


def _user(request: HttpRequest) -> User:
    """The user asking: every route needs one (see config.api)."""
    return cast("User", request.auth)  # pyright: ignore[reportAttributeAccessIssue]


def _own_item(request: HttpRequest, item_id: int) -> MealItem:
    """An item of one of the user's own meals, and no one else's."""
    return get_object_or_404(
        MealItem.objects.select_related("meal", "product"),
        id=item_id,
        meal__user=_user(request),
    )


@router.get(path="/limits/", response=list[LimitsOut])
def list_limits(request: HttpRequest) -> list[LimitsOut]:
    """What the user allows of the products of their inventory (see limits)."""
    return [
        LimitsOut(
            barcode=barcode,
            meals=list(found.meals),
            max_quantity=found.max_quantity,
            max_unit=found.max_unit,
        )
        for barcode, found in limits_services.limits_of(_user(request)).items()
    ]


@router.put(path="/limits/{barcode}", response=LimitsOut)
def set_limits(request: HttpRequest, barcode: str, data: LimitsIn) -> LimitsOut:
    """
    Set the meals a product of the inventory may be in when a day is proposed, and
    the most of it a day. Allowing every meal with no most clears them.
    """
    product = get_object_or_404(Product, barcode=barcode)
    try:
        found = limits_services.set_limits(
            _user(request), product, list(data.meals), data.max_quantity, data.max_unit
        )
    except meal_services.NotInInventoryError as e:
        raise HttpError(422, "The product is not in your inventory.") from e
    except meal_services.NoServingError as e:
        raise HttpError(422, "The product has no serving: give grams.") from e
    return LimitsOut(
        barcode=barcode,
        meals=list(found.meals),
        max_quantity=found.max_quantity,
        max_unit=found.max_unit,
    )


@router.get(path="/{day}", response=DayOut)
def get_day(request: HttpRequest, day: date) -> DayOut:
    """
    The meals of a day with what they bring, and the day against the user's needs.

    Worked out from the estimates kept for the products (about a second for each one
    that has none yet, once).
    """
    return day_out(day_report(_user(request), day))


@router.post(path="/{day}/propose", response=ProposalOut)
def propose_day(request: HttpRequest, day: date) -> ProposalOut:
    """
    The best day from the user's inventory for the needs of their profile, as a
    proposal: nothing is written, and what is already in the day is not counted.

    It may take some seconds (the solver is given 20 at most), and longer the first
    time for the products whose estimate was never worked out.
    """
    user = _user(request)
    try:
        proposal = proposals.propose_day(user)
    except proposals.NoProfileError as e:
        raise HttpError(422, "Fill in your profile first.") from e
    kept: dict[str, list[MealItem]] = {}
    for item in proposal.items:
        kept.setdefault(item.kind, []).append(
            MealItem(product=item.product, quantity=item.quantity, unit=item.unit)
        )
    return proposal_out(proposal, report_of(user, day, kept))


@router.post(path="/{day}/suggest", response=SuggestionsOut)
def suggest_foods(request: HttpRequest, day: date) -> SuggestionsOut:
    """
    What to get for the inventory to meet the needs: foods of the CIQUAL table, at
    most a few, that close what the best day from the inventory misses, with how much
    of each and where, and the day they make. Nothing is written.

    It takes about ten seconds: the foods are chosen, then the day is worked out.
    """
    try:
        found = suggestions.suggest_foods(_user(request), day)
    except proposals.NoProfileError as e:
        raise HttpError(422, "Fill in your profile first.") from e
    return suggestions_out(found)


@router.put(path="/{day}", response=DayOut)
def replace_day(request: HttpRequest, day: date, data: DayIn) -> DayOut:
    """
    Make the meals of a day what the items say, in place of what they were: to take
    a proposed day. All or nothing.
    """
    user = _user(request)
    found = Product.objects.in_bulk({item.barcode for item in data.items})
    unknown = sorted({item.barcode for item in data.items} - found.keys())
    if unknown:
        raise HttpError(404, f"Unknown products: {', '.join(unknown)}")
    try:
        meal_services.replace_day(
            user,
            day,
            [
                (item.kind, found[item.barcode], item.quantity, item.unit)
                for item in data.items
            ],
        )
    except meal_services.NotInInventoryError as e:
        raise HttpError(422, "A product is not in your inventory.") from e
    except meal_services.NoServingError as e:
        raise HttpError(422, "A product has no serving: give grams.") from e
    except meal_services.AlreadyInMealError as e:
        raise HttpError(409, "A product is twice in the same meal.") from e
    return day_out(day_report(user, day))


@router.post(path="/{day}/{kind}/items", response=DayOut)
def add_item(request: HttpRequest, day: date, kind: MealKind, data: ItemIn) -> DayOut:
    """Put a product of the user's inventory in a meal."""
    user = _user(request)
    product = get_object_or_404(Product, barcode=data.barcode)
    try:
        meal_services.add_item(user, day, kind, product, data.quantity, data.unit)
    except meal_services.NotInInventoryError as e:
        raise HttpError(422, "The product is not in your inventory.") from e
    except meal_services.NoServingError as e:
        raise HttpError(422, "The product has no serving: give grams.") from e
    except meal_services.AlreadyInMealError as e:
        raise HttpError(409, "The product is in this meal: change its quantity.") from e
    return day_out(day_report(user, day))


@router.patch(path="/items/{item_id}", response=DayOut)
def change_item(request: HttpRequest, item_id: int, data: ItemChange) -> DayOut:
    """Change how much of a product is in a meal."""
    item = _own_item(request, item_id)
    try:
        meal_services.change_item(item, data.quantity, data.unit)
    except meal_services.NoServingError as e:
        raise HttpError(422, "The product has no serving: give grams.") from e
    return day_out(day_report(_user(request), item.meal.date))


@router.delete(path="/items/{item_id}", response=DayOut)
def remove_item(request: HttpRequest, item_id: int) -> DayOut:
    """Take a product out of a meal."""
    item = _own_item(request, item_id)
    day = item.meal.date
    meal_services.remove_item(item)
    return day_out(day_report(_user(request), day))
