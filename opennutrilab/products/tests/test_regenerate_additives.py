import json
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Product
from opennutrilab.products.services import additive_sync
from opennutrilab.products.services.additive_sources import AdditiveSourceError
from opennutrilab.products.services.additive_sync import EU_SOURCE
from opennutrilab.products.services.additive_sync import read_dataset
from opennutrilab.products.services.additive_sync import write_dataset

DATA = Path(__file__).parent / "data"
COMMAND = "opennutrilab.products.management.commands.regenerate_additives"
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def dataset_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The dataset is a file of this test, never the repository's."""
    path = tmp_path / "additives.json"
    monkeypatch.setattr(additive_sync, "DATASET", path)
    return path


@pytest.fixture
def sources():
    """The two sources, as real extracts of what they answer."""
    items: list[dict[str, Any]] = json.loads(
        (DATA / "union_list_api.json").read_text(encoding="utf-8")
    )
    page = (DATA / "wikipedia_additifs.html").read_text(encoding="utf-8")
    with (
        patch(f"{COMMAND}.fetch_union_list", return_value=items) as union,
        patch(f"{COMMAND}.fetch_french_page", return_value=(page, 239644140)) as french,
    ):
        yield union, french


def run(*args: str) -> str:
    out = StringIO()
    call_command("regenerate_additives", *args, stdout=out)
    return out.getvalue()


def test_the_dataset_is_rebuilt_written_and_loaded_into_the_table(
    sources: Any, dataset_file: Path
):
    output = run()

    dataset, entries = read_dataset(dataset_file)
    assert len(entries) == Additive.objects.count() == 14  # noqa: PLR2004
    assert dataset["generated"]
    citric = Additive.objects.get(code="E330")
    assert (citric.name_en, citric.name_fr) == ("Citric acid", "Acide citrique")
    assert citric.status == Additive.Status.TO_REVIEW
    assert "14 additives in the dataset: 14 created" in output


def test_what_the_commissions_list_left_out_is_said(sources: Any):
    output = run()

    assert "Left out, Octyl gallate: removed from the Union list" in output
    assert "Left out, Hydrogen peroxide: no usable E number (none)" in output


def test_the_additives_with_no_french_name_are_said(sources: Any):
    output = run()

    assert "4 additive(s) without a French name: E1210, E322A, E960A, E960B" in output


def test_a_dry_run_says_what_would_change_and_keeps_nothing(
    sources: Any, dataset_file: Path
):
    output = run("--dry-run")

    assert "Dry run, nothing kept. 14 additives in the dataset: 14 created" in output
    assert not dataset_file.exists()
    assert not Additive.objects.exists()


def test_offline_it_reads_nothing_and_loads_the_dataset_as_it_is(
    sources: Any, dataset_file: Path
):
    run()
    Additive.objects.all().delete()
    union, french = sources
    union.reset_mock()
    french.reset_mock()
    before = dataset_file.read_text(encoding="utf-8")

    output = run("--offline")

    union.assert_not_called()
    french.assert_not_called()
    assert Additive.objects.count() == 14  # noqa: PLR2004
    assert dataset_file.read_text(encoding="utf-8") == before
    assert "14 created" in output


def test_what_changed_since_the_dataset_of_the_repository_is_said(
    sources: Any, dataset_file: Path
):
    write_dataset(
        {
            "additives": [
                {"code": "E330", "name_en": "Citric acid", "name_fr": "Acide citrique"},
                {"code": "E300", "name_en": "Ascorbic acid", "name_fr": "Vitamine C"},
                {"code": "E999", "name_en": "Gone", "name_fr": ""},
            ]
        }
    )

    output = run()

    assert (
        "New in the list: E101, E1210, E150A, E160A, E322, E322A, E334, E415, "
        "E440, E471, E960A, E960B"
    ) in output
    assert "No longer in the list: E999" in output
    # E300 changed its French name, E330 did not.
    assert "Names that changed: E300" in output


def test_an_untouched_additive_the_list_lacks_goes_and_a_touched_one_stays(
    sources: Any,
):
    gone = Additive.objects.create(
        name_en="Gone", code="E998", description=f"{EU_SOURCE} (POL-1)."
    )
    used = Additive.objects.create(
        name_en="Used", code="E999", description=f"{EU_SOURCE} (POL-2)."
    )
    label = Product.objects.create(barcode="3017620422003", name="Chocolate")
    Ingredient.objects.create(product=label, additive=used)

    output = run()

    assert not Additive.objects.filter(pk=gone.pk).exists()
    assert Additive.objects.filter(pk=used.pk).exists()
    assert "1 untouched ones rebuilt" in output


def test_what_an_earlier_list_made_is_loaded_again_with_the_names_of_the_dataset(
    sources: Any,
):
    Additive.objects.create(
        name_en="Citric acid",
        name_fr="Acide citrique (OFF)",
        code="E330",
        description="Imported from OpenFoodFacts' additives (en:e330).",
    )

    run()

    citric = Additive.objects.get(code="E330")
    assert citric.name_fr == "Acide citrique"
    assert citric.description.startswith(EU_SOURCE)


def test_running_it_again_gives_the_same_table(sources: Any):
    run()
    before = sorted(Additive.objects.values_list("code", "name_en", "name_fr"))

    output = run()

    assert sorted(Additive.objects.values_list("code", "name_en", "name_fr")) == before
    # What nothing touched is rebuilt, and what a person did is not.
    assert "14 untouched ones rebuilt" in output


@pytest.mark.parametrize("source", ["union", "french"])
def test_a_source_that_cannot_be_read_is_an_error_and_changes_nothing(
    sources: Any, dataset_file: Path, source: str
):
    union, french = sources
    {"union": union, "french": french}[source].side_effect = AdditiveSourceError(
        "Could not read it"
    )

    with pytest.raises(CommandError, match="Could not read it"):
        run()

    assert not dataset_file.exists()
    assert not Additive.objects.exists()
