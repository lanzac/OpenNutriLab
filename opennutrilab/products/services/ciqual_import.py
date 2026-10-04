"""
Loading ANSES' CIQUAL food composition table as a Source with its foods.

CIQUAL is published as four XML files (the foods, their groups, the
constituents, and the composition: one row per food and constituent). The
composition file is about 70 MB, so it is read as a stream and written in
batches.

The values keep the meaning the source gives them. In `teneur`: "-" is not
measured (empty, never 0), "< x" is below the detection limit x, "traces" is
traces, and anything else is a number with a decimal comma. Each value has a
grade from A (best) to D, and sometimes the minimum and maximum the data spans.

The nutrients that are a sum of others (vitamin A from retinol and
beta-carotene...) are set up once the constituents are there, see
derived_nutrients.

Prepared dishes, sauces and stocks are not ingredients, so they are not
imported (see EXCLUDED_*). Importing again updates what changed and adds
nothing twice; a food that was imported and is now excluded is left as it is.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from decimal import InvalidOperation
from pathlib import Path
from typing import NamedTuple

import requests
from django.db import transaction

from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.ciqual_constituents import CONSTITUENTS
from opennutrilab.products.services.ciqual_constituents import SKIPPED
from opennutrilab.products.services.derived_nutrients import ensure_derivations

# The table is published on recherche.data.gouv.fr; this DOI always leads to the
# latest release.
DATASET_DOI = "doi:10.57745/RDMHWY"
DATASET_API = "https://entrepot.recherche.data.gouv.fr/api/datasets/:persistentId/"
FILE_API = "https://entrepot.recherche.data.gouv.fr/api/access/datafile/{id}"
CIQUAL_URL = "https://ciqual.anses.fr"
DOWNLOAD_HEADERS = {"User-Agent": "OpenNutriLab"}

BATCH_SIZE = 5_000
CHUNK_SIZE = 1 << 20

# alim_2025_11_03.xml: the stem, then the date of the data.
FILE_NAME = re.compile(r"^(alim|alim_grp|compo|const)_(\d{4})_(\d{2})_(\d{2})\.xml$")

# Not ingredients. Whole groups first, then sub-groups, then single foods where
# a sub-group mixes ingredients and preparations: "aides culinaires" (1003)
# holds yeast, gelatin, bicarbonate and brans, which stay, and stocks, which
# do not (reconstituted stocks are among the soups, in group 01).
EXCLUDED_GROUPS = frozenset(
    {
        "00",  # An average dessert.
        "01",  # Starters and prepared dishes: salads, soups, pizzas, sandwiches...
    }
)
EXCLUDED_SUBGROUPS = frozenset(
    {
        "1001",  # Sauces.
    }
)
EXCLUDED_FOODS: dict[str, str] = {
    "11001": "Bouillon de boeuf, déshydraté",
    "11041": "Bouillon de légumes, déshydraté",
    "11043": "Tapenade, préemballée",
    "11169": "Fond de veau pour sauces et cuisson, déshydraté",
    "11171": "Fond de volaille pour sauces et cuisson, déshydraté",
    "11172": "Court-bouillon pour poissons, déshydraté",
    "11174": "Bouillon de volaille, déshydraté",
    "11175": "Gelée au madère, déshydratée",
    "11176": "Gelée au madère",
    "11303": "Fumet de poisson, prêt à consommer, préemballé",
    "11304": "Fond de veau, préemballé",
    "25525": "Sauce tomate cuisinée pour pizza",
    "25970": "Bouillon de viande et légumes type pot-au-feu, non dégraissé, déshydraté",
    "25971": "Bouillon de viande et légumes type pot-au-feu, dégraissé, déshydraté",
    "37000": "Base de pizza (pâte et sauce à la crème), crue",
    "37002": "Base de pizza (pâte et sauce à la tomate), crue",
}

GRADES = frozenset({"A", "B", "C", "D", ""})
_UNIT = re.compile(r"\s*\((?P<unit>[^()/]+)/100\s?g\)\s*$")
UNITS = {
    "kj": Nutrient.Unit.KILOJOULE.value,
    "g": Nutrient.Unit.GRAM.value,
    "mg": Nutrient.Unit.MILLIGRAM.value,
    "µg": Nutrient.Unit.MICROGRAM.value,  # The micro sign.
    "μg": Nutrient.Unit.MICROGRAM.value,  # The Greek letter mu.
    "ug": Nutrient.Unit.MICROGRAM.value,
}
_DIGITS = Decimal(1).scaleb(-6)  # What SourceFoodNutrient stores.


class CiqualError(Exception):
    """The files, or the catalogue, are not what the import expects."""


class CiqualFiles(NamedTuple):
    foods: Path
    groups: Path
    composition: Path
    constituents: Path
    # The date of the data, from the files' names.
    released: date


class FileConstituent(NamedTuple):
    code: str
    name_fr: str
    name_en: str
    # As the label gives it: "mg", "µg", "kcal"...
    unit: str


class FoodRecord(NamedTuple):
    code: str
    name_fr: str
    name_en: str
    group: str
    subgroup: str


class Value(NamedTuple):
    food: str
    constituent: str
    amount: Decimal | None
    qualifier: SourceFoodNutrient.Qualifier
    minimum: Decimal | None
    maximum: Decimal | None
    confidence: str


@dataclass
class ImportReport:
    source: Source
    foods: int
    excluded: int
    nutrients_created: int
    values: int
    derived: int


# ----------------------------------------------------------------------------
# Reading the files
# ----------------------------------------------------------------------------
def find_files(directory: Path) -> CiqualFiles:
    """The four files of a release in `directory`, which names them by date."""
    found: dict[str, tuple[Path, date]] = {}
    for path in sorted(directory.iterdir()):
        match = FILE_NAME.match(path.name)
        if match is None:
            continue
        stem = match.group(1)
        if stem in found:
            msg = (
                f"More than one {stem} file in {directory}: "
                f"{found[stem][0].name}, {path.name}."
            )
            raise CiqualError(msg)
        found[stem] = (path, date(*(int(part) for part in match.groups()[1:])))
    missing = {"alim", "alim_grp", "compo", "const"} - found.keys()
    if missing:
        msg = f"{directory} lacks the CIQUAL file(s): {', '.join(sorted(missing))}."
        raise CiqualError(msg)
    return CiqualFiles(
        foods=found["alim"][0],
        groups=found["alim_grp"][0],
        composition=found["compo"][0],
        constituents=found["const"][0],
        released=found["compo"][1],
    )


def _records(path: Path, tag: str) -> Iterator[dict[str, str]]:
    """The children of each `tag` element, as text, without loading the file."""
    try:
        # ANSES' file, fetched over HTTPS, or one the operator chose: not untrusted.
        context = ET.iterparse(path, events=("start", "end"))  # noqa: S314
        _event, root = next(context)
        for event, element in context:
            if event == "end" and element.tag == tag:
                yield {child.tag: (child.text or "").strip() for child in element}
                root.clear()
    except (OSError, ET.ParseError) as e:
        msg = f"Could not read {path}: {e}"
        raise CiqualError(msg) from e


def read_constituents(path: Path) -> list[FileConstituent]:
    return [
        FileConstituent(
            code=record["const_code"],
            name_fr=_strip_unit(record["const_nom_fr"]),
            name_en=_strip_unit(record["const_nom_eng"]),
            unit=_unit_of(record["const_nom_fr"]),
        )
        for record in _records(path, "CONST")
    ]


def _unit_of(label: str) -> str:
    match = _UNIT.search(label)
    if match is None:
        msg = f"No unit at the end of the constituent label {label!r}."
        raise CiqualError(msg)
    return match["unit"].strip()


def _strip_unit(label: str) -> str:
    return _UNIT.sub("", label).strip()


def is_excluded(record: dict[str, str]) -> bool:
    return (
        record["alim_grp_code"] in EXCLUDED_GROUPS
        or record["alim_ssgrp_code"] in EXCLUDED_SUBGROUPS
        or record["alim_code"] in EXCLUDED_FOODS
    )


def read_foods(foods: Path, groups: Path) -> tuple[list[FoodRecord], set[str]]:
    """The foods that are imported, and the codes of those left out."""
    group_names: dict[str, str] = {}
    subgroup_names: dict[str, str] = {}
    for record in _records(groups, "ALIM_GRP"):
        group_names[record["alim_grp_code"]] = record["alim_grp_nom_fr"]
        subgroup_names[record["alim_ssgrp_code"]] = _blank_dash(
            record["alim_ssgrp_nom_fr"]
        )

    kept: list[FoodRecord] = []
    excluded: set[str] = set()
    for record in _records(foods, "ALIM"):
        if is_excluded(record):
            excluded.add(record["alim_code"])
            continue
        group, subgroup = record["alim_grp_code"], record["alim_ssgrp_code"]
        kept.append(
            FoodRecord(
                code=record["alim_code"],
                name_fr=record["alim_nom_fr"],
                name_en=record["alim_nom_eng"],
                group=_blank_dash(group_names.get(group, "")),
                subgroup=subgroup_names.get(subgroup, ""),
            )
        )
    return kept, excluded


def _blank_dash(name: str) -> str:
    return "" if name == "-" else name


def parse_value(record: dict[str, str]) -> Value:
    """One row of the composition file."""
    text = record["teneur"]
    amount: Decimal | None
    if text == "-":
        # Not measured: empty, never 0.
        amount, qualifier = None, SourceFoodNutrient.Qualifier.EXACT
    elif text == "traces":
        amount, qualifier = None, SourceFoodNutrient.Qualifier.TRACES
    elif text.startswith("<"):
        amount = _decimal(text[1:])
        qualifier = SourceFoodNutrient.Qualifier.LESS_THAN
    else:
        amount, qualifier = _decimal(text), SourceFoodNutrient.Qualifier.EXACT
    confidence = record["code_confiance"]
    if confidence not in GRADES:
        msg = f"Unknown confidence grade {confidence!r} for {record['alim_code']}."
        raise CiqualError(msg)
    return Value(
        food=record["alim_code"],
        constituent=record["const_code"],
        amount=amount,
        qualifier=qualifier,
        minimum=_decimal(record["min"]) if record["min"] else None,
        maximum=_decimal(record["max"]) if record["max"] else None,
        confidence=confidence,
    )


def _decimal(text: str) -> Decimal:
    try:
        return Decimal(text.strip().replace(",", ".")).quantize(_DIGITS)
    except InvalidOperation as e:
        msg = f"Not a number: {text!r}."
        raise CiqualError(msg) from e


def read_values(path: Path) -> Iterator[Value]:
    for record in _records(path, "COMPO"):
        yield parse_value(record)


# ----------------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------------
def attribution(released: date) -> str:
    return (
        "Anses. Table de composition nutritionnelle des aliments Ciqual "
        f"{released.year} (données du {released.isoformat()}). {CIQUAL_URL}. "
        "Licence Ouverte 2.0 (Etalab)."
    )


def ensure_nutrients(
    constituents: list[FileConstituent],
) -> tuple[dict[str, Nutrient], int]:
    """
    The nutrient of each CIQUAL code that is imported, creating those missing.

    Refuses a constituent the mapping does not know, and a unit that differs
    from the catalogue's, before anything is written.
    """
    unknown = [
        f"{c.code} ({c.name_en})"
        for c in constituents
        if c.code not in CONSTITUENTS and c.code not in SKIPPED
    ]
    if unknown:
        msg = (
            "CIQUAL constituents the import does not know (add them to "
            f"ciqual_constituents): {', '.join(unknown)}."
        )
        raise CiqualError(msg)

    by_code = {c.code: c for c in constituents}
    order = {code: index for index, code in enumerate(by_code)}
    nutrients: dict[str, Nutrient] = {}
    created = 0
    # Parents are created before their children, in the order of CONSTITUENTS.
    for code, mapped in CONSTITUENTS.items():
        row = by_code.get(code)
        if row is None:
            continue
        unit = UNITS.get(row.unit.lower())
        if unit is None:
            msg = f"Constituent {code} ({row.name_en}) has the unit {row.unit!r}."
            raise CiqualError(msg)
        nutrient = (
            Nutrient.objects.filter(ciqual_code=code).first()
            or Nutrient.objects.filter(code=mapped.code, ciqual_code=None).first()
        )
        if nutrient is None:
            nutrient = Nutrient.objects.create(
                code=mapped.code,
                name_en=row.name_en,
                name_fr=row.name_fr,
                unit=unit,
                group=mapped.group,
                parent_id=mapped.parent,
                display_order=100 + 10 * order[code],
                ciqual_code=code,
            )
            created += 1
        elif nutrient.ciqual_code is None:
            nutrient.ciqual_code = code
            nutrient.save(update_fields=["ciqual_code"])
        if nutrient.unit != unit:
            msg = (
                f"Constituent {code} ({row.name_en}) is in {unit} in CIQUAL, "
                f"and {nutrient.unit} for the nutrient {nutrient.code}."
            )
            raise CiqualError(msg)
        nutrients[code] = nutrient
    return nutrients, created


def import_ciqual(
    directory: Path, progress: Callable[[str], None] = lambda _message: None
) -> ImportReport:
    """Load the CIQUAL release in `directory`; see the module's docstring."""
    files = find_files(directory)
    constituents = read_constituents(files.constituents)
    foods, excluded = read_foods(files.foods, files.groups)
    progress(f"{len(foods)} foods to import, {len(excluded)} left out.")

    with transaction.atomic():
        nutrients, created = ensure_nutrients(constituents)
        derived = ensure_derivations()
        source, _created = Source.objects.update_or_create(
            code=f"ciqual-{files.released.year}",
            defaults={
                "name": "Ciqual",
                "version": str(files.released.year),
                "url": CIQUAL_URL,
                "attribution": attribution(files.released),
            },
        )
        food_ids = _upsert_foods(source, foods)
        progress("Foods written; writing the values...")
        values = _upsert_values(
            files.composition, food_ids, excluded, nutrients, progress
        )
    return ImportReport(source, len(foods), len(excluded), created, values, derived)


