"""
Finding the reference ingredient an ingredient is, and creating it when none is.

What a client sends for an ingredient is an IngredientInput: a name, a
percentage, and what OpenFoodFacts said about it. The English name is the
reference ingredient's key, but nothing is refused for lacking it: a name is
looked up as it is, in either language, and if no reference has it, through
its English correspondence, as OpenFoodFacts' taxonomy gives it ("flocons
d'avoine" is "oat flakes"). When there is still none, one is created, to
review, so that every ingredient has a reference.

What OpenFoodFacts said (its id, its CIQUAL codes) is used only to find the
correspondence and to create that reference, and only kept as a note in its
description: OFF's data is imperfect and never becomes part of the curated
models.
"""

from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from typing import NamedTuple

from django.db import IntegrityError
from django.db import transaction
from django.db.models import Case
from django.db.models import Q
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Length
from django.db.models.functions import Lower
from django.utils.translation import get_language

from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import SourceFood

# What the Source of a CIQUAL table is named after (ciqual-2025, ...).
CIQUAL_SOURCE_PREFIX = "ciqual"

SUGGESTION_LIMIT = 20
# Shorter words ("de", "la") say nothing about which food is meant.
SUGGESTION_MIN_WORD = 3


class Correspondence(NamedTuple):
    """An ingredient's names in the OpenFoodFacts taxonomy; either may be blank."""

    name_en: str
    name_fr: str


def clean_name(name: str) -> str:
    return " ".join(name.split())


def name_key(name: str) -> str:
    """What names are compared by: their case and spacing do not matter."""
    return clean_name(name).lower()


def name_keys(name: str) -> tuple[str, ...]:
    """
    The keys a name is looked up by: as it is, then with its words in the singular.

    A label says "dattes" and "framboises" where the names are "datte" and
    "framboise". The name as written is tried first, so "cassis" is never read
    as "cassi". Only the name looked up is changed: what is stored is not.
    """
    key = name_key(name)
    singular = " ".join(_singular(word) for word in key.split())
    return (key, singular) if singular != key else (key,)


def _singular(word: str) -> str:
    plural = len(word) > 3 and word.endswith("s") and not word.endswith("ss")  # noqa: PLR2004
    return word[:-1] if plural else word


def walk_ingredients(items: Iterable[IngredientInput]) -> Iterator[IngredientInput]:
    for item in items:
        yield item
        yield from walk_ingredients(item.sub_ingredients)


def find_references(
    names: Iterable[str], *, french_first: bool = False
) -> dict[str, ReferenceIngredient]:
    """
    The references that have these names, by name_key, in one query.

    A name is searched in both languages, English first unless `french_first`:
    each name is unique, but the English name of one reference can be the French
    name of another ("raisin" is a dried grape in English and a grape in French).
    A name written in the plural also finds the singular (see name_keys). A name
    no reference has is absent.
    """
    return _find(dict.fromkeys(names, french_first))


def _find(french_first: Mapping[str, bool]) -> dict[str, ReferenceIngredient]:
    """find_references, with the language to win a tie asked for each name."""
    asked = {name: name_keys(name) for name in french_first if name_key(name)}
    keys = {key for variants in asked.values() for key in variants}
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
    english_wins = by_french | by_english
    french_wins = by_english | by_french
    found: dict[str, ReferenceIngredient] = {}
    for name, variants in asked.items():
        stored = french_wins if french_first[name] else english_wins
        for key in variants:
            if key in stored:
                found[name_key(name)] = stored[key]
                break
    return found


