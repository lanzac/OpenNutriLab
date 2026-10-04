import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from xml.sax.saxutils import escape

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError

from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services import ciqual_import
from opennutrilab.products.services.ciqual_constituents import CONSTITUENTS
from opennutrilab.products.services.ciqual_constituents import SKIPPED
from opennutrilab.products.services.ciqual_import import CiqualError
from opennutrilab.products.services.ciqual_import import import_ciqual
from opennutrilab.products.services.ciqual_import import parse_value
from opennutrilab.products.services.ciqual_import import read_constituents

DATA = Path(__file__).parent / "data"
# The real list of CIQUAL 2025's 74 constituents.
CONSTITUENTS_FILE = DATA / "ciqual_const_2025.xml"
EXACT = SourceFoodNutrient.Qualifier.EXACT
LESS_THAN = SourceFoodNutrient.Qualifier.LESS_THAN
TRACES = SourceFoodNutrient.Qualifier.TRACES

GROUPS = [
    ("02", "fruits, légumes, légumineuses et oléagineux", "0201", "légumes"),
    ("01", "entrées et plats composés", "0105", "sandwichs"),
    ("10", "aides culinaires et ingrédients divers", "1001", "sauces"),
    ("10", "aides culinaires et ingrédients divers", "1003", "aides culinaires"),
    ("10", "aides culinaires et ingrédients divers", "1004", "sels"),
    ("00", "-", "0000", "-"),
]

# code, French, English, group, sub-group
FOODS = [
    ("20009", "Carotte, crue", "Carrot, raw", "02", "0201"),
    ("11058", "Sel blanc", "Salt, white", "10", "1004"),
    ("11010", "Levure de boulanger fraîche", "Baker's yeast, fresh", "10", "1003"),
    # Left out: a prepared dish, a sauce, a stock.
    ("25000", "Sandwich jambon-beurre", "Ham sandwich", "01", "0105"),
    ("11013", "Ketchup", "Ketchup", "10", "1001"),
    ("11001", "Bouillon de boeuf, déshydraté", "Beef stock, dried", "10", "1003"),
]


def xml(tag: str, records: list[dict[str, str]]) -> str:
    rows = "".join(
        f"<{tag}>"
        + "".join(
            f'<{key} missing=" " />'
            if value == ""
            else f"<{key}> {escape(value)} </{key}>"
            for key, value in record.items()
        )
        + f"</{tag}>"
        for record in records
    )
    return f'<?xml version="1.0" encoding="utf-8" ?>\n<TABLE>{rows}</TABLE>'


def value(  # noqa: PLR0913
    food: str,
    constituent: str,
    teneur: str,
    confidence: str = "B",
    minimum: str = "",
    maximum: str = "",
) -> dict[str, str]:
    return {
        "alim_code": food,
        "const_code": constituent,
        "teneur": teneur,
        "min": minimum,
        "max": maximum,
        "code_confiance": confidence,
        "source_code": "1",
    }


VALUES = [
    value("20009", "55100", "9,3", "B", "7,1", "11,9"),  # Vitamin C, mg
    value("20009", "52100", "-", ""),  # Vitamin D: not measured
    value("20009", "10530", "traces", "C"),  # Iodine
    value("20009", "10004", "< 0,02", "A"),  # Salt
    value("20009", "56600", "0,000123", "D"),  # Vitamin B12, six decimals
    value("20009", "328", "41", "A"),  # Energy in kcal: skipped
    value("11058", "10004", "99,9", "A"),
    value("11010", "56100", "2,2", "C"),
    # Foods that are left out: their values are ignored.
    value("25000", "55100", "1", "D"),
    value("11013", "55100", "2", "D"),
    value("11001", "55100", "3", "D"),
]


def release(
    directory: Path,
    foods: list[tuple[str, ...]] = FOODS,
    values: list[dict[str, str]] = VALUES,
    constituents: Path = CONSTITUENTS_FILE,
    date: str = "2025_11_03",
) -> Path:
    directory.mkdir(exist_ok=True)
    shutil.copy(constituents, directory / f"const_{date}.xml")
    (directory / f"alim_grp_{date}.xml").write_text(
        xml(
            "ALIM_GRP",
            [
                {
                    "alim_grp_code": group,
                    "alim_grp_nom_fr": group_name,
                    "alim_grp_nom_eng": group_name,
                    "alim_ssgrp_code": subgroup,
                    "alim_ssgrp_nom_fr": subgroup_name,
                    "alim_ssgrp_nom_eng": subgroup_name,
                }
                for group, group_name, subgroup, subgroup_name in GROUPS
            ],
        ),
        encoding="utf-8",
    )
    (directory / f"alim_{date}.xml").write_text(
        xml(
            "ALIM",
            [
                {
                    "alim_code": code,
                    "alim_nom_fr": name_fr,
                    "alim_nom_eng": name_en,
                    "alim_grp_code": group,
                    "alim_ssgrp_code": subgroup,
                }
                for code, name_fr, name_en, group, subgroup in foods
            ],
        ),
        encoding="utf-8",
    )
    (directory / f"compo_{date}.xml").write_text(xml("COMPO", values), encoding="utf-8")
    return directory


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    return release(tmp_path / "ciqual")


