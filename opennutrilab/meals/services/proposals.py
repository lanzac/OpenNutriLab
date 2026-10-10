"""
A day proposed from the user's inventory.

The candidates are the products of the inventory that have a composition to count:
each is counted in steps of half a serving where it has a serving and of 10 g where
it has not, may be in the meals its limits say (any by default), and in a day up to
the most they say (by default 6 servings, and never more than 500 g), or all of the
package where they ask for it. The needs are those of the user's profile. The day is
then the optimiser's (services.optimiser), and is only proposed: nothing is written
until the user takes it (see meal_services.replace_day).
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import NamedTuple

from opennutrilab.meals.models import MealItem
from opennutrilab.meals.models import Profile
from opennutrilab.meals.services.limits import NO_LIMITS
from opennutrilab.meals.services.limits import Limits
from opennutrilab.meals.services.limits import limits_of
from opennutrilab.meals.services.needs import daily_needs
from opennutrilab.meals.services.optimiser import KINDS
from opennutrilab.meals.services.optimiser import Candidate
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
    # "optimal", "time_limit" (the best found when the time was up), "failed", or
    # "no_candidates" when no product of the inventory had a composition to count.
    status: str
    objective: float | None
    items: list[ProposedItem]
    skipped: list[Skipped]


# Why a product was left out.
NO_ENERGY = "no_energy"


def candidate_of(
    product: Product, composition: dict[str, Amount], limits: Limits = NO_LIMITS
) -> Candidate | None:
    """
    The product as the optimiser counts it, or None when it has no energy to count
    (a day with no energy for a product cannot be told from one without it).
    """
    energy = composition.get("energy")
    if energy is None or energy.amount <= 0:
        return None
    serving = (
        float(product.serving_quantity)
        if product.serving_quantity is not None
        else None
    )
    meals = frozenset(limits.meals or KINDS)
    # All of the package, in grams whatever the product's serving, for it to add up.
    # A package in ml counts as the same grams, as a serving in ml does.
    if limits.use_all and product.package_quantity is not None:
        whole = product.package_quantity
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


def load_inventory(user: User) -> Inventory:
    """
    The products of the user's inventory, and those of them a day can be made of
    (not those they leave out).

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
        found = candidate_of(product, composition[product.pk], wanted)
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


def propose_day(user: User, *, time_limit: float = 20.0) -> Proposal:
    """The best day from the user's inventory for the needs of their profile."""
    profile = Profile.objects.filter(user=user).first()
    if profile is None:
        raise NoProfileError(user.pk)
    needs = daily_needs(profile)
    inventory = load_inventory(user)
    if not inventory.candidates:
        return Proposal("no_candidates", None, [], inventory.skipped)

    plan = optimise(inventory.candidates, needs, options=Options(time_limit=time_limit))
    return Proposal(
        plan.status,
        plan.objective,
        items_of(plan, inventory.products),
        inventory.skipped,
    )