def english_correspondences(
    items: Iterable[IngredientInput],
) -> dict[str, Correspondence]:
    """
    The names OpenFoodFacts' taxonomy gives these ingredients, by name_key.

    An ingredient with an OFF id is identified by it. Any other is looked up by
    its name, in the language it is in if that is known and else in both, and
    only when the taxonomy gives that name a single correspondence: a name
    several entries share is ambiguous and gets none. An ingredient the taxonomy
    does not know is absent.
    """
    flat = list(items)
    ids = {item.off_id for item in flat if item.off_id}
    keys = {key for item in flat for key in name_keys(item.name)} - {""}
    taxa = list(
        IngredientTaxon.objects.alias(
            key_en=Lower("name_en"), key_fr=Lower("name_fr")
        ).filter(Q(off_id__in=ids) | Q(key_en__in=keys) | Q(key_fr__in=keys))
    )
    by_id = {taxon.off_id: taxon for taxon in taxa}
    # By each language's names, and by both: a name in a language is read in that
    # language's names first, since "raisin" is two things in French and English.
    tables: dict[str, defaultdict[str, set[Correspondence]]] = {
        "en": defaultdict(set),
        "fr": defaultdict(set),
        "": defaultdict(set),
    }
    for taxon in taxa:
        correspondence = Correspondence(
            clean_name(taxon.name_en), clean_name(taxon.name_fr)
        )
        for language, name in (("en", taxon.name_en), ("fr", taxon.name_fr)):
            if (key := name_key(name)) in keys:
                tables[""][key].add(correspondence)
                tables[language][key].add(correspondence)

    found: dict[str, Correspondence] = {}
    for item in flat:
        taxon = by_id.get(item.off_id)
        if taxon is not None and (taxon.name_en or taxon.name_fr):
            correspondence = Correspondence(
                clean_name(taxon.name_en), clean_name(taxon.name_fr)
            )
        else:
            correspondence = _read_in_taxonomy(item, tables)
        if correspondence is not None:
            found[name_key(item.name)] = correspondence
    return found


def _read_in_taxonomy(
    item: IngredientInput,
    tables: Mapping[str, Mapping[str, set[Correspondence]]],
) -> Correspondence | None:
    """The one correspondence the taxonomy gives a name, if it gives just one."""
    language = _language_hint(item)[:2]
    for table in (tables.get(language, {}), tables[""]):
        for variant in name_keys(item.name):
            if variant in table:
                known = table[variant]
                return next(iter(known)) if len(known) == 1 else None
    return None


def existing_references(
    items: Iterable[IngredientInput],
) -> dict[str, ReferenceIngredient]:
    """
    The reference of each ingredient of these trees that has one, by name_key.

    Looked up by the name as it is, then through its English correspondence.
    Nothing is created.
    """
    flat = list(walk_ingredients(items))
    found = _find({i.name: _language_hint(i).startswith("fr") for i in flat})
    unmatched = [item for item in flat if name_key(item.name) not in found]
    correspondences = english_correspondences(unmatched) if unmatched else {}
    candidates = find_references(
        name for correspondence in correspondences.values() for name in correspondence
    )
    for item in unmatched:
        key = name_key(item.name)
        for name in correspondences.get(key, ()):
            if name_key(name) in candidates:
                found[key] = candidates[name_key(name)]
                break
    return found


def resolve_references(
    items: Iterable[IngredientInput],
) -> dict[str, ReferenceIngredient]:
    """
    The reference of every ingredient of these trees, by name_key of its name.

    An ingredient no reference has the name of, in either language or through
    its English correspondence, gets one created, so every name is in the
    result.
    """
    flat = list(walk_ingredients(items))
    references = existing_references(flat)
    missing = [item for item in flat if name_key(item.name) not in references]
    correspondences = english_correspondences(missing) if missing else {}
    # What was created here, under every key of its names, for the same name
    # written in the plural, or listed twice, to find it.
    created: dict[str, ReferenceIngredient] = {}
    for item in missing:
        key = name_key(item.name)
        if key in references:
            continue
        reference = next(
            (created[k] for k in name_keys(item.name) if k in created), None
        )
        if reference is None:
            reference = _create_reference(item, correspondences.get(key))
            for name in (reference.name_en, reference.name_fr):
                for variant in name_keys(name) if name else ():
                    created.setdefault(variant, reference)
        references[key] = reference
    return references


