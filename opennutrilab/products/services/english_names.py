"""
Proposing the English name of a reference ingredient, a preparation or an additive
that has none.

The English name is the key a reference is found by and a curated one needs it, so
one created from a French label waits for it. A proposal says which name is
likely and where it comes from, and the curator accepts it or edits it. Nothing
here writes a name: `name_en` is what labels are looked up by and what "mark as
curated" accepts, so a guess written there would pass for a checked name.

Where a proposal comes from, from the most to the least reliable:
- OpenFoodFacts' taxonomy, which names the same thing in both languages;
- the English name of the one source food it draws on ("Olive oil,
  extra virgin"): with several foods there is no telling which to take;
- a machine translation of the French name, if a translator is set (translation).
"""

from collections.abc import Mapping
from collections.abc import Sequence
from typing import NamedTuple

from django.db.models import TextChoices
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.models import Additive
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.services.reference_services import Correspondence
from opennutrilab.products.services.reference_services import clean_name
from opennutrilab.products.services.reference_services import english_correspondences
from opennutrilab.products.services.reference_services import name_key
from opennutrilab.products.services.translation import translate
from opennutrilab.products.services.translation import translation_enabled

# Translations asked of the server in one go: each is a request, and the page
# waits for them.
MACHINE_LIMIT = 50


class NameSource(TextChoices):
    TAXONOMY = "taxonomy", _("OpenFoodFacts taxonomy")
    FOOD = "food", _("Its source food")
    MACHINE = "machine", _("Machine translation")


# What has names and waits for its English one.
type Nameable = ReferenceIngredient | Preparation | Additive


class NameProposal(NamedTuple):
    item: Nameable
    # Blank when nothing could be proposed.
    name_en: str
    source: NameSource | None
    # The name of the reference, preparation or additive that already has this
    # English name: it cannot be given twice.
    taken_by: str = ""


class ProposedNames(NamedTuple):
    proposals: list[NameProposal]
    # Whether a translator is set, was asked and did not answer.
    translator_failed: bool


def propose_english_names(items: Sequence[Nameable]) -> ProposedNames:
    """
    A proposal for each item, in the order given. Needs `source_foods` prefetched
    to be quick.
    """
    taxonomy = english_correspondences(
        IngredientInput(name=item.name_fr, language="fr")
        for item in items
        if item.name_fr
    )
    # No translator set is not a translator that fails: it is not asked, and the
    # curator is not told it did not answer.
    machine = translation_enabled()
    asked = 0
    failed = False
    proposals: list[NameProposal] = []
    for item in items:
        name, source = _from_taxonomy(item, taxonomy)
        if not name:
            name, source = _from_food(item)
        if (
            not name
            and machine
            and item.name_fr
            and not failed
            and asked < MACHINE_LIMIT
        ):
            asked += 1
            translated = translate(item.name_fr)
            if translated is None:
                # A server that is down would hold the page for every name.
                failed = True
            elif name_key(translated) != name_key(item.name_fr):
                # A translator returns a word it does not know as it was given.
                name, source = translated, NameSource.MACHINE
        proposals.append(
            NameProposal(
                item,
                name,
                source if name else None,
                taken_by(name, item) if name else "",
            )
        )
    return ProposedNames(proposals, failed)


def _from_taxonomy(
    item: Nameable, taxonomy: Mapping[str, Correspondence]
) -> tuple[str, NameSource | None]:
    found = taxonomy.get(name_key(item.name_fr))
    name = clean_name(found.name_en) if found else ""
    return (name, NameSource.TAXONOMY) if name else ("", None)


def _from_food(item: Nameable) -> tuple[str, NameSource | None]:
    foods = list(item.source_foods.all())
    name = clean_name(foods[0].name_en) if len(foods) == 1 else ""
    return (name, NameSource.FOOD) if name else ("", None)


def taken_by(name: str, item: Nameable) -> str:
    """
    The name of the reference, preparation or additive, other than this one, that
    already has this English name, or "". A name is one thing's only, whatever
    its case.
    """
    key = name_key(name)
    for model in (ReferenceIngredient, Preparation, Additive):
        others = model.objects.alias(key=Lower("name_en")).filter(key=key)
        if type(item) is model:
            others = others.exclude(pk=item.pk)
        if (other := others.first()) is not None:
            return other.name
    return ""
