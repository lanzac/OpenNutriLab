"""
A day proposed from the user's inventory.

The candidates are the products of the inventory that have a composition to count:
each is counted in steps of half a serving where it has a serving and of 10 g where
it has not, may be in the meals its limits say (any by default), and in a day up to
the most they say (by default 6 servings, and never more than 500 g). The needs are
those of the user's profile. The day is then the optimiser's (services.optimiser),
and is only proposed: nothing is written until the user takes it (see
meal_services.replace_day).
"""

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
        meals=frozenset(limits.meals or KINDS),
    )


def propose_day(user: User, *, time_limit: float = 20.0) -> Proposal:
    """
    The best day from the user's inventory for the needs of their profile.

    The estimate of each product of the inventory is worked out first where it was
    never (about a second each), which `refresh_estimates` does ahead of time.
    """
    profile = Profile.objects.filter(user=user).first()
    if profile is None:
        raise NoProfileError(user.pk)
    needs = daily_needs(profile)
    products = [
        item.product
        for item in InventoryItem.objects.filter(user=user).select_related("product")
    ]
    composition = compositions(products)
    limits = limits_of(user)

    candidates: list[Candidate] = []
    skipped: list[Skipped] = []
    for product in products:
        found = candidate_of(
            product, composition[product.pk], limits.get(product.pk, NO_LIMITS)
        )
        if found is None:
            skipped.append(Skipped(product.pk, product.name, NO_ENERGY))
        else:
            candidates.append(found)
    if not candidates:
        return Proposal("no_candidates", None, [], skipped)

    plan = optimise(candidates, needs, time_limit=time_limit)
    by_barcode = {product.pk: product for product in products}
    items = [
        ProposedItem(
            kind=pick.kind,
            product=by_barcode[pick.barcode],
            quantity=Decimal(str(round(pick.quantity, 2))),
            unit=pick.unit,
        )
        for pick in plan.picks
    ]
    return Proposal(plan.status, plan.objective, items, skipped)
