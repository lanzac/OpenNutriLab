"""
Loading the table of additives from its dataset.

The dataset (data/additives.json) is the list of additives of the European
Commission with their English names and the French ones of Wikipedia, as the
`regenerate_additives` command builds it (see additive_sources). A migration loads it,
so the table is there without a command, and the command loads it again when it has
rebuilt the dataset.

What is loaded is to review. An additive that is there already, with the same code or,
with no code, the same name, is completed with what it lacks and never overwritten, so
what a person has curated is safe and loading again changes nothing. A name is one
additive's: when two entries share one, the first keeps it and the other is named by
its code. A name that a reference or a preparation has is kept on the additive all the
same: that is the sign that the reference is to be merged into it (see
additive_services).

Nothing of OpenFoodFacts' list stays in the table. What an import made, from that list
or from the dataset, is deleted when nothing has touched it (still to review, used by
no ingredient, no nutrient, no source food) and loaded again from the dataset, so that
the table is the dataset and what a person has worked on. One that a person has
touched keeps what it has, and its note on where it came from is rewritten.
"""

import json
import re
from pathlib import Path
from typing import Any
from typing import NamedTuple

from django.db import transaction
from django.db.models import Q

from opennutrilab.products.models import Additive
from opennutrilab.products.services.reference_services import name_key

DATASET = Path(__file__).resolve().parent.parent / "data" / "additives.json"
EU_SOURCE = "Imported from the European Commission's food additives database"
# What the description of an additive says when an earlier way of filling the table
# made it, from OpenFoodFacts' list.
LEGACY_SOURCES = ("Imported from OpenFoodFacts",)
_NAME_FIELDS = ("name_en", "name_fr")
# The sentence of an additive made from OpenFoodFacts' list that says so.
_LEGACY_NOTE = re.compile(r"^Imported from OpenFoodFacts[^\n]*?\)\.")


class DatasetEntry(NamedTuple):
    code: str
    name_en: str
    name_fr: str
    # The entry in the Commission's portal.
    ref: str


class SyncReport(NamedTuple):
    created: int
    completed: int
    unchanged: int
    # Names left off an additive because another one has them.
    shared_names: int


def _note(entry: DatasetEntry) -> str:
    """Where an additive comes from, for its description."""
    return f"{EU_SOURCE} ({entry.ref or entry.code})."


def read_dataset(
    path: Path | None = None,
) -> tuple[dict[str, Any], list[DatasetEntry]]:
    """The dataset as it is in its file, and its additives."""
    dataset = json.loads((path or DATASET).read_text(encoding="utf-8"))
    entries = [
        DatasetEntry(
            a["code"], a.get("name_en", ""), a.get("name_fr", ""), a.get("ref", "")
        )
        for a in dataset["additives"]
    ]
    return dataset, entries


def write_dataset(dataset: dict[str, Any], path: Path | None = None) -> None:
    """The dataset in its file, in the order it was built, so that a diff reads."""
    (path or DATASET).write_text(
        json.dumps(dataset, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def sync_additives(
    entries: list[DatasetEntry], *, model: type[Additive] = Additive
) -> SyncReport:
    """
    Create the additives of the dataset, and complete those that are there. `model`
    is the Additive class, or the historical one when a migration calls it.
    """
    by_code: dict[str, Additive] = {}
    by_name: dict[str, dict[str, Additive]] = {field: {} for field in _NAME_FIELDS}
    for additive in model.objects.order_by("pk"):
        _index(additive, by_code, by_name)

    created = completed = unchanged = shared = 0
    with transaction.atomic():
        for entry in entries:
            additive = by_code.get(entry.code.lower()) or _unnamed_by(entry, by_name)
            free, left_off = _free_names(entry, additive, by_name)
            shared += left_off
            if additive is None:
                additive = _create(model, entry, free)
                created += 1
            elif _complete(additive, entry, free):
                completed += 1
            else:
                unchanged += 1
            _index(additive, by_code, by_name)
    return SyncReport(created, completed, unchanged, shared)


def clear_untouched(*, model: type[Additive] = Additive) -> int:
    """
    Delete the additives that a list made and that nothing has touched: still to
    review, used by no ingredient, with no nutrient and no source food, which is what
    the table rebuilds from the dataset. Those that OpenFoodFacts' list made and those
    that an earlier loading made go alike. Whatever a person has worked on is kept.
    Returns how many were deleted.
    """
    made_by_a_list = Q(description__startswith=EU_SOURCE)
    for source in LEGACY_SOURCES:
        made_by_a_list |= Q(description__startswith=source)
    untouched = model.objects.filter(
        made_by_a_list,
        status="to_review",
        usages__isnull=True,
        nutrients__isnull=True,
        source_foods__isnull=True,
    ).values_list("pk", flat=True)
    deleted, _per_model = model.objects.filter(pk__in=list(untouched)).delete()
    return deleted


def _is_legacy(additive: Additive) -> bool:
    return additive.description.startswith(LEGACY_SOURCES)


def _index(
    additive: Additive,
    by_code: dict[str, Additive],
    by_name: dict[str, dict[str, Additive]],
) -> None:
    """Remember the additive under its code and names, the first holder keeping one."""
    if additive.code:
        by_code.setdefault(additive.code.lower(), additive)
    for field in _NAME_FIELDS:
        if name := getattr(additive, field):
            by_name[field].setdefault(name_key(name), additive)


def _free_names(
    entry: DatasetEntry,
    additive: Additive | None,
    by_name: dict[str, dict[str, Additive]],
) -> tuple[dict[str, str], int]:
    """
    The names of the entry that nobody has, by field, and how many are left off
    because another additive has them (a name is one additive's).
    """
    free: dict[str, str] = {}
    left_off = 0
    for field, name in (("name_en", entry.name_en), ("name_fr", entry.name_fr)):
        if not name:
            continue
        holder = by_name[field].get(name_key(name))
        if holder is None:
            free[field] = name
        elif holder is not additive:
            left_off += 1
    return free, left_off


def _unnamed_by(
    entry: DatasetEntry, by_name: dict[str, dict[str, Additive]]
) -> Additive | None:
    """An additive with no code that has the name of this entry, if there is one."""
    for field, name in (("name_en", entry.name_en), ("name_fr", entry.name_fr)):
        found = by_name[field].get(name_key(name)) if name else None
        if found is not None and not found.code:
            return found
    return None


def _create(
    model: type[Additive], entry: DatasetEntry, free: dict[str, str]
) -> Additive:
    return model.objects.create(
        name_en=free.get("name_en", "") or ("" if free.get("name_fr") else entry.code),
        name_fr=free.get("name_fr", ""),
        code=entry.code,
        description=_note(entry),
        status="to_review",
    )


def _complete(additive: Additive, entry: DatasetEntry, free: dict[str, str]) -> bool:
    """
    Give the additive what it lacks of the entry, and say where it comes from if
    a list it has since been dropped made it. Whether anything changed.
    """
    changed: list[str] = []
    if not additive.code:
        additive.code = entry.code
        changed.append("code")
    if _is_legacy(additive):
        additive.description = _LEGACY_NOTE.sub(
            lambda _match: _note(entry), additive.description, count=1
        )
        changed.append("description")
    for field, name in free.items():
        if not getattr(additive, field):
            setattr(additive, field, name)
            changed.append(field)
    if changed:
        additive.save(update_fields=changed)
    return bool(changed)
