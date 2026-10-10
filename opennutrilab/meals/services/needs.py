"""
A person's needs for a day, from the ANSES references.

The references are kept in data/anses_references.json, each with the opinion and
the page it comes from. They are published figures, which change only with a new
opinion, so they are read from that file and kept nowhere else. A need has a
lower end (a population reference intake, an adequate intake, a bound of ANSES'
own diet optimisation) and an upper one (a tolerable upper intake level, a
bound), either of which may be missing. Some are given per MJ of energy (vitamins
B1 and B3) or as a share of it (fat, carbohydrates, proteins, fatty acids), and
are worked out here for the person's energy need (services.energy). Some are on a
sum of nutrients (lauric + myristic + palmitic acids, EPA + DHA).

Ratios are needs of their own: ANSES' linoleic over alpha-linolenic acid below 5
and sodium over potassium, in moles, at most 1, and the user's own targets for
DHA over EPA and omega-3 over omega-6, each within their tolerance.

Only adults are covered, neither pregnant nor breastfeeding, as the profile is.
"""

import json
from collections.abc import Iterable
from collections.abc import Mapping
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any
from typing import NamedTuple

from django.db.models import TextChoices
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from opennutrilab.meals.models import Profile
from opennutrilab.meals.services.energy import ENERGY_MARGIN
from opennutrilab.meals.services.energy import KCAL_PER_MJ
from opennutrilab.meals.services.energy import KJ_PER_KCAL
from opennutrilab.meals.services.energy import Person
from opennutrilab.meals.services.energy import basal_metabolisms
from opennutrilab.meals.services.energy import energy_need
from opennutrilab.products.models import Nutrient

REFERENCES_FILE = Path(__file__).parents[1] / "data" / "anses_references.json"
ADULT_AGE = 18


class Kind(TextChoices):
    """What the end of a need is."""

    RNP = "rnp", _("Population reference intake")
    AS = "as", _("Adequate intake")
    LSS = "lss", _("Tolerable upper intake level")
    ANC = "anc", _("Recommended intake (2011)")
    CONSTRAINT = "constraint", _("Bound of ANSES' diet optimisation")
    ENERGY = "energy", _("Energy need")
    TARGET = "target", _("Your target")


class EnergyShare(NamedTuple):
    """A need given as a share of the energy, in percent."""

    low: Decimal | None
    high: Decimal | None
    kcal_per_g: Decimal


class Need(NamedTuple):
    """
    What a day should bring of a nutrient, or of the sum of several, in the
    nutrient's unit (the catalogue's: energy in kJ, EPA and DHA in g).
    """

    nutrients: tuple[str, ...]
    low: Decimal | None
    high: Decimal | None
    # What each end is (a Kind), and the source it comes from: the two ends of
    # one need can come from two opinions.
    low_kind: str
    high_kind: str
    low_source: str
    high_source: str
    energy_share: EnergyShare | None = None
    # What a sum is called, when its nutrients' names joined would be too long.
    name_en: str = ""
    name_fr: str = ""
    # How much a miss of this need counts, against the others', in the day the
    # optimiser proposes: 1, or what the reference says. A choice of the planner, not
    # a fact of nutrition (see optimiser.Weights).
    priority: Decimal = Decimal(1)


class Ratio(NamedTuple):
    """Weighted sum of the numerator's nutrients over the denominator's."""

    numerator: dict[str, Decimal]
    denominator: dict[str, Decimal]
    low: Decimal | None
    high: Decimal | None
    kind: str
    source: str


class Needs(NamedTuple):
    # In kcal: the need, and the range a day may be in.
    energy: Decimal
    energy_low: Decimal
    energy_high: Decimal
    # By equation, in kcal (see services.energy).
    basal_metabolisms: dict[str, Decimal]
    # The energy first, in kJ, then in the order of the references, one for each
    # nutrient or sum of nutrients.
    nutrients: list[Need]
    ratios: list[Ratio]


class NoReferenceError(ValueError):
    """The references cover no one of this age."""


def daily_needs(profile: Profile) -> Needs:
    """The needs of a profile's person for a day."""
    return needs_for(
        Person(profile.sex, profile.age, profile.weight, profile.height),
        profile.activity_level,
        high_iron_losses=profile.high_iron_losses,
        targets=(
            (
                {"dha": Decimal(1)},
                {"epa": Decimal(1)},
                profile.dha_epa_ratio,
            ),
            (
                {"omega_3": Decimal(1)},
                {"omega_6": Decimal(1)},
                profile.omega3_omega6_ratio,
            ),
        ),
        tolerance=profile.ratio_tolerance,
    )


