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

A name that does not say its form ("haricot rouge") is not one food but several:
CIQUAL has it dried, boiled and canned, with figures that differ by a factor of
two or three. The proposal then holds all those forms, with the one it would take
as the default (the raw one, which for a pulse is the dried one), and the
curator decides. It is never a high confidence proposal, since the form is a choice
and not something the name and OpenFoodFacts can agree on.

Only a high confidence proposal can be applied without a curator
(link_confident_foods), when a reference is created.
"""

from collections.abc import Iterable
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import NamedTuple

from django.db.models import Q
from django.db.models import TextChoices
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.food_forms import FROZEN_WORDS
from opennutrilab.products.services.food_forms import Form
from opennutrilab.products.services.food_forms import fold
from opennutrilab.products.services.food_forms import form_of
from opennutrilab.products.services.food_forms import split_states
from opennutrilab.products.services.reference_services import CIQUAL_SOURCE_PREFIX
from opennutrilab.products.services.reference_services import name_key
from opennutrilab.products.services.reference_services import suggest_source_foods

CANDIDATES_SHOWN = 5
# Fewer forms than this are not a choice.
FORMS_FOR_A_CHOICE = 2
# Foods of one name whose energy differs by more than this ratio, or whose water by
# more than this many grams per 100 g, are not the same thing whatever their names
# say ("Coriandre, graine" and "Coriandre, fraiche").
ENERGY_RATIO_FOR_A_CHOICE = Decimal("1.5")
WATER_GAP_FOR_A_CHOICE = Decimal(20)
# The vitamins and minerals that count, with their daily reference value in the
# unit of the catalogue (Regulation (EU) 1169/2011, annex XIII). Selenium and iodine
# are left out: CIQUAL's figures for them swing for no reason a name explains.
REFERENCE_INTAKES = {
    "vitamin_a": Decimal(800),
    "vitamin_d": Decimal(5),
    "vitamin_e": Decimal(12),
    "vitamin_k": Decimal(75),
    "vitamin_c": Decimal(80),
    "vitamin_b1": Decimal("1.1"),
    "vitamin_b2": Decimal("1.4"),
    "vitamin_b3": Decimal(16),
    "vitamin_b5": Decimal(6),
    "vitamin_b6": Decimal("1.4"),
    "vitamin_b9_dfe": Decimal(200),
    "vitamin_b12": Decimal("2.5"),
    "potassium": Decimal(2000),
    "calcium": Decimal(800),
    "phosphorus": Decimal(700),
    "iron": Decimal(14),
    "magnesium": Decimal(375),
    "zinc": Decimal(10),
    "copper": Decimal(1),
    "manganese": Decimal(2),
}
# A vitamin or a mineral differs when the foods are two times apart and by at least
# this share of its daily value per 100 g, which is what lets a label claim "source
# of".
SHARE_OF_INTAKE_THAT_DIFFERS = Decimal("0.15")
RATIO_THAT_DIFFERS = Decimal(2)
# The same for what is weighed: two times apart and by at least this much per 100 g.
GRAMS_THAT_DIFFER = {
    "fiber": Decimal(5),
    "proteins": Decimal(5),
    "fat": Decimal(5),
    "carbohydrates": Decimal(5),
    "sodium": Decimal(100),  # In mg: a quarter of a gram of salt.
}
# Foods that differ on this many of those make a choice, a single one being too often
# one sample's oddity.
NUTRIENTS_THAT_DIFFER_FOR_A_CHOICE = 2
# More foods than this under one name are a family of varieties ("Lait": whole,
# skimmed, UHT, pasteurised...) to choose from, not a few things the name may mean.
MOST_FOODS_THAT_DIFFER = 8
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


# The form taken by default is the food as it comes: what a bare name means. A label
# gives an ingredient's share as its weight when it was used (Regulation (EU)
# 1169/2011, annex VIII), and says "cuit", "appertisé" when it was used cooked or
# canned, so the name alone is the food before any of that. A pulse comes dried.
DRIED_FIRST_SUBGROUPS = frozenset({"légumineuses"})
# The dried form of a food is always among the forms: any food may be dried, and
# leaving it out would hide the choice. It is ticked only where the bare name
# usually means it, as a dried pulse is the pulse, and herbs and spices are sold
# dried. A dried fruit or vegetable ("raisin sec", "tomate séchée") is another
# product that a label names as such, so it is shown and not ticked.
DRIED_IS_USUAL_IN = frozenset({"légumineuses", "herbes", "épices"})


# Forms in the order they are taken by default.
DEFAULT_ORDER = (Form.RAW, Form.DRIED, Form.BOILED, Form.COOKED, Form.CANNED)
DEFAULT_ORDER_PULSES = (Form.DRIED, Form.RAW, Form.BOILED, Form.COOKED, Form.CANNED)


class Confidence(TextChoices):
    HIGH = "high", _("High")
    MEDIUM = "medium", _("Medium")
    LOW = "low", _("Low")
    NONE = "none", _("None found")


class Reason(TextChoices):
    NAME = "name", _("Its name is the reference's name")
    OFF = "off", _("OpenFoodFacts gives this CIQUAL code")
    PREPARED = "prepared", _("Cooked or prepared, which the reference is not")
    FORM = "form", _("A form of the same food as the others")
    DEFAULT = "default", _("Proposed as the default form")
    UNLIKELY = "unlikely", _("A label names it as such, so it is not ticked")
    DIFFERS = "differs", _("Same name, but a very different composition")


class Candidate(NamedTuple):
    food: SourceFood
    reasons: tuple[Reason, ...]

    @property
    def unlikely(self) -> bool:
        """A form the bare name does not usually mean, shown and not ticked."""
        return Reason.UNLIKELY in self.reasons


@dataclass
class Proposal:
    reference: ReferenceIngredient
    candidates: list[Candidate]
    confidence: Confidence
    # Set when the name does not say the form: the candidates are then the forms
    # of one food, and this is the one proposed as the default.
    default: SourceFood | None = None


def _same_head(name: str, food_name: str) -> bool:
    """Whether a food is named first by `name`: "Cassis, cru" is "cassis"."""
    return bool(name) and food_name.split(",")[0].strip() == name


def _starts(name: str, food_name: str) -> bool:
    return bool(name) and food_name.startswith(name)


def _is_prepared(text: str) -> bool:
    return any(word in fold(text) for word in PREPARED_WORDS)


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
    name_fr, name_en = fold(reference.name_fr), fold(reference.name_en)
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
        food_fr, food_en = fold(food.name_fr), fold(food.name_en)
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
    if forms := _forms_of_the_same_food(name_fr, name_en, scored):
        return _proposal_of_forms(reference, forms, Reason.FORM)
    if apart := _foods_that_differ_a_lot(scored):
        return _proposal_of_forms(reference, apart, Reason.DIFFERS)
    return Proposal(
        reference=reference,
        candidates=[Candidate(s.food, s.reasons()) for s in scored[:CANDIDATES_SHOWN]],
        confidence=_confidence(scored, len(hint_codes)),
    )


class _Variant(NamedTuple):
    scored: _Scored
    form: Form
    frozen: bool
    unlikely: bool
    # Its name says its state, as "Coriandre, fraiche" does and "Coriandre, graine"
    # does not: the first is the more certainly the food as it is.
    stated: bool = True
    # What is left of its name in French and in English once the words of state are
    # taken out: the same in all the forms when they are one food.
    bases: tuple[str, str] = ("", "")


def _forms_of_the_same_food(
    name_fr: str, name_en: str, scored: Iterable[_Scored]
) -> list[_Variant]:
    """
    One food for each form the reference's name may mean, if it is more than one:
    ["Haricot rouge, sec", "..., bouilli/cuit à l'eau", "..., appertisé"] for
    "haricot rouge". Empty when the foods are not two forms or more, so that frozen
    and fresh raspberries, which are one form, are not taken for a choice.

    What else a name says besides its state ("doux", "en épis", "verte", "chair et
    peau") does not make another form: "Maïs doux, en épis, cuit" and "Maïs doux,
    appertisé" are two forms of "maïs". Of several foods in one form the plainest is
    kept, the one with the fewest such words, so that "Tomate verte, crue" does not
    stand for "tomate" when "Tomate, crue" is there.
    """
    best: dict[Form, tuple[tuple[bool, bool, int, int, str], _Variant]] = {}
    for s in scored:
        if not s.exact:
            continue
        base_fr, states_fr = split_states(fold(s.food.name_fr))
        base_en, states_en = split_states(fold(s.food.name_en))
        states = states_fr | states_en
        form = form_of(states)
        frozen = bool(states & FROZEN_WORDS)
        variant = _Variant(
            s,
            form,
            frozen,
            unlikely=form is Form.DRIED
            and s.food.food_subgroup not in DRIED_IS_USUAL_IN,
            stated=bool(states),
            bases=(base_fr, base_en),
        )
        # The one fresh and named by its state first, then the plainest, the shortest.
        rank = (
            frozen,
            not states,
            (base_fr or base_en).count(","),
            len(s.food.name_fr),
            s.food.code,
        )
        if form not in best or rank < best[form][0]:
            best[form] = (rank, variant)
    if len(best) < FORMS_FOR_A_CHOICE:
        return []
    return [variant for _rank, variant in best.values()]


def _foods_that_differ_a_lot(scored: Iterable[_Scored]) -> list[_Variant]:
    """
    The foods of the reference's name, when what they are made of differs so much
    that taking one for another would be a mistake, though no word of state says
    it: the leaf and the seed of coriander, ginger fresh and ground, the wheat
    flours from white to wholemeal.

    This only adds to the forms the words find. It cannot remove one: raw and
    cooked beetroot have the same energy and water and a ninth of the folates, so a
    difference this does not see can still matter, and the words see it.
    """
    # One food of each kind, so that a hundred samples of one are not a hundred.
    foods: dict[tuple[str, Form], _Variant] = {}
    for s in (s for s in scored if s.exact):
        base_fr, states_fr = split_states(fold(s.food.name_fr))
        base_en, states_en = split_states(fold(s.food.name_en))
        states = states_fr | states_en
        form = form_of(states)
        foods.setdefault(
            (base_fr or base_en, form),
            _Variant(
                s,
                form,
                bool(states & FROZEN_WORDS),
                unlikely=False,
                stated=bool(states),
                bases=(base_fr, base_en),
            ),
        )
    variants = list(foods.values())
    if not FORMS_FOR_A_CHOICE <= len(variants) <= MOST_FOODS_THAT_DIFFER:
        return []
    watched = {"energy", "water", *REFERENCE_INTAKES, *GRAMS_THAT_DIFFER}
    amounts: dict[str, list[Decimal]] = {}
    for nutrient, amount in SourceFoodNutrient.objects.filter(
        food__in=[v.scored.food for v in variants], nutrient_id__in=watched
    ).values_list("nutrient_id", "amount"):
        if amount is not None:
            amounts.setdefault(nutrient, []).append(amount)
    if _energy_or_water_differs(amounts) or (
        sum(
            _nutrient_differs(code, values)
            for code, values in amounts.items()
            if code in REFERENCE_INTAKES or code in GRAMS_THAT_DIFFER
        )
        >= NUTRIENTS_THAT_DIFFER_FOR_A_CHOICE
    ):
        return variants
    return []


def _energy_or_water_differs(amounts: dict[str, list[Decimal]]) -> bool:
    energies = [e for e in amounts.get("energy", []) if e > 0]
    waters = amounts.get("water", [])
    return (
        len(energies) >= FORMS_FOR_A_CHOICE
        and max(energies) / min(energies) > ENERGY_RATIO_FOR_A_CHOICE
    ) or (
        len(waters) >= FORMS_FOR_A_CHOICE
        and max(waters) - min(waters) > WATER_GAP_FOR_A_CHOICE
    )


def _nutrient_differs(code: str, values: list[Decimal]) -> bool:
    """Whether the foods are two times apart on a nutrient, by enough to matter."""
    if len(values) < FORMS_FOR_A_CHOICE or min(values) <= 0:
        return False
    enough = (
        REFERENCE_INTAKES[code] * SHARE_OF_INTAKE_THAT_DIFFERS
        if code in REFERENCE_INTAKES
        else GRAMS_THAT_DIFFER[code]
    )
    return max(values) / min(values) >= RATIO_THAT_DIFFERS and (
        max(values) - min(values) >= enough
    )


def _default_order(forms: Sequence[_Variant]) -> list[_Variant]:
    """The forms, the one to take by default first."""
    subgroup = forms[0].scored.food.food_subgroup
    order = DEFAULT_ORDER_PULSES if subgroup in DRIED_FIRST_SUBGROUPS else DEFAULT_ORDER
    return sorted(
        forms,
        key=lambda f: (
            f.unlikely,
            order.index(f.form),
            not f.stated,
            f.frozen,
            len(f.scored.food.name_fr),
            f.scored.food.code,
        ),
    )


def _proposal_of_forms(
    reference: ReferenceIngredient, forms: list[_Variant], why: Reason
) -> Proposal:
    ordered = _default_order(forms)
    default = ordered[0].scored.food
    candidates = [
        Candidate(
            f.scored.food,
            (
                *(r for r in f.scored.reasons() if r is not Reason.PREPARED),
                why,
                *((Reason.DEFAULT,) if f.scored.food == default else ()),
                *((Reason.UNLIKELY,) if f.unlikely else ()),
            ),
        )
        for f in ordered
    ]
    # The forms are all the right food: which one is a choice, which a name and
    # OpenFoodFacts cannot settle, so this is never high. It is medium when they are
    # one food in several forms, and low when what they are made of differs too
    # ("Champignon": a cep raw, a shiitake cooked), where the default is a guess.
    one_food = any(
        all(v.bases[i] and v.bases[i] == forms[0].bases[i] for v in forms)
        for i in (0, 1)
    )
    return Proposal(
        reference,
        candidates,
        Confidence.MEDIUM if one_food else Confidence.LOW,
        default=default,
    )


def link_confident_foods(references: Iterable[ReferenceIngredient]) -> list[SourceFood]:
    """
    Link each of these references that has no food to the one food proposed for
    it, when the proposal is high confidence: the name and OpenFoodFacts agree on
    a plain food that is not one of several forms. A note says so in its
    description, and it stays to review.

    Anything less is left to a curator. Returns the foods linked.
    """
    waiting = [r for r in references if not r.source_foods.exists()]
    linked: list[SourceFood] = []
    for proposal in propose_foods(waiting):
        if proposal.confidence is not Confidence.HIGH or proposal.default is not None:
            continue
        reference, food = proposal.reference, proposal.candidates[0].food
        reference.source_foods.add(food)
        reference.description = " ".join(
            filter(
                None,
                (
                    reference.description,
                    f"Linked to {food.source.code} {food.code} when created: "
                    "its name and OpenFoodFacts agree.",
                ),
            )
        )
        reference.save(update_fields=["description"])
        linked.append(food)
    return linked


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
