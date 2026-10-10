"""
A day proposed from the user's inventory.

The candidates are the products of the inventory that have a composition to count:
each is counted in steps of half a serving where it has a serving and of 10 g where
it has not, may be in the meals its limits say (any by default), and in a day up to
the most they say (by default 6 servings, and never more than 500 g), or all of the
package where they ask for it. The needs are those of the user's profile. The day is
then the optimiser's (services.optimiser), and is only proposed: nothing is written
until the user takes it (see meal_services.replace_day).

A day may be partly eaten (Meal.eaten): what its eaten meals brought is counted, so
that what is proposed is what to add to get closer to the needs; nothing is put in
them, and they are kept when the proposal is taken. What a product was eaten of
comes off the most of it that is allowed, and off the package of one that is to be
used whole.
"""

from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from opennutrilab.meals.models import Meal
from opennutrilab.meals.models import MealItem
from opennutrilab.meals.models import Profile
from opennutrilab.meals.services.day_report import GenericItem
from opennutrilab.meals.services.day_report import Portion
from opennutrilab.meals.services.day_report import add_up
from opennutrilab.meals.services.limits import NO_LIMITS
from opennutrilab.meals.services.limits import Limits
from opennutrilab.meals.services.limits import limits_of
from opennutrilab.meals.services.needs import daily_needs
from opennutrilab.meals.services.optimiser import KINDS
from opennutrilab.meals.services.optimiser import Candidate
from opennutrilab.meals.services.optimiser import Eaten
from opennutrilab.meals.services.optimiser import Options
from opennutrilab.meals.services.optimiser import Plan
from opennutrilab.meals.services.optimiser import optimise
from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Product
from opennutrilab.products.services.stored_estimates import Amount
from opennutrilab.products.services.stored_estimates import compositions
from opennutrilab.users.models import User

# The most of a product in a day when its limits say none.
DEFAULT_MAX_SERVINGS = 6.0
DEFAULT_MAX_GRAMS = 500.0
# What a step is: half a serving, or this many grams.
SERVING_STEP = 0.5
GRAM_STEP = 10.0
# What a step of a whole package is, in grams: the coarsest that makes the package a
# whole number of them, so that there are as few as may be to choose between.
PACKAGE_STEPS = (
    Decimal(10),
    Decimal(5),
    Decimal(1),
    Decimal("0.5"),
    Decimal("0.1"),
    Decimal("0.01"),
)


class NoProfileError(Exception):
    """The user has no profile to work the needs out from."""


class ProposedItem(NamedTuple):
    kind: str
    product: Product
    quantity: Decimal
    unit: str


class Skipped(NamedTuple):
    """A product of the inventory the day could not be made of, and why."""

    barcode: str
    name: str
    reason: str


class Proposal(NamedTuple):
    # "optimal", "time_limit" (the best found when the time was up), "failed",
    # "no_candidates" when no product of the inventory had a composition to count, or
    # "nothing_to_fill" when every meal of the day is eaten.
    status: str
    objective: float | None
    items: list[ProposedItem]
    skipped: list[Skipped]
    # The meals of the day that are eaten, with their items (none for a meal eaten and
    # empty), which the proposal is added to and leaves as they are.
    eaten: Mapping[str, Sequence[MealItem]] = {}


class EatenMeals(NamedTuple):
    """The meals of a day that are eaten, as a day proposed takes them."""

    # Their items, by kind of meal.
    items: dict[str, list[MealItem]]
    # What they brought, for the optimiser.
    eaten: Eaten
    # The grams of each product in them, by barcode.
    grams: dict[str, Decimal]

    @property
    def all_eaten(self) -> bool:
        """Whether every meal of the day is eaten: nothing is left to fill."""
        return len(self.items) >= len(KINDS)


# Why a product was left out.
NO_ENERGY = "no_energy"


def eaten_meals(user: User, day: date) -> EatenMeals:
    """The meals of a user's day that are eaten, with what they brought."""
    meals = Meal.objects.filter(user=user, date=day, eaten=True).prefetch_related(
        "items__product"
    )
    items = {meal.kind: list(meal.items.all()) for meal in meals}
    every = [item for found in items.values() for item in found]
    composition = compositions(
        {item.product_id: item.product for item in every}.values()
    )
    portions = [
        Portion(item.grams, composition[item.product_id])
        for item in every
        if item.grams is not None
    ]
    grams: defaultdict[str, Decimal] = defaultdict(Decimal)
    for item in every:
        if item.grams is not None:
            grams[item.product_id] += item.grams
    amounts = {code: float(total.amount) for code, total in add_up(portions).items()}
    return EatenMeals(items, Eaten(frozenset(items), amounts), dict(grams))


def kept_items(
    proposed: Iterable[ProposedItem], eaten: Mapping[str, Sequence[MealItem]]
) -> dict[str, list[MealItem | GenericItem]]:
    """
    A day as it would be, to be reported, by meal: the meals eaten as they are, and
    the proposed items, which are not saved, in the others.
    """
    kept: dict[str, list[MealItem | GenericItem]] = {
        kind: list(found) for kind, found in eaten.items()
    }
    for item in proposed:
        kept.setdefault(item.kind, []).append(
            MealItem(product=item.product, quantity=item.quantity, unit=item.unit)
        )
    return kept


