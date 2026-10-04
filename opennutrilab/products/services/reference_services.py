"""
Finding the reference ingredient an ingredient is, and creating it when none is.

What a client sends for an ingredient is an IngredientInput: a name, a
percentage, and what OpenFoodFacts said about it. Its reference ingredient is
the one that has that name, in either language and whatever the case. When none
has, one is created, to review, so that every ingredient has a reference.

What OpenFoodFacts said (its id, its CIQUAL codes) is used only to create that
reference, and only kept as a note in its description: OFF's data is imperfect
and never becomes part of the curated models.
"""

from collections.abc import Iterable
from collections.abc import Iterator

from django.db import IntegrityError
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower

from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import SourceFood

# What the Source of a CIQUAL table is named after (ciqual-2020, ...).
CIQUAL_SOURCE_PREFIX = "ciqual"


def clean_name(name: str) -> str:
    return " ".join(name.split())


def name_key(name: str) -> str:
    """What names are compared by: their case and spacing do not matter."""
    return clean_name(name).lower()


def find_references(names: Iterable[str]) -> dict[str, ReferenceIngredient]:
    """
    The references that have these names, by name_key, in one query.

    A name is searched in both languages, English first: each name is unique,
    but the English name of one reference can be the French name of another.
    A name no reference has is absent.
    """
    keys = {name_key(name) for name in names} - {""}
    if not keys:
        return {}
    candidates = ReferenceIngredient.objects.alias(
        key_en=Lower("name_en"), key_fr=Lower("name_fr")
    ).filter(Q(key_en__in=keys) | Q(key_fr__in=keys))
    by_french: dict[str, ReferenceIngredient] = {}
    by_english: dict[str, ReferenceIngredient] = {}
    for reference in candidates:
        if (key := name_key(reference.name_fr)) in keys:
            by_french[key] = reference
        if (key := name_key(reference.name_en)) in keys:
            by_english[key] = reference
    return by_french | by_english


def resolve_references(
    items: Iterable[IngredientInput],
) -> dict[str, ReferenceIngredient]:
    """
    The reference of every ingredient of these trees, by name_key of its name.

    A name no reference has creates one, so every name is in the result.
    """
    flat = list(walk_ingredients(items))
    references = find_references(item.name for item in flat)
    for item in flat:
        key = name_key(item.name)
        if key not in references:
            references[key] = _create_reference(item)
    return references


def walk_ingredients(items: Iterable[IngredientInput]) -> Iterator[IngredientInput]:
    for item in items:
        yield item
        yield from walk_ingredients(item.sub_ingredients)


def _create_reference(item: IngredientInput) -> ReferenceIngredient:
    """
    A reference to review for an ingredient no reference has the name of.

    The name is taken as the normalized one, which is English when it comes
    from OpenFoodFacts' taxonomy. A name typed by hand in another language
    lands in `name_en` too and is fixed when the reference is reviewed, since
    names are searched in both. The French name is the taxonomy's for the OFF
    id, when there is one and no other reference has it.

    OFF's CIQUAL food code, when it is that of a food that was imported,
    links the new reference to it. A proxy code never does: it is an
    approximation, and is only noted in the description.
    """
    name = clean_name(item.name)
    name_fr = _taxonomy_french_name(item.off_id)
    if name_fr and find_references([name_fr]):
        name_fr = ""
    food = _ciqual_food(item.off_ciqual_food_code)
    try:
        with transaction.atomic():
            reference = ReferenceIngredient.objects.create(
                name_en=name,
                name_fr=name_fr,
                description=_creation_note(item, food),
                status=ReferenceIngredient.Status.TO_REVIEW,
            )
    except IntegrityError:
        # Another request created it since it was looked up.
        existing = find_references([name]).get(name_key(name))
        if existing is None:
            raise
        return existing
    if food is not None:
        reference.source_foods.add(food)
    return reference


def _taxonomy_french_name(off_id: str) -> str:
    if not off_id:
        return ""
    taxon = IngredientTaxon.objects.filter(off_id=off_id).first()
    return clean_name(taxon.name_fr) if taxon else ""


def _ciqual_food(code: str) -> SourceFood | None:
    if not code:
        return None
    return (
        SourceFood.objects.filter(
            source__code__startswith=CIQUAL_SOURCE_PREFIX, code=code
        )
        .order_by("-source__version")
        .first()
    )


def _creation_note(item: IngredientInput, food: SourceFood | None) -> str:
    notes = ["Created from an ingredient list."]
    if item.off_id:
        notes.append(f"OpenFoodFacts id: {item.off_id}.")
    if item.off_ciqual_food_code:
        state = "linked" if food else "not among the imported foods"
        notes.append(
            f"OpenFoodFacts CIQUAL code: {item.off_ciqual_food_code} ({state})."
        )
    if item.off_ciqual_proxy_food_code:
        notes.append(
            f"OpenFoodFacts proxy CIQUAL code: {item.off_ciqual_proxy_food_code}"
            " (not linked)."
        )
    return " ".join(notes)
