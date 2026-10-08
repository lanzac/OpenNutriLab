"""
What is a preparation: an ingredient whose label lists its parts.

The rule is that one: "boulette au haricot rouge (haricot rouge cuit, protéine de
blé, ...)" is a preparation, and so is each of its parts that lists parts in turn
("haricot rouge cuit (eau, haricot rouge)"), a preparation being made of
references and of other preparations. Nothing else makes one: a name no label
listed the parts of stays a reference. What the rule cannot know (the foods the
preparation draws on, whether its recipe is right) is for the curator, and the
preparation is created to review.

A reference is created for any name nothing has (see reference_services), so a
preparation starts as one and is converted here, which is also what the curator's
action does: a reference that was there before the label listed its parts becomes
a preparation the same way.

Nothing is lost. The names, the status and the notes move, the source foods it
drew on become the preparation's, every ingredient that used it points to the
preparation (with its percentage and the parts the label listed for it, which
stay its children), the preparations that were made of it are made of the
preparation, and what it was seen made of on labels becomes the preparation's
components, for the curator to review.
"""

from collections.abc import Iterable
from collections.abc import Sequence

from django.db import IntegrityError
from django.db import transaction
from django.db.models.functions import Lower
from django.utils.translation import gettext as _

from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.services.reference_services import Item
from opennutrilab.products.services.reference_services import name_key
from opennutrilab.products.services.reference_services import walk_ingredients

type Part = ReferenceIngredient | Preparation
_PART_KINDS = (ReferenceIngredient, Preparation)


class PreparationConversionError(Exception):
    """A reference cannot be made a preparation, and is left as it is."""


def parts_seen(reference: ReferenceIngredient) -> list[Part]:
    """
    The references and the preparations this one was seen made of on labels, each
    once.

    They are what the label listed under it, in the order they were first seen. An
    additive is not one: it is not an ingredient the preparation is made of. Nor
    is the reference itself, which a label lists among its own parts ("dattes
    (dattes, farine de riz)").
    """
    seen = (
        Ingredient.objects.filter(parent__reference=reference)
        .exclude(reference=reference)
        .exclude(additive__isnull=False)
        .order_by("id")
        .values_list("reference_id", "preparation_id")
    )
    ordered = list(dict.fromkeys(seen))
    references = ReferenceIngredient.objects.in_bulk(
        [r for r, _p in ordered if r is not None]
    )
    preparations = Preparation.objects.in_bulk(
        [p for _r, p in ordered if p is not None]
    )
    parts: list[Part] = []
    for reference_id, preparation_id in ordered:
        if reference_id is not None:
            parts.append(references[reference_id])
        elif preparation_id is not None:
            parts.append(preparations[preparation_id])
    return parts


def ensure_convertible(reference: ReferenceIngredient) -> None:
    """
    Raise PreparationConversionError if the reference cannot become a preparation.

    A name a preparation already has is refused, since a name leads to one thing.
    """
    if _taken_by_a_preparation(reference):
        raise PreparationConversionError(
            _("A preparation already has the name of %(name)s.")
            % {"name": reference.name}
        )


def _taken_by_a_preparation(reference: ReferenceIngredient) -> bool:
    for field in ("name_en", "name_fr"):
        key = name_key(getattr(reference, field))
        if key and Preparation.objects.alias(key=Lower(field)).filter(key=key).exists():
            return True
    return False


def convert_to_preparation(
    reference: ReferenceIngredient, listed: Iterable[Part] = ()
) -> Preparation:
    """
    The preparation that takes the place of this reference, which is deleted.

    Its components are the parts seen on labels, and `listed`, the parts of the
    label being read. All or nothing: a reference that is refused (see
    ensure_convertible) is untouched.
    """
    ensure_convertible(reference)
    parts = _distinct([*parts_seen(reference), *listed], leaving_out=reference)
    description = reference.description
    if parts:
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
            preparation.components.set(
                part for part in parts if isinstance(part, ReferenceIngredient)
            )
            preparation.preparation_components.set(
                part for part in parts if isinstance(part, Preparation)
            )
            for made_of_it in reference.used_in_preparations.all():
                made_of_it.preparation_components.add(preparation)
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


def _distinct(parts: Iterable[Part], leaving_out: ReferenceIngredient) -> list[Part]:
    """The parts, each once and in order, without the reference itself."""
    kept = {
        (type(part), part.pk): part
        for part in parts
        if (type(part), part.pk) != (ReferenceIngredient, leaving_out.pk)
    }
    return list(kept.values())


def make_preparations_of_listed_parts(
    items: Sequence[IngredientInput], linked: dict[str, Item]
) -> dict[str, Item]:
    """
    `linked` with each reference whose label lists parts made a preparation.

    `linked` is what resolve_references gives for the label's ingredients, by
    name_key: the same name leads to the same one wherever it is listed, so an
    ingredient is a preparation as soon as one place lists its parts. What is not a
    reference (a preparation already, an additive) is left as it is, and so is a
    reference that cannot be converted. The parts come first: a preparation is
    given the preparations among its parts, not the references they were.
    """
    for item in reversed(list(walk_ingredients(items))):
        found = linked[name_key(item.name)]
        if not item.sub_ingredients or not isinstance(found, ReferenceIngredient):
            continue
        listed = [
            part
            for sub in item.sub_ingredients
            if isinstance(part := linked[name_key(sub.name)], _PART_KINDS)
        ]
        pk = found.pk
        try:
            preparation = convert_to_preparation(found, listed)
        except PreparationConversionError:
            continue
        # The deleted instance has no pk any more: it is found by identity.
        for key, value in linked.items():
            if value is found or (
                isinstance(value, ReferenceIngredient) and value.pk == pk
            ):
                linked[key] = preparation
    return linked
