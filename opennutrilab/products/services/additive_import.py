"""
Filling the table of additives, from the European Commission's list and, for their
French names, from OpenFoodFacts'.

A label names an additive by its name ("acide citrique") as often as by its E number,
and only a table that knows the name can find it. The list that says which additives
exist is the European Commission's (the Union list of Regulation (EC) 1333/2008, as
its Food and Feed Information Portal publishes it): the substances that have an E
number, with their English name. That is what creates additives. OpenFoodFacts'
taxonomy of additives is wider and less careful (it has the sub-forms, enzymes, and
colours that are no longer authorised, and classes that cannot be trusted: E330 is
"antioxidant, sequestrant" there and not an acid), so it creates nothing: it only
completes the names, which the Union list gives in English alone.

Nothing gives a class: the class of an additive comes from a label that gives it, or
from the curator. Nothing gives a composition either.

What is imported is to review. An additive that exists already, with the same code
or, with no code, the same name, is completed with what it lacks and never
overwritten, so the lists can be imported again and a curated additive is safe. A
name is one additive's: when two entries share one ("riboflavin"), the first keeps it
and the other is named by its code. A name that a reference or a preparation has is
kept on the additive all the same: that is the sign that the reference is to be
merged into it (see additive_services).
"""

import html
import re
from collections import defaultdict
from collections.abc import Iterator
from typing import Any
from typing import NamedTuple

from django.db import transaction

from opennutrilab.products.models import Additive
from opennutrilab.products.services.label_parser import e_number
from opennutrilab.products.services.reference_services import name_key

