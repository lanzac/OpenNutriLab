"""
Proposing the CIQUAL foods a reference ingredient draws on, for a human to check.

Linking a reference to its foods is a judgement, and nothing here makes it: a
proposal says which foods are likely and why, and how sure it is, and the
curator accepts or changes it.

Two signals that do not depend on each other are crossed. The name: CIQUAL
names a food by the thing first ("Cassis, cru", "Datte, chair et peau, sans
noyau, sèche"), so a food whose name starts with the reference's name is the
likely one, and a cooked or prepared one is not when the reference is not. And
OpenFoodFacts' taxonomy, which gives a CIQUAL code for many ingredients: it is
not trusted alone (some codes are out of date, and entries that differ share
one), but when it points to the food the name points to, the two agree.
"""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from django.db.models import Q
from django.db.models import TextChoices
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.reference_services import CIQUAL_SOURCE_PREFIX
from opennutrilab.products.services.reference_services import name_key
from opennutrilab.products.services.reference_services import suggest_source_foods

CANDIDATES_SHOWN = 5
# Enough name matches to find the plain food among many.
NAME_MATCHES_READ = 100

# Words that say a food is cooked or prepared. "Sec" and "sèche" are not here: a
# dried food is the one the reference is made of ("Datte, ..., sèche").
PREPARED_WORDS = (
    "cuit",
    "bouilli",
    "frit",
    "roti",
    "grille",
    "appertise",
    "braise",
    "poele",
    "vapeur",
    "confit",
    "sirop",
    "pane",
    "reconstitue",
    "conserve",
    "au four",
    "saute",
    "fume",
)


class Confidence(TextChoices):
    HIGH = "high", _("High")
    MEDIUM = "medium", _("Medium")
    LOW = "low", _("Low")
    NONE = "none", _("None found")


class Reason(TextChoices):
    NAME = "name", _("Its name is the reference's name")
    OFF = "off", _("OpenFoodFacts gives this CIQUAL code")
    PREPARED = "prepared", _("Cooked or prepared, which the reference is not")


class Candidate(NamedTuple):
    food: SourceFood
    reasons: tuple[Reason, ...]


@dataclass
class Proposal:
    reference: ReferenceIngredient
    candidates: list[Candidate]
    confidence: Confidence


def _fold(text: str) -> str:
    """Lower case, without accents."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


def _same_head(name: str, food_name: str) -> bool:
    """Whether a food is named first by `name`: "Cassis, cru" is "cassis"."""
    return bool(name) and food_name.split(",")[0].strip() == name


def _starts(name: str, food_name: str) -> bool:
    return bool(name) and food_name.startswith(name)


def _is_prepared(text: str) -> bool:
    return any(word in _fold(text) for word in PREPARED_WORDS)


class _Scored(NamedTuple):
    food: SourceFood
    exact: bool
    starts: bool
    prepared: bool
    off: bool

    def sort_key(self) -> tuple[bool, bool, bool, bool, int, str]:
        return (
            not self.exact,
            self.prepared,
            not self.off,
            not self.starts,
            len(self.food.name_fr),
            self.food.code,
        )

    def reasons(self) -> tuple[Reason, ...]:
        found = [
            (self.exact, Reason.NAME),
            (self.off, Reason.OFF),
            (self.prepared, Reason.PREPARED),
        ]
        return tuple(reason for present, reason in found if present)


def _hint_codes(references: Sequence[ReferenceIngredient]) -> list[set[str]]:
    """
    The CIQUAL codes OFF's taxonomy gives for each reference, found by name.

    An English name is compared with the English one and a French name with the
    French one: "raisin" is a grape in French and a dried one in English, and
    the code of one is not a hint for the other.
    """
    names = [
        (name_key(reference.name_en), name_key(reference.name_fr))
        for reference in references
    ]
    keys = {key for pair in names for key in pair} - {""}
    if not keys:
        return [set() for _ in references]
    taxa = list(
        IngredientTaxon.objects.alias(key_en=Lower("name_en"), key_fr=Lower("name_fr"))
        .filter(Q(key_en__in=keys) | Q(key_fr__in=keys))
        .exclude(ciqual_food_code="")
    )
    return [
        {
            taxon.ciqual_food_code
            for taxon in taxa
            if (name_en and name_key(taxon.name_en) == name_en)
            or (name_fr and name_key(taxon.name_fr) == name_fr)
        }
        for name_en, name_fr in names
    ]


def propose_foods(
    references: Sequence[ReferenceIngredient],
) -> list[Proposal]:
    """A proposal for each reference, in the same order."""
    hints = _hint_codes(references)
    return [
        _propose(reference, hint_codes)
        for reference, hint_codes in zip(references, hints, strict=True)
    ]


def _propose(reference: ReferenceIngredient, hint_codes: set[str]) -> Proposal:
    name_fr, name_en = _fold(reference.name_fr), _fold(reference.name_en)
    wants_prepared = _is_prepared(f"{reference.name_fr} {reference.name_en}")

    foods = {
        food.pk: food
        for food in suggest_source_foods(reference, limit=NAME_MATCHES_READ)
    }
    off_foods = SourceFood.objects.filter(
        source__code__startswith=CIQUAL_SOURCE_PREFIX, code__in=hint_codes
    ).select_related("source")
    if reference.pk is not None:
        off_foods = off_foods.exclude(reference_ingredients=reference)
    off_ids: set[int] = set()
    for food in off_foods:
        foods.setdefault(food.pk, food)
        off_ids.add(food.pk)

    scored: list[_Scored] = []
    for food in foods.values():
        food_fr, food_en = _fold(food.name_fr), _fold(food.name_en)
        # A name is compared with the same language's: "raisin" is the French
        # for a grape and the English for a dried one.
        scored.append(
            _Scored(
                food=food,
                exact=_same_head(name_fr, food_fr) or _same_head(name_en, food_en),
                starts=_starts(name_fr, food_fr) or _starts(name_en, food_en),
                prepared=not wants_prepared
                and _is_prepared(f"{food.name_fr} {food.name_en}"),
                off=food.pk in off_ids,
            )
        )
    scored.sort(key=_Scored.sort_key)
    return Proposal(
        reference=reference,
        candidates=[Candidate(s.food, s.reasons()) for s in scored[:CANDIDATES_SHOWN]],
        confidence=_confidence(scored, len(hint_codes)),
    )


def _confidence(scored: list[_Scored], hint_count: int) -> Confidence:
    """
    High when the name and OpenFoodFacts point to the same plain food, medium
    when the name does and nothing else contradicts it, low otherwise.
    """
    if not scored:
        return Confidence.NONE
    top = scored[0]
    plain_exact = [s for s in scored if s.exact and not s.prepared]
    if top.exact and not top.prepared and top.off and hint_count == 1:
        return Confidence.HIGH
    if top.exact and not top.prepared and len(plain_exact) == 1:
        return Confidence.MEDIUM
    return Confidence.LOW
