"""
The links of reference ingredients to the foods of a table, kept in a file.

A link is a row of the database, so a reset loses it, and nothing in the code
says that "quinoa blanc" is CIQUAL's "Quinoa, cru". The links of a food made by
hand are kept by its spec (custom_foods). The others, to the foods of a table a
person chose, are kept in products/data/reference_links.json, by the name of the
reference (an id would not survive a reset) and the code of the food, with the
food that gives its value when they are forms of it (`default_food`).

Making them again only adds the links that are missing, and gives a default to a
reference that has none: a reference keeps the foods and the default it has, and
stays "to review", as this replays a decision and takes none.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import NamedTuple

from django.db import transaction

from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.custom_foods import MANUAL_SOURCE_CODE
from opennutrilab.products.services.custom_foods import CustomFoodError
from opennutrilab.products.services.custom_foods import find_food
from opennutrilab.products.services.custom_foods import find_reference
from opennutrilab.products.services.custom_foods import reference_id

LINKS_FILE = Path(__file__).parents[1] / "data" / "reference_links.json"


class FoodKey(NamedTuple):
    """A food of a source, by the code of the source and its own code."""

    source: str
    code: str


@dataclass(frozen=True)
class ReferenceLink:
    """A reference (an id or a name), the foods it draws on, and its default."""

    reference: int | str
    foods: tuple[FoodKey, ...]
    default: FoodKey | None = None


class LinkResult(NamedTuple):
    reference: ReferenceIngredient
    added: tuple[SourceFood, ...]
    # The foods the reference already drew on.
    already: tuple[SourceFood, ...]
    # The default the link gave to a reference that had none.
    default_set: SourceFood | None = None
    # The default the reference has, when it is not the one the link names.
    default_kept: SourceFood | None = None


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
    if extra := sorted(set(entry) - {"reference", "foods", "default"}):
        msg = f"Unknown key(s) in a link: {', '.join(extra)}."
        raise CustomFoodError(msg)
    foods: Any = entry.get("foods")
    if not isinstance(foods, list) or not foods:
        msg = f'A link needs its "foods", a list: {item!r}.'
        raise CustomFoodError(msg)
    foods_list: list[Any] = foods  # pyright: ignore[reportUnknownVariableType]
    default = entry.get("default")
    return ReferenceLink(
        reference=reference_id(entry.get("reference")),
        foods=tuple(_food(food) for food in foods_list),
        default=None if default is None else _food(default),
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
        default_set, default_kept = _default(reference, link.default)
    already = tuple(f for f in foods if f.pk in drawn_on)
    return LinkResult(reference, added, already, default_set, default_kept)


def _default(
    reference: ReferenceIngredient, key: FoodKey | None
) -> tuple[SourceFood | None, SourceFood | None]:
    """Give the default to a reference with none; the one it has is kept."""
    if key is None:
        return None, None
    food = find_food(key.source, key.code)
    if not reference.source_foods.filter(pk=food.pk).exists():
        msg = (
            f"{key.code!r} is the default of {reference.name!r}, not one of its foods."
        )
        raise CustomFoodError(msg)
    if reference.default_food_id is None:
        reference.default_food = food
        reference.save(update_fields=["default_food"])
        return food, None
    if reference.default_food_id != food.pk:
        return None, reference.default_food
    return None, None


# ----------------------------------------------------------------------------
# Keeping the links of the database in the file
# ----------------------------------------------------------------------------
class Kept(NamedTuple):
    links: list[ReferenceLink]
    # References that no name finds alone, which a replay could not tell apart.
    unnamed: list[ReferenceIngredient]


def links_to_keep() -> Kept:
    """The links of the references to the foods of a table, as the database has them.

    A food made by hand is left out: its spec links it. A reference that has only
    such foods is left out with them, and one that has both keeps its foods of a
    table and a default that is a food made by hand.
    """
    of_a_table = SourceFood.objects.exclude(source__code=MANUAL_SOURCE_CODE)
    references = (
        ReferenceIngredient.objects.filter(source_foods__in=of_a_table)
        .distinct()
        .select_related("default_food__source")
        .order_by("pk")
    )
    links: list[ReferenceLink] = []
    unnamed: list[ReferenceIngredient] = []
    for reference in references:
        name = _name_that_finds(reference)
        if name is None:
            unnamed.append(reference)
            continue
        foods = (
            reference.source_foods.exclude(source__code=MANUAL_SOURCE_CODE)
            .select_related("source")
            .order_by("source__code", "code")
        )
        default = reference.default_food
        links.append(
            ReferenceLink(
                reference=name,
                foods=tuple(FoodKey(f.source.code, f.code) for f in foods),
                default=FoodKey(default.source.code, default.code) if default else None,
            )
        )
    links.sort(key=lambda link: str(link.reference).lower())
    return Kept(links, unnamed)


def _name_that_finds(reference: ReferenceIngredient) -> str | None:
    """The French or English name that finds this reference and no other."""
    for name in (reference.name_fr, reference.name_en):
        if not name:
            continue
        try:
            if find_reference(name).pk == reference.pk:
                return name
        except CustomFoodError:
            continue
    return None


def links_as_data(links: list[ReferenceLink]) -> list[dict[str, Any]]:
    """The links as the JSON file holds them."""
    data: list[dict[str, Any]] = []
    for link in links:
        entry: dict[str, Any] = {
            "reference": link.reference,
            "foods": [f._asdict() for f in link.foods],
        }
        if link.default is not None:
            entry["default"] = link.default._asdict()
        data.append(entry)
    return data
