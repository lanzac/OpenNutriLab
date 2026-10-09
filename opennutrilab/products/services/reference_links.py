"""
The links of reference ingredients to the foods of a table, kept in a file.

A link is a row of the database, so a reset loses it, and nothing in the code
says that "quinoa blanc" is CIQUAL's "Quinoa, cru". The links of a food made by
hand are kept by its spec (custom_foods). The others, to the foods of a table a
person chose, are kept in products/data/reference_links.json, by the name of the
reference (an id would not survive a reset) and the code of the food.

Making them again only adds the links that are missing: a reference keeps the
foods it has, and stays "to review", as this replays a decision and takes none.
"""

from dataclasses import dataclass
from typing import Any
from typing import NamedTuple

from django.db import transaction

from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.custom_foods import CustomFoodError
from opennutrilab.products.services.custom_foods import find_food
from opennutrilab.products.services.custom_foods import find_reference
from opennutrilab.products.services.custom_foods import reference_id


class FoodKey(NamedTuple):
    """A food of a source, by the code of the source and its own code."""

    source: str
    code: str


@dataclass(frozen=True)
class ReferenceLink:
    """A reference (an id or a name) and the foods it draws on."""

    reference: int | str
    foods: tuple[FoodKey, ...]


class LinkResult(NamedTuple):
    reference: ReferenceIngredient
    added: tuple[SourceFood, ...]
    # The foods the reference already drew on.
    already: tuple[SourceFood, ...]


def parse_links(data: object) -> list[ReferenceLink]:
    """The links a JSON file holds, checked; raises CustomFoodError."""
    if not isinstance(data, list):
        msg = 'The links are a list of {"reference": ..., "foods": [...]}.'
        raise CustomFoodError(msg)
    items: list[Any] = data  # pyright: ignore[reportUnknownVariableType]
    return [_link(item) for item in items]


def _link(item: object) -> ReferenceLink:
    if not isinstance(item, dict):
        msg = f'A link is {{"reference": ..., "foods": [...]}}, got {item!r}.'
        raise CustomFoodError(msg)
    entry: dict[str, Any] = item  # pyright: ignore[reportUnknownVariableType]
    if extra := sorted(set(entry) - {"reference", "foods"}):
        msg = f"Unknown key(s) in a link: {', '.join(extra)}."
        raise CustomFoodError(msg)
    foods: Any = entry.get("foods")
    if not isinstance(foods, list) or not foods:
        msg = f'A link needs its "foods", a list: {item!r}.'
        raise CustomFoodError(msg)
    foods_list: list[Any] = foods  # pyright: ignore[reportUnknownVariableType]
    return ReferenceLink(
        reference=reference_id(entry.get("reference")),
        foods=tuple(_food(food) for food in foods_list),
    )


def _food(item: object) -> FoodKey:
    if not isinstance(item, dict):
        msg = f'A food is {{"source": ..., "code": ...}}, got {item!r}.'
        raise CustomFoodError(msg)
    entry: dict[str, Any] = item  # pyright: ignore[reportUnknownVariableType]
    if extra := sorted(set(entry) - {"source", "code"}):
        msg = f"Unknown key(s) in a food: {', '.join(extra)}."
        raise CustomFoodError(msg)
    source, code = entry.get("source"), entry.get("code")
    if not (isinstance(source, str) and isinstance(code, str) and source and code):
        msg = f'A food needs its "source" (a source code) and its "code": {item!r}.'
        raise CustomFoodError(msg)
    return FoodKey(source=source, code=code)


def link_reference_foods(link: ReferenceLink) -> LinkResult:
    """Link a reference to its foods; raises CustomFoodError if one is not found."""
    with transaction.atomic():
        reference = find_reference(link.reference)
        foods = [find_food(food.source, food.code) for food in link.foods]
        drawn_on = set(
            reference.source_foods.filter(pk__in=[f.pk for f in foods]).values_list(
                "pk", flat=True
            )
        )
        added = tuple(f for f in foods if f.pk not in drawn_on)
        reference.source_foods.add(*added)
    already = tuple(f for f in foods if f.pk in drawn_on)
    return LinkResult(reference=reference, added=added, already=already)