def needs_for(
    person: Person,
    activity_level: Decimal,
    *,
    high_iron_losses: bool = False,
    targets: tuple[tuple[dict[str, Decimal], dict[str, Decimal], Decimal], ...] = (),
    tolerance: Decimal = Decimal("0.10"),
) -> Needs:
    """
    The needs of a person for a day. `targets` are the user's own ratios, as
    (numerator, denominator, ratio), each kept within `tolerance` of the ratio.
    """
    if person.age < ADULT_AGE:
        msg = f"The references kept are for adults; {person.age} is too young."
        raise NoReferenceError(msg)
    kcal = energy_need(person, activity_level)
    data = references()
    nutrients = [
        Need(
            ("energy",),
            kcal * (1 - ENERGY_MARGIN) * KJ_PER_KCAL,
            kcal * (1 + ENERGY_MARGIN) * KJ_PER_KCAL,
            Kind.ENERGY,
            Kind.ENERGY,
            "anses-2016",
            "anses-2016",
        ),
        *_merged(
            _need(entry, kcal)
            for entry in data["references"]
            if _applies(entry, person, high_iron_losses=high_iron_losses)
        ),
    ]
    ratios = [
        Ratio(
            {code: Decimal(f) for code, f in entry["numerator"].items()},
            {code: Decimal(f) for code, f in entry["denominator"].items()},
            _decimal(entry.get("low")),
            _decimal(entry.get("high")),
            Kind.CONSTRAINT,
            entry["source"],
        )
        for entry in data["ratios"]
    ]
    ratios += [
        Ratio(
            numerator,
            denominator,
            ratio * (1 - tolerance),
            ratio * (1 + tolerance),
            Kind.TARGET,
            "user",
        )
        for numerator, denominator, ratio in targets
    ]
    return Needs(
        energy=kcal,
        energy_low=kcal * (1 - ENERGY_MARGIN),
        energy_high=kcal * (1 + ENERGY_MARGIN),
        basal_metabolisms=basal_metabolisms(person),
        nutrients=nutrients,
        ratios=ratios,
    )


@cache
def references() -> dict[str, Any]:
    """The references as the file holds them."""
    with REFERENCES_FILE.open(encoding="utf-8") as file:
        return json.load(file)


def _applies(entry: dict[str, Any], person: Person, *, high_iron_losses: bool) -> bool:
    if entry.get("sex") not in (None, person.sex):
        return False
    if person.age < entry.get("min_age", ADULT_AGE):
        return False
    if "max_age" in entry and person.age > entry["max_age"]:
        return False
    return entry.get("high_iron_losses", high_iron_losses) == high_iron_losses


def _need(entry: dict[str, Any], kcal: Decimal) -> Need:
    low, high = _decimal(entry.get("low")), _decimal(entry.get("high"))
    share = None
    match entry["basis"]:
        case "day":
            factor = Decimal(1)
        case "per_mj":
            factor = kcal / KCAL_PER_MJ
        case "energy_percent":
            per_g = Decimal(entry["kcal_per_g"])
            share = EnergyShare(low, high, per_g)
            factor = kcal / 100 / per_g
        case basis:
            msg = f"Unknown basis {basis!r} in {REFERENCES_FILE.name}."
            raise ValueError(msg)
    return Need(
        nutrients=tuple(entry["nutrients"]),
        low=None if low is None else low * factor,
        high=None if high is None else high * factor,
        low_kind=entry.get("low_kind", "") if low is not None else "",
        high_kind=entry.get("high_kind", "") if high is not None else "",
        low_source=entry["source"] if low is not None else "",
        high_source=entry["source"] if high is not None else "",
        energy_share=share,
        name_en=entry.get("name_en", ""),
        name_fr=entry.get("name_fr", ""),
        priority=Decimal(entry.get("priority", "1")),
    )


def need_name(need: Need, catalogue: Mapping[str, Nutrient]) -> str:
    """What a need is called: its own name if it has one, else its nutrients' joined."""
    given = need.name_fr if (get_language() or "").startswith("fr") else need.name_en
    return given or " + ".join(catalogue[code].name for code in need.nutrients)


def _merged(needs: Iterable[Need]) -> list[Need]:
    """
    One need for each nutrient or sum, from the references that give its lower
    end and its upper end (vitamin E's are in two opinions).
    """
    merged: dict[tuple[str, ...], Need] = {}
    for need in needs:
        kept = merged.get(need.nutrients)
        if kept is None:
            merged[need.nutrients] = need
            continue
        if (need.low is not None and kept.low is not None) or (
            need.high is not None and kept.high is not None
        ):
            msg = f"Two references give the same end for {need.nutrients}."
            raise ValueError(msg)
        merged[need.nutrients] = kept._replace(
            **(
                {
                    "low": need.low,
                    "low_kind": need.low_kind,
                    "low_source": need.low_source,
                }
                if need.low is not None
                else {
                    "high": need.high,
                    "high_kind": need.high_kind,
                    "high_source": need.high_source,
                }
            ),
            energy_share=kept.energy_share or need.energy_share,
            priority=max(kept.priority, need.priority),
        )
    return list(merged.values())


def _decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)