def _upsert_foods(source: Source, foods: list[FoodRecord]) -> dict[str, int]:
    SourceFood.objects.bulk_create(
        [
            SourceFood(
                source=source,
                code=food.code,
                name_fr=food.name_fr,
                name_en=food.name_en,
                food_group=food.group,
                food_subgroup=food.subgroup,
            )
            for food in foods
        ],
        batch_size=BATCH_SIZE,
        update_conflicts=True,
        unique_fields=["source", "code"],
        update_fields=["name_fr", "name_en", "food_group", "food_subgroup"],
    )
    return dict(SourceFood.objects.filter(source=source).values_list("code", "id"))


def _upsert_values(
    path: Path,
    food_ids: dict[str, int],
    excluded: set[str],
    nutrients: dict[str, Nutrient],
    progress: Callable[[str], None],
) -> int:
    batch: list[SourceFoodNutrient] = []
    written = 0
    for value in read_values(path):
        if value.food in excluded or value.constituent in SKIPPED:
            continue
        food_id = food_ids.get(value.food)
        nutrient = nutrients.get(value.constituent)
        if food_id is None or nutrient is None:
            msg = (
                f"The composition has a value for food {value.food} and "
                f"constituent {value.constituent}, which the other files lack."
            )
            raise CiqualError(msg)
        batch.append(
            SourceFoodNutrient(
                food_id=food_id,
                nutrient=nutrient,
                amount=value.amount,
                minimum=value.minimum,
                maximum=value.maximum,
                qualifier=value.qualifier,
                confidence=value.confidence,
            )
        )
        if len(batch) >= BATCH_SIZE:
            written += _flush(batch)
            progress(f"{written} values written...")
    return written + _flush(batch)


