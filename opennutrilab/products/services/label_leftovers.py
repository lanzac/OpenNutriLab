"""
What the reading of a label leaves in the tables of curated items, and takes back.

Saving a product creates a reference, a preparation or an additive for every name
nothing has (see reference_services), all to review: they are the queue a curator
works through. A label that is read badly, or a text that is wrong, queues names that
are no ingredients ("le personnel manipule les"), and correcting the text, or deleting
the product, would leave them there with nothing using them, among the real ones.

So what a product used is looked at again when its ingredients are replaced and when
it is deleted, and an item goes if it is one that a reading made and nobody has
touched since:

- it says it was made from an ingredient list, and is still to review;
- no ingredient uses it, and no preparation is made of it;
- nothing was added to it by a curator: no source food, no default food, no density
  (an additive: no E number, no nutrient). An English name does not count, one is
  proposed when it is made.

A preparation goes before the references it was made of, which are then used by
nothing: the loop goes on until nothing more goes. What a curator has worked on, or
another product uses, stays.
"""

import logging
from collections.abc import Iterable
from typing import NamedTuple

from django.db import transaction
from django.db.models import ProtectedError
from django.db.models import QuerySet

from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import ReferenceIngredient

logger = logging.getLogger(__name__)

# How every item a reading makes starts its description (see reference_services).
CREATION_NOTE = "Created from an ingredient list"


class Used(NamedTuple):
    """The keys of what the ingredients of a product are."""

    references: frozenset[int] = frozenset()
    preparations: frozenset[int] = frozenset()
    additives: frozenset[int] = frozenset()


def used_by(product: Product) -> Used:
    """What the ingredients of a product are, to look at again once they change."""
    rows = list(
        Ingredient.objects.filter(product=product).values_list(
            "reference_id", "preparation_id", "additive_id"
        )
    )
    return Used(
        frozenset(r for r, _p, _a in rows if r is not None),
        frozenset(p for _r, p, _a in rows if p is not None),
        frozenset(a for _r, _p, a in rows if a is not None),
    )


def discard_leftovers(used: Used) -> int:
    """
    Delete what `used` holds that a reading made and no one has touched since, and
    return how many went. Call it once the ingredients that used them have changed.
    """
    gone = 0
    while removed := sum(_discard(queryset) for queryset in _leftovers(used)):
        gone += removed
    if gone:
        logger.info("%s unused item(s) made from a label were discarded", gone)
    return gone


def _leftovers(
    used: Used,
) -> list[QuerySet[Preparation | ReferenceIngredient | Additive]]:
    """Where to look, the wholes before their parts."""
    made = {"status": "to_review", "description__startswith": CREATION_NOTE}
    return [
        Preparation.objects.filter(pk__in=used.preparations, **made).filter(
            usages=None, used_in_preparations=None, source_foods=None
        ),
        ReferenceIngredient.objects.filter(
            pk__in=used.references, default_food=None, density_low=None, **made
        ).filter(usages=None, used_in_preparations=None, source_foods=None),
        Additive.objects.filter(pk__in=used.additives, code="", **made).filter(
            usages=None, source_foods=None, nutrients=None
        ),
    ]  # pyright: ignore[reportReturnType]


def _discard(items: Iterable[Preparation | ReferenceIngredient | Additive]) -> int:
    gone = 0
    for item in items:
        try:
            with transaction.atomic():
                item.delete()
        except ProtectedError:
            # Something else points to it: it is not unused after all.
            continue
        gone += 1
    return gone