def amount_of(food: str, nutrient: str) -> SourceFoodNutrient:
    return SourceFoodNutrient.objects.get(
        food__code=food, nutrient__ciqual_code=nutrient
    )


# ----------------------------------------------------------------------------
# What a value means
# ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("teneur", "amount", "qualifier"),
    [
        ("-", None, EXACT),
        ("traces", None, TRACES),
        ("< 2,2", Decimal("2.2"), LESS_THAN),
        ("<0,5", Decimal("0.5"), LESS_THAN),
        ("1140", Decimal(1140), EXACT),
        ("0,5", Decimal("0.5"), EXACT),
        ("0,000123", Decimal("0.000123"), EXACT),
    ],
)
def test_a_value_keeps_the_meaning_the_source_gives_it(
    teneur: str, amount: Decimal | None, qualifier: SourceFoodNutrient.Qualifier
):
    parsed = parse_value(value("1", "327", teneur))

    assert (parsed.amount, parsed.qualifier) == (amount, qualifier)


def test_a_minimum_and_a_maximum_are_read_when_there_are():
    parsed = parse_value(value("1", "327", "10", "A", "9,5", "1E-6"))

    assert (parsed.minimum, parsed.maximum) == (Decimal("9.5"), Decimal("0.000001"))
    assert parse_value(value("1", "327", "10")).minimum is None


def test_a_number_that_is_not_one_is_refused():
    with pytest.raises(CiqualError, match="Not a number"):
        parse_value(value("1", "327", "abc"))


def test_a_grade_that_is_not_one_is_refused():
    with pytest.raises(CiqualError, match="grade"):
        parse_value(value("1", "327", "1", "Z"))


# ----------------------------------------------------------------------------
# The import
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_values_are_stored_as_the_source_publishes_them(directory: Path):
    import_ciqual(directory)

    vitamin_c = amount_of("20009", "55100")
    assert (vitamin_c.amount, vitamin_c.qualifier, vitamin_c.confidence) == (
        Decimal("9.3"),
        EXACT,
        "B",
    )
    assert (vitamin_c.minimum, vitamin_c.maximum) == (Decimal("7.1"), Decimal("11.9"))
    # Not measured is empty, never 0.
    vitamin_d = amount_of("20009", "52100")
    assert (vitamin_d.amount, vitamin_d.qualifier, vitamin_d.confidence) == (
        None,
        EXACT,
        "",
    )
    iodine = amount_of("20009", "10530")
    assert (iodine.amount, iodine.qualifier) == (None, TRACES)
    salt = amount_of("20009", "10004")
    assert (salt.amount, salt.qualifier) == (Decimal("0.02"), LESS_THAN)
    # Every digit the source gives is kept.
    assert amount_of("20009", "56600").amount == Decimal("0.000123")
    assert amount_of("20009", "55100").minimum is not None
    assert amount_of("20009", "10530").minimum is None


@pytest.mark.django_db
def test_the_foods_are_stored_with_their_names_and_groups(directory: Path):
    import_ciqual(directory)

    carrot = SourceFood.objects.get(code="20009")
    assert (carrot.name_fr, carrot.name_en) == ("Carotte, crue", "Carrot, raw")
    assert (carrot.food_group, carrot.food_subgroup) == (
        "fruits, légumes, légumineuses et oléagineux",
        "légumes",
    )
    assert carrot.source.code == "ciqual-2025"


@pytest.mark.django_db
def test_prepared_dishes_sauces_and_stocks_are_left_out(directory: Path):
    report = import_ciqual(directory)

    assert set(SourceFood.objects.values_list("code", flat=True)) == {
        "20009",
        "11058",  # Salt and yeast stay, though they are in the groups of sauces
        "11010",  # and stocks.
    }
    assert (report.foods, report.excluded) == (3, 3)
    # Their values are ignored without a word.
    assert SourceFoodNutrient.objects.count() == report.values == 7  # noqa: PLR2004


@pytest.mark.django_db
def test_energy_in_kcal_is_not_a_nutrient(directory: Path):
    import_ciqual(directory)

    assert not Nutrient.objects.filter(ciqual_code__in=SKIPPED).exists()
    assert not SourceFoodNutrient.objects.filter(
        nutrient__ciqual_code__in=SKIPPED
    ).exists()