def candidate_of(
    product: Product,
    composition: dict[str, Amount],
    limits: Limits = NO_LIMITS,
    eaten_grams: Decimal = Decimal(0),
) -> Candidate | None:
    """
    The product as the optimiser counts it, or None when it has no energy to count
    (a day with no energy for a product cannot be told from one without it).

    `eaten_grams` of it are eaten already, which come off the most of it a day, and off
    the package where it is to be used whole.
    """
    energy = composition.get("energy")
    if energy is None or energy.amount <= 0:
        return None
    # In grams: a quantity in ml weighs what the product's density says when it is
    # known (Product.grams_of), which the compositions set when they are read.
    serving = (
        float(product.grams_of(product.serving_quantity, product.serving_unit))
        if product.serving_quantity is not None
        else None
    )
    meals = frozenset(limits.meals or KINDS)
    # All of the package, in grams whatever the product's serving, for it to add up.
    if limits.use_all and product.package_quantity is not None:
        package = product.grams_of(product.package_quantity, product.package_unit)
        whole = (package - eaten_grams).quantize(Decimal("0.01"))
        if whole <= 0:
            # Used up: none is left to put in the day, so it is not a candidate.
            return Candidate(
                barcode=product.pk,
                name=product.name,
                per_100g={},
                step_grams=1.0,
                step_quantity=1.0,
                unit=str(MealItem.Unit.GRAM),
                max_grams=0.0,
                meals=meals,
            )
        step = next(found for found in PACKAGE_STEPS if whole % found == 0)
        return Candidate(
            barcode=product.pk,
            name=product.name,
            per_100g={code: float(found.amount) for code, found in composition.items()},
            step_grams=float(step),
            step_quantity=float(step),
            unit=str(MealItem.Unit.GRAM),
            max_grams=float(whole),
            meals=meals,
            required_grams=float(whole),
        )
    if serving is None:
        step_grams, step_quantity, unit = GRAM_STEP, GRAM_STEP, MealItem.Unit.GRAM
        most = DEFAULT_MAX_GRAMS
    else:
        step_grams = SERVING_STEP * serving
        step_quantity, unit = SERVING_STEP, MealItem.Unit.SERVING
        most = min(DEFAULT_MAX_SERVINGS * serving, DEFAULT_MAX_GRAMS)
    if limits.max_quantity is not None:
        by_unit = serving if limits.max_unit == MealItem.Unit.SERVING else 1.0
        most = float(limits.max_quantity) * (by_unit or 1.0)
    most = max(most - float(eaten_grams), 0.0)
    return Candidate(
        barcode=product.pk,
        name=product.name,
        per_100g={code: float(found.amount) for code, found in composition.items()},
        step_grams=step_grams,
        step_quantity=step_quantity,
        unit=str(unit),
        max_grams=most,
        meals=meals,
    )


class Inventory(NamedTuple):
    """The products of a user's inventory, as the optimiser counts them."""

    products: dict[str, Product]
    candidates: list[Candidate]
    skipped: list[Skipped]


def load_inventory(
    user: User, eaten_grams: Mapping[str, Decimal] | None = None
) -> Inventory:
    """
    The products of the user's inventory, and those of them a day can be made of
    (not those they leave out). `eaten_grams` is what is eaten of each, by barcode.

    The estimate of each is worked out first where it never was (about a second
    each), which `refresh_estimates` does ahead of time.
    """
    products = [
        item.product
        for item in InventoryItem.objects.filter(user=user).select_related("product")
    ]
    composition = compositions(products)
    limits = limits_of(user)
    candidates: list[Candidate] = []
    skipped: list[Skipped] = []
    for product in products:
        wanted = limits.get(product.pk, NO_LIMITS)
        # Left out by the user: not a candidate, and not left aside for lack of energy.
        if not wanted.enabled:
            continue
        found = candidate_of(
            product,
            composition[product.pk],
            wanted,
            (eaten_grams or {}).get(product.pk, Decimal(0)),
        )
        if found is None:
            skipped.append(Skipped(product.pk, product.name, NO_ENERGY))
        else:
            candidates.append(found)
    return Inventory({p.pk: p for p in products}, candidates, skipped)


def items_of(plan: Plan, products: Mapping[str, Product]) -> list[ProposedItem]:
    """The picks of a plan as items of meals, in the quantity they are counted in."""
    return [
        ProposedItem(
            kind=pick.kind,
            product=products[pick.barcode],
            quantity=Decimal(str(round(pick.quantity, 2))),
            unit=pick.unit,
        )
        for pick in plan.picks
        if pick.barcode in products
    ]


def propose_day(user: User, day: date, *, time_limit: float = 20.0) -> Proposal:
    """
    What to add to a day, from the user's inventory, for the needs of their profile:
    the best day, with the meals that are eaten as they are.
    """
    profile = Profile.objects.filter(user=user).first()
    if profile is None:
        raise NoProfileError(user.pk)
    needs = daily_needs(profile)
    eaten = eaten_meals(user, day)
    if eaten.all_eaten:
        return Proposal("nothing_to_fill", None, [], [], eaten.items)
    inventory = load_inventory(user, eaten.grams)
    if not inventory.candidates:
        return Proposal("no_candidates", None, [], inventory.skipped, eaten.items)

    plan = optimise(
        inventory.candidates,
        needs,
        options=Options(time_limit=time_limit),
        eaten=eaten.eaten,
    )
    return Proposal(
        plan.status,
        plan.objective,
        items_of(plan, inventory.products),
        inventory.skipped,
        eaten.items,
    )
