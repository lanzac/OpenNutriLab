"""
The state a food is in, read from the way CIQUAL names it.

CIQUAL says a food's state after its name, in segments: "Haricot rouge, sec",
"Haricot rouge, appertisé, égoutté", "Red kidney bean, boiled/cooked in water".
The proposals of foods for a reference and the composition of an ingredient that
a preparation lists the parts of both read it from here.
"""

import re
import unicodedata
from collections.abc import Iterable

from django.db.models import TextChoices

from opennutrilab.products.models import SourceFood

# The words CIQUAL gives a food's state in, after its name ("Haricot rouge, sec",
# "Red kidney bean, canned, drained"), folded: no accent, lower case. A word is
# only what a whole word says, so that "cru" is not found in "crustacés".
RAW_WORDS = frozenset(
    [
        "cru",
        "crue",
        "crus",
        "crues",
        "frais",
        "fraiche",
        "fraiches",
        "raw",
        "fresh",
        "surgele",
        "surgelee",
        "surgeles",
        "surgelees",
        "frozen",
    ]
)
BOILED_WORDS = frozenset(
    ["bouilli", "bouillie", "bouillis", "bouillies", "boiled", "steamed", "vapeur"]
)
COOKED_WORDS = BOILED_WORDS | frozenset(
    [
        "cuit",
        "cuite",
        "cuits",
        "cuites",
        "cooked",
        "braise",
        "braisee",
        "poele",
        "poelee",
        "saute",
        "sautee",
        "grille",
        "grillee",
        "roti",
        "rotie",
        "four",
        "frit",
        "frite",
        "braised",
        "grilled",
        "roasted",
        "baked",
        "fried",
        "sauteed",
    ]
)
CANNED_WORDS = frozenset(
    [
        "appertise",
        "appertisee",
        "appertises",
        "appertisees",
        "conserve",
        "canned",
        "egoutte",
        "egouttee",
        "egouttes",
        "egouttees",
        "drained",
    ]
)
DRIED_WORDS = frozenset(
    [
        "sec",
        "secs",
        "seche",
        "seches",
        "sechee",
        "sechees",
        "dried",
        "dry",
        "deshydrate",
        "deshydratee",
        "deshydrates",
        "deshydratees",
        "dehydrated",
    ]
)
FROZEN_WORDS = frozenset(["surgele", "surgelee", "surgeles", "surgelees", "frozen"])
STATE_WORDS = RAW_WORDS | COOKED_WORDS | CANNED_WORDS | DRIED_WORDS

# What a segment says about how a food was made that is no other food: "Orge
# perlée, bouillie/cuite à l'eau, sans sel ajouté" is the boiled barley.
QUALIFIERS = (
    "sans sel ajoute",
    "no added salt",
    "sans matiere grasse",
    "without added fat",
    "aliment moyen",
    "average",
)


class Form(TextChoices):
    """What state a food is in, to the degree that its composition differs."""

    BOILED = "boiled"
    COOKED = "cooked"
    CANNED = "canned"
    RAW = "raw"
    DRIED = "dried"


def fold(text: str) -> str:
    """Lower case, without accents."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


def split_states(folded_name: str) -> tuple[str, set[str]]:
    """
    A food's name without the words of its state, and those words.

    CIQUAL says it after the name, in segments: "haricot rouge, appertise,
    egoutte" is "haricot rouge" and {"appertise", "egoutte"}. What else a segment
    says ("chair et peau", "sans noyau") is another food and stays in the name.
    """
    head, *segments = (segment.strip() for segment in folded_name.split(","))
    kept, states = [head], set[str]()
    for segment in segments:
        words = set(re.findall(r"[a-z]+", segment))
        if words & STATE_WORDS:
            states |= words & STATE_WORDS
        elif not any(qualifier in segment for qualifier in QUALIFIERS):
            kept.append(segment)
    return ", ".join(kept), states


def form_of(states: set[str]) -> Form:
    if states & CANNED_WORDS:
        return Form.CANNED
    if states & BOILED_WORDS:
        return Form.BOILED
    if states & COOKED_WORDS:
        return Form.COOKED
    if states & DRIED_WORDS:
        return Form.DRIED
    # Frozen, fresh, or nothing said: the food as it is.
    return Form.RAW


def form_of_food(food: SourceFood) -> Form:
    """The form a source food is in, from its names in both languages."""
    _base_fr, states_fr = split_states(fold(food.name_fr))
    _base_en, states_en = split_states(fold(food.name_en))
    return form_of(states_fr | states_en)


def has_a_word_of(name: str, words: Iterable[str]) -> bool:
    """Whether any of these words is a whole word of the name, without accents."""
    return bool(set(re.findall(r"[a-z]+", fold(name))) & set(words))