@pytest.mark.django_db
def test_the_source_carries_the_attribution_the_licence_requires(directory: Path):
    import_ciqual(directory)

    source = Source.objects.get()
    assert (source.code, source.version) == ("ciqual-2025", "2025")
    assert "Etalab" in source.attribution
    assert "2025-11-03" in source.attribution
    assert "Anses" in source.attribution


@pytest.mark.django_db
def test_nutrients_are_added_from_the_file_and_the_label_ones_are_untouched(
    directory: Path,
):
    label_names = {n.code: n.name_fr for n in Nutrient.objects.filter(on_label=True)}

    report = import_ciqual(directory)

    vitamin_c = Nutrient.objects.get(code="vitamin_c")
    assert (vitamin_c.name_en, vitamin_c.name_fr) == ("Vitamin C", "Vitamine C")
    assert (vitamin_c.unit, vitamin_c.group, vitamin_c.ciqual_code) == (
        "mg",
        "vitamin",
        "55100",
    )
    assert (vitamin_c.on_label, vitamin_c.off_key) == (False, None)
    assert Nutrient.objects.get(code="vitamin_b12").unit == "µg"
    assert Nutrient.objects.get(code="fructose").parent_id == "sugars"
    assert Nutrient.objects.get(code="epa").parent_id == "polyunsaturated_fat"
    assert {
        n.code: n.name_fr for n in Nutrient.objects.filter(on_label=True)
    } == label_names
    # 74 constituents, less the two in kcal and the eight the label already has.
    assert report.nutrients_created == 64  # noqa: PLR2004
    # And vitamin K, which no source gives and the derivations create.
    assert Nutrient.objects.filter(ciqual_code__isnull=True).count() == 1


@pytest.mark.django_db
def test_importing_again_changes_nothing_and_updates_what_changed(
    directory: Path, tmp_path: Path
):
    import_ciqual(directory)
    counts = (
        Nutrient.objects.count(),
        SourceFood.objects.count(),
        SourceFoodNutrient.objects.count(),
    )

    again = import_ciqual(directory)

    assert (
        Nutrient.objects.count(),
        SourceFood.objects.count(),
        SourceFoodNutrient.objects.count(),
    ) == counts
    assert again.nutrients_created == 0
    changed = [
        {**row, "teneur": "10,5"} if row["const_code"] == "55100" else row
        for row in VALUES
    ]
    import_ciqual(release(tmp_path / "next", values=changed))
    assert amount_of("20009", "55100").amount == Decimal("10.5")
    assert Source.objects.count() == 1


@pytest.mark.django_db
def test_an_existing_nutrient_with_the_right_ciqual_code_is_used(directory: Path):
    iron = Nutrient.objects.create(
        code="my_iron",
        name_en="Iron",
        name_fr="Fer",
        unit="mg",
        group="mineral",
        ciqual_code="10260",
    )

    import_ciqual(directory)

    assert not Nutrient.objects.filter(code="iron").exists()
    assert Nutrient.objects.get(ciqual_code="10260") == iron


@pytest.mark.django_db
def test_a_nutrient_with_the_code_but_no_ciqual_code_is_adopted(directory: Path):
    Nutrient.objects.create(
        code="iron", name_en="Iron", name_fr="Fer", unit="mg", group="mineral"
    )

    import_ciqual(directory)

    assert Nutrient.objects.get(code="iron").ciqual_code == "10260"


# ----------------------------------------------------------------------------
# What it refuses, and leaves unwritten
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_unit_that_differs_from_the_catalogues_is_refused(directory: Path):
    Nutrient.objects.create(
        code="iron",
        name_en="Iron",
        name_fr="Fer",
        unit="g",
        group="mineral",
        ciqual_code="10260",
    )

    with pytest.raises(CiqualError, match=r"mg in CIQUAL.*g for the nutrient iron"):
        import_ciqual(directory)

    assert not Source.objects.exists()


@pytest.mark.django_db
def test_a_constituent_the_import_does_not_know_is_refused(tmp_path: Path):
    constituents = tmp_path / "const.xml"
    constituents.write_text(
        CONSTITUENTS_FILE.read_text(encoding="utf-8-sig").replace(
            "</TABLE>",
            "<CONST><const_code> 99999 </const_code>"
            "<const_nom_fr> Unobtainium (mg/100 g) </const_nom_fr>"
            "<const_nom_eng> Unobtainium (mg/100g) </const_nom_eng></CONST></TABLE>",
        ),
        encoding="utf-8",
    )

    with pytest.raises(CiqualError, match=r"99999.*Unobtainium"):
        import_ciqual(release(tmp_path / "ciqual", constituents=constituents))

    assert not Nutrient.objects.filter(ciqual_code="99999").exists()


