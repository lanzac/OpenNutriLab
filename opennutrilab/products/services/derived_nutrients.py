"""
Nutrients that are a sum of others, and how to compute them.

A source does not always give a nutrient that can be worked out from others it
does give, and a nutrient the label declares may be one no source gives
directly. Each derivation here is derived = sum of factor x component, stored
as NutrientComponent rows (see ensure_derivations) and applied with
derived_amount.

Every formula was checked against the totals CIQUAL 2025 publishes itself,
and those that did not hold are not here:
- vitamin A is retinol + beta-carotene / 12: 953 of the 960 foods that have all
  three, and a non-zero value, agree to within 5 % (with / 6 only 346 do). That
  is the convention CIQUAL 2025 uses for the amounts it publishes, so the
  derivation matches them. The EU label's retinol equivalent may use another
  (see docs/plans/lot-estimation.md).
- folates in dietary folate equivalents are intrinsic folates + 1.7 x folic
  acid: of the 634 foods that have all three and a non-zero value, 631 agree
  to CIQUAL's own rounding (the other three are an average food and two
  breakfast cereals).
- salt is sodium x 2.5, as labels compute it: of the 2,437 foods that have both
  and a non-zero value, 81 % agree to within 5 % (median gap 0.9 %), but not
  those with very little sodium, where CIQUAL's rounding weighs most.
- vitamin K is K1 + K2. CIQUAL gives no total, and K2 is measured for few
  foods, so the total is mostly incomplete.
- Not here: vitamin D as D2 + D3, which CIQUAL's own total does not follow
  (6 agree of 14 foods with a non-zero value); folates in total, which CIQUAL
  gives for none of the foods that give their parts; niacin equivalents, which
  need tryptophan; energy, which CIQUAL gives.
"""

from collections.abc import Iterable
from collections.abc import Mapping
from decimal import Decimal
from typing import NamedTuple

from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import NutrientComponent


class Term(NamedTuple):
    component: str
    factor: Decimal


class NewNutrient(NamedTuple):
    """A derived nutrient no source gives, so it has to be created."""

    name_en: str
    name_fr: str
    unit: Nutrient.Unit
    group: Nutrient.Group
    # Nutrients that are part of it, and had no parent.
    parts: tuple[str, ...] = ()


# Factors keep six decimals, which is how NutrientComponent stores them: 1/12 is
# 0.083333, off by less than 0.0005 %.
DERIVATIONS: dict[str, tuple[Term, ...]] = {
    "vitamin_a": (
        Term("retinol", Decimal(1)),
        Term("beta_carotene", Decimal("0.083333")),
    ),
    "vitamin_b9_dfe": (
        Term("intrinsic_folates", Decimal(1)),
        Term("folic_acid", Decimal("1.7")),
    ),
    # Sodium in mg, salt in g.
    "salt": (Term("sodium", Decimal("0.0025")),),
    "vitamin_k": (
        Term("vitamin_k1", Decimal(1)),
        Term("vitamin_k2", Decimal(1)),
    ),
}

CREATED: dict[str, NewNutrient] = {
    "vitamin_k": NewNutrient(
        "Vitamin K",
        "Vitamine K",
        Nutrient.Unit.MICROGRAM,
        Nutrient.Group.VITAMIN,
        parts=("vitamin_k1", "vitamin_k2"),
    ),
}


class DerivationError(Exception):
    """A derivation names a nutrient the catalogue does not have."""


def ensure_derivations() -> int:
    """
    Make the catalogue hold DERIVATIONS, and return how many nutrients they derive.

    Creates the derived nutrients no source gives, and sets the terms of each
    derivation to what is here, so the code is the one place they are written
    (a term added by hand is kept; one whose factor was changed is put back).
    The nutrients the terms name must exist: the CIQUAL import creates them.
    """
    for code, terms in DERIVATIONS.items():
        derived = _derived_nutrient(code)
        for term in terms:
            component = Nutrient.objects.filter(code=term.component).first()
            if component is None:
                msg = (
                    f"{code} is derived from {term.component}, which is not a nutrient."
                )
                raise DerivationError(msg)
            NutrientComponent.objects.update_or_create(
                derived=derived,
                component=component,
                defaults={"factor": term.factor},
            )
    return len(DERIVATIONS)


def _derived_nutrient(code: str) -> Nutrient:
    existing = Nutrient.objects.filter(code=code).first()
    if existing is not None:
        return existing
    new = CREATED.get(code)
    if new is None:
        msg = f"{code} is derived, but is not a nutrient and is not created here."
        raise DerivationError(msg)
    parts = list(Nutrient.objects.filter(code__in=new.parts))
    nutrient = Nutrient.objects.create(
        code=code,
        name_en=new.name_en,
        name_fr=new.name_fr,
        unit=new.unit,
        group=new.group,
        # Just before its first part, so they are listed together.
        display_order=min((p.display_order for p in parts), default=100) - 1,
    )
    Nutrient.objects.filter(code__in=new.parts, parent=None).update(parent=nutrient)
    return nutrient


def derived_nutrients() -> list[Nutrient]:
    """The nutrients that have a derivation, with their terms loaded."""
    return list(
        Nutrient.objects.filter(components__isnull=False)
        .distinct()
        .prefetch_related("components")
    )


def derived_amount(
    nutrient: Nutrient, amounts: Mapping[str, Decimal | None]
) -> Decimal | None:
    """
    The nutrient worked out from `amounts`, keyed by nutrient code.

    None when it has no derivation, and when a component has no amount: the
    value is incomplete, and is not computed as if the missing one were zero. A
    component that is 0 is a measurement and counts.

    The factors are positive, so the same call gives a derived range from the
    components' low ends and from their high ends.
    """
    terms = list(nutrient.components.all())
    if not terms:
        return None
    total = Decimal(0)
    for term in terms:
        amount = amounts.get(term.component_id)
        if amount is None:
            return None
        total += term.factor * amount
    return total


def complete_with_derived(
    amounts: Mapping[str, Decimal | None],
    derived: Iterable[Nutrient] | None = None,
) -> dict[str, Decimal | None]:
    """
    `amounts`, with each derived nutrient they lack that they can give.

    An amount that is there is never replaced, and a derived amount is not
    used to derive another: a derivation reads the amounts the source gave.
    `derived` is derived_nutrients() when not given; pass it when completing
    many, to read the catalogue once.
    """
    completed = dict(amounts)
    for nutrient in derived_nutrients() if derived is None else derived:
        if amounts.get(nutrient.code) is None:
            value = derived_amount(nutrient, amounts)
            if value is not None:
                completed[nutrient.code] = value
    return completed