def _create_reference(
    item: IngredientInput, correspondence: Correspondence | None
) -> ReferenceIngredient:
    """
    A reference to review for an ingredient no reference has the name of.

    Its names are the taxonomy's correspondence when there is one: the English
    name is the key and the French one is for display. Without one, the name
    typed is all there is, and it goes where its language says (see
    _is_french); a name in any other language lands in `name_en` and is fixed
    when the reference is reviewed.

    OFF's CIQUAL food code, when it is that of a food that was imported, links
    the new reference to it. A proxy code never does: it is an approximation,
    and is only noted in the description.
    """
    if correspondence is not None:
        name_en, name_fr = correspondence
    elif _is_french(item):
        name_en, name_fr = "", clean_name(item.name)
    else:
        name_en, name_fr = clean_name(item.name), ""
    food = _ciqual_food(item.off_ciqual_food_code)
    try:
        with transaction.atomic():
            reference = ReferenceIngredient.objects.create(
                name_en=name_en,
                name_fr=name_fr,
                description=_creation_note(item, food),
                status=ReferenceIngredient.Status.TO_REVIEW,
            )
    except IntegrityError:
        # Another request created it since it was looked up.
        existing = find_references([name_en, name_fr])
        for name in (name_en, name_fr):
            if name and name_key(name) in existing:
                return existing[name_key(name)]
        raise
    if food is not None:
        reference.source_foods.add(food)
    return reference


def _language_hint(item: IngredientInput) -> str:
    """
    The language an ingredient's name is in, if the client said it: "fr", "en"...

    It is the language the client gave. Failing that an OFF id says it: its
    prefix is the language of the label wording the taxonomy had no English name
    for. Otherwise it is not known, and the empty string.
    """
    if item.language:
        return item.language.lower()
    prefix, separator, _rest = item.off_id.partition(":")
    return prefix.lower() if separator else ""


def _is_french(item: IngredientInput) -> bool:
    """Whether a new name goes in `name_fr`: when it is French, as far as known."""
    if hint := _language_hint(item):
        return hint.startswith("fr")
    return (get_language() or "").startswith("fr")


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
    if item.language:
        notes.append(f"Language of the label: {item.language}.")
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


# ----------------------------------------------------------------------------
# Curating
# ----------------------------------------------------------------------------
class ReferenceNameError(Exception):
    """A reference cannot be created with the names the foods give it."""


def suggest_source_foods(
    reference: ReferenceIngredient, limit: int = SUGGESTION_LIMIT
) -> list[SourceFood]:
    """
    The imported foods that may be what a reference is, found by its names.

    A food matches when its name, in either language, has every word of one of
    the reference's names ("carotte râpée" finds "Carotte, râpée, crue"). Those
    whose name starts with the first word of a name come first, then the
    shortest names, which are the plainest foods ("Huile de tournesol" before
    "Sardine à l'huile de tournesol"). The foods the reference already draws on
    are left out. A suggestion is only a place to start: the choice is the
    curator's.
    """
    matches = Q()
    starts = Q()
    for name in (reference.name_en, reference.name_fr):
        words = [w for w in clean_name(name).split() if len(w) >= SUGGESTION_MIN_WORD]
        if not words:
            continue
        every_word = Q()
        for word in words:
            every_word &= Q(name_fr__icontains=word) | Q(name_en__icontains=word)
        matches |= every_word
        starts |= Q(name_fr__istartswith=words[0]) | Q(name_en__istartswith=words[0])
    if not matches:
        return []
    foods = SourceFood.objects.filter(matches)
    if reference.pk is not None:
        foods = foods.exclude(reference_ingredients=reference)
    return list(
        foods.select_related("source")
        .annotate(
            starts_with=Case(When(starts, then=Value(0)), default=Value(1)),
            name_length=Length("name_fr"),
        )
        .order_by("starts_with", "name_length", "name_fr", "code")[:limit]
    )


def create_reference_from_foods(foods: Sequence[SourceFood]) -> ReferenceIngredient:
    """
    A reference to review that draws on these foods, named after the first.

    The names are the food's own ("Carotte, crue"): the curator edits them.
    """
    first = foods[0]
    name_en, name_fr = clean_name(first.name_en), clean_name(first.name_fr)
    if not (name_en or name_fr):
        msg = f"{first} has no name to give a reference."
        raise ReferenceNameError(msg)
    try:
        with transaction.atomic():
            reference = ReferenceIngredient.objects.create(
                name_en=name_en,
                name_fr=name_fr,
                description="Created from: " + "; ".join(str(food) for food in foods),
                status=ReferenceIngredient.Status.TO_REVIEW,
            )
    except IntegrityError as e:
        msg = f"A reference already has the name of {first}."
        raise ReferenceNameError(msg) from e
    reference.source_foods.set(foods)
    return reference