def _flush(batch: list[SourceFoodNutrient]) -> int:
    count = len(batch)
    SourceFoodNutrient.objects.bulk_create(
        batch,
        batch_size=BATCH_SIZE,
        update_conflicts=True,
        unique_fields=["food", "nutrient"],
        update_fields=["amount", "minimum", "maximum", "qualifier", "confidence"],
    )
    batch.clear()
    return count


# ----------------------------------------------------------------------------
# Downloading
# ----------------------------------------------------------------------------
def download_ciqual(
    directory: Path, progress: Callable[[str], None] = lambda _message: None
) -> None:
    """Fetch the four files of the latest release into `directory`."""
    try:
        response = requests.get(
            DATASET_API,
            params={"persistentId": DATASET_DOI},
            headers=DOWNLOAD_HEADERS,
            timeout=60,
        )
        response.raise_for_status()
        listed = response.json()["data"]["latestVersion"]["files"]
        wanted = [
            (item["dataFile"]["id"], item["dataFile"]["filename"])
            for item in listed
            if FILE_NAME.match(item["dataFile"]["filename"])
        ]
        for file_id, name in wanted:
            progress(f"Downloading {name}...")
            with requests.get(
                FILE_API.format(id=file_id),
                headers=DOWNLOAD_HEADERS,
                stream=True,
                timeout=(10, 120),
            ) as download:
                download.raise_for_status()
                with (directory / name).open("wb") as out:
                    for chunk in download.iter_content(CHUNK_SIZE):
                        out.write(chunk)
    except (OSError, requests.RequestException, KeyError, ValueError) as e:
        msg = f"Could not download the CIQUAL table from {DATASET_API}: {e}"
        raise CiqualError(msg) from e
