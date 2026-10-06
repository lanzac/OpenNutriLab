"""
Turning a reference ingredient into a preparation.

A reference is created for any name a label lists that nothing has (see
reference_services), so a mozzarella or a gnocchi ends up one. Only a person can
say it is made of several ingredients: the text does not (raisins secs and dattes
list parts too, and stay ingredients). So nothing here decides: the curator
picks the references, and this moves what they are to a preparation.

Nothing is lost. The names, the status and the notes move, the source foods it
drew on become the preparation's, every ingredient that used it points to the
preparation (with its percentage and the parts the label listed for it, which
stay its children), and the references it was seen made of on labels become the
preparation's components, for the curator to review.
"""

from django.db import IntegrityError
from django.db import transaction
from django.db.models.functions import Lower
from django.utils.translation import gettext as _

from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.services.reference_services import name_key


class PreparationConversionError(Exception):
    """A reference cannot be made a preparation, and is left as it is."""


def parts_seen(reference: ReferenceIngredient) -> list[ReferenceIngredient]:
    """
    The references this one was seen made of on labels, each once.

    They are the true ingredients the label listed under it, in the order they
    were first seen. A part that is a preparation is not one: a preparation is
    made of references only, and its own parts are its own.
    """
    seen = (
        Ingredient.objects.filter(parent__reference=reference, reference__isnull=False)
        .exclude(reference=reference)
        .order_by("id")
        .values_list("reference_id", flat=True)
    )
    ids = list(dict.fromkeys(seen))
    found = ReferenceIngredient.objects.in_bulk(ids)
    return [found[pk] for pk in ids]


def ensure_convertible(reference: ReferenceIngredient) -> None:
    """
    Raise PreparationConversionError if the reference cannot become a preparation.

    A name a preparation already has is refused, since a name leads to one
    thing. So is a reference that is a component of a preparation: a
    preparation is made of true ingredients, and taking it out there would lose
    what that preparation is made of.
    """
    if _taken_by_a_preparation(reference):
        raise PreparationConversionError(
            _("A preparation already has the name of %(name)s.")
            % {"name": reference.name}
        )
    makes = list(reference.used_in_preparations.order_by("id"))
    if makes:
        raise PreparationConversionError(
            _("%(name)s is a component of %(preparations)s: take it out there first.")
            % {
                "name": reference.name,
                "preparations": ", ".join(p.name for p in makes),
            }
        )


def _taken_by_a_preparation(reference: ReferenceIngredient) -> bool:
    for field in ("name_en", "name_fr"):
        key = name_key(getattr(reference, field))
        if key and Preparation.objects.alias(key=Lower(field)).filter(key=key).exists():
            return True
    return False


def convert_to_preparation(reference: ReferenceIngredient) -> Preparation:
    """
    The preparation that takes the place of this reference, which is deleted.

    All or nothing: a reference that is refused (see ensure_convertible) is
    untouched.
    """
    ensure_convertible(reference)
    components = parts_seen(reference)
    description = reference.description
    if components:
        note = (
            "Made from a reference ingredient. Its components are the parts "
            "seen on labels: to check."
        )
        description = f"{description}\n{note}" if description else note
    try:
        with transaction.atomic():
            preparation = Preparation.objects.create(
                name_en=reference.name_en,
                name_fr=reference.name_fr,
                description=description,
                status=reference.status,
            )
            preparation.source_foods.set(reference.source_foods.all())
            preparation.components.set(components)
            # One statement: the check wants exactly one of the two at any time.
            Ingredient.objects.filter(reference=reference).update(
                reference=None, preparation=preparation
            )
            reference.delete()
    except IntegrityError as e:
        # Another request created a preparation with that name since it was checked.
        raise PreparationConversionError(
            _("A preparation already has the name of %(name)s.")
            % {"name": reference.name}
        ) from e
    return preparation