EU_SOURCE = "Imported from the European Commission's food additives database"
OFF_SOURCE = "Imported from OpenFoodFacts' additives"
# "E330 - Acide citrique": the code that heads every name of OpenFoodFacts.
_CODE_PREFIX = re.compile(r"^E\s?[0-9][0-9a-z()]*\s*(?:-\s*)?", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_MAX_NAME = 255
_NAME_FIELDS = ("name_en", "name_fr")


class ImportedAdditive(NamedTuple):
    # Where the entry is in its source: its code there, or its tag.
    source_ref: str
    code: str
    name_en: str
    name_fr: str


class ImportReport(NamedTuple):
    created: int
    completed: int
    unchanged: int
    # Names left off an additive because another one has them.
    shared_names: int


# ----------------------------------------------------------------------------
# Reading the lists
# ----------------------------------------------------------------------------
def additives_of_union_list(
    items: list[Any],
) -> tuple[list[ImportedAdditive], list[str]]:
    """
    The substances of the Union list that have a usable E number, in the order of
    their numbers, and what was left out and why.

    The portal's list has what is not a code (a group of conditions of use, a
    substance that was removed, one still without a number, a placeholder), which
    is left out and said, and its names can carry the HTML of the page they were
    typed in.
    """
    found: dict[str, ImportedAdditive] = {}
    left_out: list[str] = []
    for item in items:
        fields = _fields(item)
        if fields.get("policyItemType") != ["substanceFAD"]:
            continue  # A group of additives, which is not one.
        name = _plain(next(iter(fields.get("displayName", [])), ""))
        raw = next(iter(fields.get("substanceFAD/eNumber", [])), "").strip()
        if raw.isdigit():
            raw = f"E{raw}"  # The list has "1210" for E 1210: a number is a number.
        if "REMOVED" in raw.upper():
            left_out.append(f"{name}: removed from the Union list")
        elif not (code := e_number(raw)):
            left_out.append(f"{name}: no usable E number ({raw or 'none'})")
        elif code not in found:
            ref = next(iter(fields.get("policyItemCode", [])), code)
            found[code] = ImportedAdditive(ref, code, name[:_MAX_NAME], "")
    return sorted(found.values(), key=lambda a: _number_order(a.code)), left_out


def additives_of_taxonomy(
    taxonomy: dict[str, Any],
) -> tuple[list[ImportedAdditive], int]:
    """
    The entries of OpenFoodFacts' taxonomy that are an E number, in the order of
    their numbers, and how many entries were left out.
    """
    found: list[ImportedAdditive] = []
    skipped = 0
    for off_id, entry in taxonomy.items():
        code = e_number(off_id.partition(":")[2])
        if not code:
            skipped += 1
            continue
        names: dict[str, Any] = entry.get("name") or {}
        found.append(
            ImportedAdditive(
                off_id,
                code,
                _substance(names.get("en", ""), code),
                _substance(names.get("fr", ""), code),
            )
        )
    return sorted(found, key=lambda a: _number_order(a.code)), skipped


def _fields(item: dict[str, Any]) -> dict[str, list[str]]:
    """
    What a policy item of the portal says, by field, as the portal nests it
    ("substanceFAD/eNumber"), without its conditions of use, which are not read.
    """
    out: dict[str, list[str]] = defaultdict(list)
    for path, value in _leaves(item, ()):
        if "conditionsOfUse" in path or "legislationWrapper" in path:
            continue
        key = "/".join(path).replace("policyItemObject/", "")
        out[key.replace("policyItemSpecs/", "")].append(str(value))
    return out


def _leaves(
    node: dict[str, Any], path: tuple[str, ...]
) -> Iterator[tuple[tuple[str, ...], Any]]:
    ident = node.get("valueIdentifier")
    here = (*path, ident) if ident else path
    children: list[dict[str, Any]] = node.get("childrenValues") or []
    if not children and node.get("value") not in (None, ""):
        yield here, node["value"]
    for child in children:
        yield from _leaves(child, here)


def _plain(text: str) -> str:
    """A name without the markup and the entities it was typed in."""
    return " ".join(html.unescape(_TAG.sub("", text)).split())


def _number_order(code: str) -> tuple[int, str]:
    """E100 before E1000, and E160a before E160b."""
    digits = re.match(r"E(\d+)", code)
    return (int(digits.group(1)) if digits else 0, code)


def _substance(name: object, code: str) -> str:
    """The name of the substance: what follows "E330 - ", nothing if it is the code."""
    text = _CODE_PREFIX.sub("", str(name)).strip()[:_MAX_NAME]
    return "" if e_number(text) == code else text


# ----------------------------------------------------------------------------
# Filling the table
# ----------------------------------------------------------------------------
def import_additives(
    imported: list[ImportedAdditive], *, source: str, create: bool = True
) -> ImportReport:
    """
    Create the additives of a list, and complete those that are there. With
    `create` off, only those that are there are completed.
    """
    by_code: dict[str, Additive] = {}
    by_name: dict[str, dict[str, Additive]] = {field: {} for field in _NAME_FIELDS}
    for additive in Additive.objects.order_by("pk"):
        _index(additive, by_code, by_name)

    created = completed = unchanged = shared = 0
    with transaction.atomic():
        for entry in imported:
            additive = by_code.get(entry.code.lower()) or _unnamed_by(entry, by_name)
            if additive is None and not create:
                continue
            free, left_off = _free_names(entry, additive, by_name)
            shared += left_off
            if additive is None:
                additive = _create(entry, free, source)
                created += 1
            elif _complete(additive, entry.code, free):
                completed += 1
            else:
                unchanged += 1
            _index(additive, by_code, by_name)
    return ImportReport(created, completed, unchanged, shared)


def prune_additives(keep: set[str]) -> int:
    """
    Delete the additives that an earlier import made from OpenFoodFacts' list and
    that the Union list does not have, if nothing has touched them: still to
    review, used by no ingredient, with no nutrient and no source food. Whatever a
    person has worked on is kept. Returns how many were deleted.
    """
    kept = {code.lower() for code in keep}
    unused = Additive.objects.filter(
        description__startswith=OFF_SOURCE,
        status=Additive.Status.TO_REVIEW,
        usages__isnull=True,
        nutrients__isnull=True,
        source_foods__isnull=True,
    ).distinct()
    doomed = [a.pk for a in unused if a.code.lower() not in kept]
    deleted, _per_model = Additive.objects.filter(pk__in=doomed).delete()
    return deleted


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
    entry: ImportedAdditive,
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
    entry: ImportedAdditive, by_name: dict[str, dict[str, Additive]]
) -> Additive | None:
    """An additive with no code that has the name of this entry, if there is one."""
    for field, name in (("name_en", entry.name_en), ("name_fr", entry.name_fr)):
        found = by_name[field].get(name_key(name)) if name else None
        if found is not None and not found.code:
            return found
    return None


def _create(entry: ImportedAdditive, free: dict[str, str], source: str) -> Additive:
    return Additive.objects.create(
        name_en=free.get("name_en", "") or ("" if free.get("name_fr") else entry.code),
        name_fr=free.get("name_fr", ""),
        code=entry.code,
        description=f"{source} ({entry.source_ref}).",
        status=Additive.Status.TO_REVIEW,
    )


def _complete(additive: Additive, code: str, free: dict[str, str]) -> bool:
    """Give the additive what it lacks of the entry. Whether anything changed."""
    changed: list[str] = []
    if not additive.code:
        additive.code = code
        changed.append("code")
    for field, name in free.items():
        if not getattr(additive, field):
            setattr(additive, field, name)
            changed.append(field)
    if changed:
        additive.save(update_fields=changed)
    return bool(changed)
