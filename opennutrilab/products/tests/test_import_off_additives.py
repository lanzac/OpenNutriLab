import json
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError

from opennutrilab.products.management.commands.import_off_additives import ADDITIVES_URL
from opennutrilab.products.models import Additive
from opennutrilab.products.services.additive_import import additives_of_taxonomy

# A real extract of OpenFoodFacts' taxonomy: eleven E numbers and four entries
# that are not.
OFF_EXTRACT = Path(__file__).parent / "data" / "off_additives_taxonomy.json"
EU_EXTRACT = Path(__file__).parent / "data" / "eu_food_additives.json"
pytestmark = pytest.mark.django_db


@pytest.fixture
def taxonomy() -> dict[str, object]:
    return json.loads(OFF_EXTRACT.read_text(encoding="utf-8"))


@pytest.fixture
def eu_additives() -> None:
    call_command("import_eu_additives", path=EU_EXTRACT)


# ----------------------------------------------------------------------------
# Reading the taxonomy
# ----------------------------------------------------------------------------
def test_the_entries_that_are_an_e_number_are_read_in_the_order_of_their_numbers(
    taxonomy: dict[str, object],
):
    found, skipped = additives_of_taxonomy(taxonomy)

    assert [a.code for a in found] == [
        "E101",
        "E101I",
        "E101II",
        "E150A",
        "E300",
        "E322",
        "E330",
        "E415",
        "E440",
        "E1001II",
        "E1200",
    ]
    assert skipped == 4  # noqa: PLR2004


def test_the_names_are_the_substance_without_the_code_that_heads_them(
    taxonomy: dict[str, object],
):
    found, _skipped = additives_of_taxonomy(taxonomy)

    by_code = {a.code: a for a in found}
    assert (by_code["E330"].name_en, by_code["E330"].name_fr) == (
        "Citric acid",
        "Acide citrique",
    )
    # Not cleaned of anything else: no guess at what was meant.
    assert by_code["E150A"].name_fr == "Caramel E150a"
    assert by_code["E1001II"].name_fr == ""


def test_a_name_that_is_only_the_code_is_no_name():
    found, _skipped = additives_of_taxonomy(
        {"en:e999": {"name": {"en": "E999", "fr": "E999 - E999"}}}
    )

    assert [(a.name_en, a.name_fr) for a in found] == [("", "")]


def test_a_long_suffix_is_read_as_part_of_the_code():
    found, _skipped = additives_of_taxonomy(
        {"en:e160aiii": {"name": {"en": "E160aiii - Beta-carotene"}}}
    )

    assert [a.code for a in found] == ["E160AIII"]


# ----------------------------------------------------------------------------
# Completing the names of the additives that are there
# ----------------------------------------------------------------------------
def test_the_french_names_are_given_to_the_additives_the_union_list_made(
    eu_additives: None,
):
    assert Additive.objects.get(code="E330").name_fr == ""

    call_command("import_off_additives", path=OFF_EXTRACT)

    citric = Additive.objects.get(code="E330")
    assert (citric.name_en, citric.name_fr) == ("Citric acid", "Acide citrique")
    assert Additive.objects.get(code="E415").name_fr == "Gomme xanthane"


def test_it_creates_nothing_the_union_list_does_not_have(eu_additives: None):
    before = Additive.objects.count()

    call_command("import_off_additives", path=OFF_EXTRACT)

    assert Additive.objects.count() == before
    # E101I and E1200 are in the taxonomy and not among the additives.
    assert not Additive.objects.filter(code__in=["E101I", "E1001II", "E1200"]).exists()


def test_a_name_an_additive_has_is_never_changed(eu_additives: None):
    Additive.objects.filter(code="E330").update(name_fr="Acide des citrons")

    call_command("import_off_additives", path=OFF_EXTRACT)

    assert Additive.objects.get(code="E330").name_fr == "Acide des citrons"


def test_the_command_says_what_it_did(
    eu_additives: None, capsys: pytest.CaptureFixture[str]
):
    capsys.readouterr()

    call_command("import_off_additives", path=OFF_EXTRACT)

    out = capsys.readouterr().out
    assert "additive(s) completed with names" in out


def test_with_no_additive_there_is_nothing_to_complete_and_it_says_where_to_start():
    with pytest.raises(CommandError, match="run import_eu_additives first"):
        call_command("import_off_additives", path=OFF_EXTRACT)


def test_the_taxonomy_is_downloaded_when_no_file_is_given(eu_additives: None):
    response = MagicMock()
    response.json.return_value = json.loads(OFF_EXTRACT.read_text(encoding="utf-8"))

    with patch(
        "opennutrilab.products.management.commands.import_off_additives.requests.get",
        return_value=response,
    ) as get:
        call_command("import_off_additives")

    assert get.call_args.args[0] == ADDITIVES_URL
    assert Additive.objects.get(code="E330").name_fr == "Acide citrique"


@pytest.mark.parametrize(
    "error", [requests.ConnectionError("down"), requests.Timeout("slow")]
)
def test_a_download_that_fails_is_an_error_that_says_so(
    eu_additives: None, error: Exception
):
    with (
        patch(
            "opennutrilab.products.management.commands.import_off_additives.requests.get",
            side_effect=error,
        ),
        pytest.raises(CommandError, match="Could not read the additives"),
    ):
        call_command("import_off_additives")


def test_a_file_that_is_not_a_taxonomy_is_an_error(eu_additives: None, tmp_path: Path):
    bad = tmp_path / "additives.json"
    bad.write_text("[1, 2]")

    with pytest.raises(CommandError, match="Not an OpenFoodFacts taxonomy"):
        call_command("import_off_additives", path=bad)


def test_a_file_that_is_missing_is_an_error(eu_additives: None, tmp_path: Path):
    with pytest.raises(CommandError, match="Could not read the additives"):
        call_command("import_off_additives", path=tmp_path / "nothing.json")