@pytest.mark.django_db
def test_a_value_for_an_unknown_food_is_refused_and_nothing_is_written(
    tmp_path: Path,
):
    values = [*VALUES, value("99999", "55100", "1")]

    with pytest.raises(CiqualError, match="99999"):
        import_ciqual(release(tmp_path / "ciqual", values=values))

    assert not Source.objects.exists()
    assert not SourceFood.objects.exists()
    assert not Nutrient.objects.filter(code="vitamin_c").exists()


@pytest.mark.django_db
def test_a_missing_file_is_reported(directory: Path):
    next(directory.glob("compo_*.xml")).unlink()

    with pytest.raises(CiqualError, match=r"lacks.*compo"):
        import_ciqual(directory)


@pytest.mark.django_db
def test_two_releases_in_one_directory_are_refused(directory: Path):
    (directory / "compo_2020_07_07.xml").write_text("<TABLE/>", encoding="utf-8")

    with pytest.raises(CiqualError, match="More than one compo"):
        import_ciqual(directory)


@pytest.mark.django_db
def test_a_file_that_is_not_xml_is_reported(directory: Path):
    next(directory.glob("alim_2*.xml")).write_text("not xml", encoding="utf-8")

    with pytest.raises(CiqualError, match="Could not read"):
        import_ciqual(directory)


# ----------------------------------------------------------------------------
# The mapping of constituents
# ----------------------------------------------------------------------------
def test_every_constituent_of_the_file_is_imported_or_skipped_on_purpose():
    codes = [c.code for c in read_constituents(CONSTITUENTS_FILE)]

    assert len(codes) == 74  # noqa: PLR2004
    assert set(codes) <= CONSTITUENTS.keys() | SKIPPED.keys()
    assert set(CONSTITUENTS) | set(SKIPPED) == set(codes)


def test_the_nutrient_codes_are_unique_and_parents_come_first():
    seen: set[str] = set()
    label = {"fat", "saturated_fat", "carbohydrates", "sugars"}
    for mapped in CONSTITUENTS.values():
        assert mapped.code not in seen
        assert mapped.parent is None or mapped.parent in seen | label
        seen.add(mapped.code)


@pytest.mark.django_db
def test_the_label_nutrients_keep_the_codes_they_were_seeded_with():
    for nutrient in Nutrient.objects.filter(on_label=True):
        assert nutrient.ciqual_code is not None
        assert CONSTITUENTS[nutrient.ciqual_code].code == nutrient.code


def test_every_unit_of_the_file_is_one_the_catalogue_knows():
    units = {c.unit.lower() for c in read_constituents(CONSTITUENTS_FILE)} - {"kcal"}

    assert units <= set(ciqual_import.UNITS)


# ----------------------------------------------------------------------------
# The command
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_command_imports_a_directory_and_reports(directory: Path, capsys: Any):
    call_command("import_ciqual", path=directory)

    assert Source.objects.get().code == "ciqual-2025"
    out = capsys.readouterr().out
    assert "3 foods (3 left out)" in out
    assert "7 values" in out
    assert "64 nutrients added, 4 derived" in out


@pytest.mark.django_db
def test_the_command_turns_a_refused_import_into_a_command_error(tmp_path: Path):
    with pytest.raises(CommandError, match="lacks"):
        call_command("import_ciqual", path=tmp_path)


def fake_response(payload: Any = None, content: bytes = b"") -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.iter_content.return_value = [content]
    response.__enter__.return_value = response
    return response


@pytest.mark.django_db
def test_without_a_path_the_latest_release_is_downloaded(directory: Path):
    names = {path.name for path in directory.iterdir()}
    listed = [
        {"dataFile": {"id": index, "filename": name}}
        for index, name in enumerate(sorted(names), start=1)
    ] + [{"dataFile": {"id": 99, "filename": "Table Ciqual 2025_FR.xlsx"}}]
    contents = {
        index: (directory / name).read_bytes()
        for index, name in enumerate(sorted(names), start=1)
    }
    asked: list[str] = []

    def get(url: str, **kwargs: Any) -> MagicMock:
        asked.append(url)
        if url == ciqual_import.DATASET_API:
            assert kwargs["params"] == {"persistentId": ciqual_import.DATASET_DOI}
            return fake_response({"data": {"latestVersion": {"files": listed}}})
        return fake_response(content=contents[int(url.rsplit("/", 1)[1])])

    with patch.object(ciqual_import.requests, "get", side_effect=get):
        call_command("import_ciqual")

    assert Source.objects.get().code == "ciqual-2025"
    # The workbook is not one of the four files, and is not downloaded.
    assert not any(url.endswith("/99") for url in asked)


@pytest.mark.django_db
def test_a_failed_download_is_reported():
    with (
        patch.object(
            ciqual_import.requests, "get", side_effect=requests.ConnectionError("down")
        ),
        pytest.raises(CommandError, match="Could not download"),
    ):
        call_command("import_ciqual")
