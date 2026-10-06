"""
Turning a reference ingredient into an additive, or into the one it already is.

A reference is created for any name a label lists that nothing has, so an "acide
citrique" ends up one unless the label gave it a class or an E number. Only a person
can say it is an additive, as for a preparation (see preparation_services), but the
table of additives, which the Commission's list fills (see additive_sync), says which
references are known as additives: the one that has the name of an additive.

Converting one that is known merges it into that additive: its ingredients point to
the additive, what the additive lacks is completed from the reference (the foods it
drew on, its notes), and the reference is deleted. One that is not known becomes a
new additive, to review, with its names, status, notes and foods. Either way nothing
is lost, and the parts a label lists for an ingredient stay its children.
"""

from collections.abc import Sequence
from typing import NamedTuple

from django.db import IntegrityError
from django.db import transaction
from django.db.models.functions import Lower
from django.utils.translation import gettext as _

from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.services.reference_services import name_key
from opennutrilab.products.services.reference_services import name_keys


class AdditiveConversionError(Exception):
    """A reference cannot be made an additive, and is left as it is."""


class KnownAdditive(NamedTuple):
    additive: Additive
    # The same name in the same language, and not a plural of it: the plural is
    # what the taxonomy of additives writes ("Lécithines") where a label writes the
    # singular, and is a likely match, not a sure one.
    exact: bool


def additives_known_as(
    references: Sequence[ReferenceIngredient],
) -> dict[int, KnownAdditive]:
    """
    The additive each of these references has the name of, by the id of the
    reference. A name is compared with the additives' in the same language only,
    since a word can be two things in two languages.
    """
    by_name: dict[str, dict[str, Additive]] = {"name_en": {}, "name_fr": {}}
    for additive in Additive.objects.order_by("pk"):
        for field, names in by_name.items():
            if name := getattr(additive, field):
                names.setdefault(name_key(name), additive)

    known: dict[int, KnownAdditive] = {}
    for reference in references:
        for field, names in by_name.items():
            name = getattr(reference, field)
            if not name:
                continue
            if (found := names.get(name_key(name))) is not None:
                known[reference.pk] = KnownAdditive(found, exact=True)
                break
            for variant in (*name_keys(name), name_key(name) + "s"):
                if (found := names.get(variant)) is not None:
                    known.setdefault(reference.pk, KnownAdditive(found, exact=False))
                    break
    return known


def ensure_convertible(
    reference: ReferenceIngredient, known: KnownAdditive | None = None
) -> None:
    """
    Raise AdditiveConversionError if the reference cannot be converted.

    A reference that is a component of a preparation is refused, as it is for a
    preparation: taking it out there would lose what that one is made of. A new
    additive cannot take a name a preparation has. Merged into one that is known,
    two ingredients of a product that would be the same under one parent are
    refused too, since the second would take the first's place.
    """
    makes = list(reference.used_in_preparations.order_by("id"))
    if makes:
        raise AdditiveConversionError(
            _("%(name)s is a component of %(preparations)s: take it out there first.")
            % {
                "name": reference.name,
                "preparations": ", ".join(p.name for p in makes),
            }
        )
    if known is None:
        if _taken_by_a_preparation(reference):
            raise AdditiveConversionError(
                _("A preparation already has the name of %(name)s.")
                % {"name": reference.name}
            )
        return
    for usage in Ingredient.objects.filter(reference=reference).select_related(
        "product"
    ):
        if Ingredient.objects.filter(
            product=usage.product, parent=usage.parent, additive=known.additive
        ).exists():
            raise AdditiveConversionError(
                _(
                    "%(name)s and %(additive)s are both listed under the same "
                    "ingredient of %(product)s: one of them has to go first."
                )
                % {
                    "name": reference.name,
                    "additive": known.additive.name,
                    "product": usage.product.name,
                }
            )


def _taken_by_a_preparation(reference: ReferenceIngredient) -> bool:
    for field in ("name_en", "name_fr"):
        key = name_key(getattr(reference, field))
        if key and Preparation.objects.alias(key=Lower(field)).filter(key=key).exists():
            return True
    return False


def convert_to_additive(reference: ReferenceIngredient) -> tuple[Additive, bool]:
    """
    The additive that takes the place of this reference, which is deleted, and
    whether it is one that was there (merged into) and not a new one.

    All or nothing: a reference that is refused (see ensure_convertible) is
    untouched.
    """
    known = additives_known_as([reference]).get(reference.pk)
    ensure_convertible(reference, known)
    try:
        with transaction.atomic():
            if known is not None:
                additive = _complete(known.additive, reference)
            else:
                additive = Additive.objects.create(
                    name_en=reference.name_en,
                    name_fr=reference.name_fr,
                    description=reference.description,
                    status=reference.status,
                )
            additive.source_foods.add(*reference.source_foods.all())
            # One statement: the check wants exactly one of the three at any time.
            Ingredient.objects.filter(reference=reference).update(
                reference=None, additive=additive
            )
            reference.delete()
    except IntegrityError as e:
        # Another request created an additive with that name since it was checked.
        raise AdditiveConversionError(
            _("An additive already has the name of %(name)s.")
            % {"name": reference.name}
        ) from e
    return additive, known is not None


def _complete(additive: Additive, reference: ReferenceIngredient) -> Additive:
    """What the additive lacks, from the reference: nothing it has is changed."""
    changed: list[str] = []
    for field in ("name_en", "name_fr"):
        theirs = getattr(reference, field)
        if theirs and not getattr(additive, field) and not _name_taken(field, theirs):
            setattr(additive, field, theirs)
            changed.append(field)
    notes = reference.description.strip()
    if notes and notes not in additive.description:
        additive.description = f"{additive.description}\n{notes}".strip()
        changed.append("description")
    if changed:
        additive.save(update_fields=changed)
    return additive


def _name_taken(field: str, name: str) -> bool:
    key = name_key(name)
    return Additive.objects.alias(key=Lower(field)).filter(key=key).exists()
