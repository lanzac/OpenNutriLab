import importlib
from pathlib import Path
from typing import Any

import pytest
from django.apps import apps

from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services import additive_sync
from opennutrilab.products.services.additive_sources import MAX_NAME
from opennutrilab.products.services.additive_sync import DATASET
from opennutrilab.products.services.additive_sync import EU_SOURCE
from opennutrilab.products.services.additive_sync import DatasetEntry
from opennutrilab.products.services.additive_sync import clear_untouched
from opennutrilab.products.services.additive_sync import read_dataset
from opennutrilab.products.services.additive_sync import sync_additives
from opennutrilab.products.services.additive_sync import write_dataset
from opennutrilab.products.services.label_parser import e_number

pytestmark = pytest.mark.django_db

CITRIC = DatasetEntry("E330", "Citric acid", "Acide citrique", "POL-FAD-IMPORT-3099")
ASCORBIC = DatasetEntry("E300", "Ascorbic acid", "Acide ascorbique", "POL-FAD-IMPORT-1")


def named(code: str) -> Additive:
    return Additive.objects.get(code=code)


# ----------------------------------------------------------------------------
# The dataset file
# ----------------------------------------------------------------------------
def test_the_dataset_of_the_repository_is_a_list_of_additives_with_usable_codes():
    dataset, entries = read_dataset()

    codes = [e.code for e in entries]
    assert len(entries) > 300  # noqa: PLR2004
    assert len(codes) == len(set(codes)), "a code is written once"
    assert all(e_number(code) == code for code in codes)
    assert all(e.name_en for e in entries)
    assert all(max(len(e.name_en), len(e.name_fr)) <= MAX_NAME for e in entries)
    assert all(e.ref for e in entries)
    assert dataset["generated"]
    assert "CC BY-SA" in dataset["sources"]["french_names"]


def test_the_dataset_has_the_additives_a_label_names_most():
    _dataset, entries = read_dataset()

    by_code = {e.code: e for e in entries}
    assert (by_code["E330"].name_en, by_code["E330"].name_fr) == (
        "Citric acid",
        "Acide citrique",
    )
    assert by_code["E300"].name_fr == "Acide ascorbique"
    assert by_code["E322"].name_fr == "Lécithines"
    assert by_code["E415"].name_fr == "Gomme xanthane"


def test_the_dataset_is_written_and_read_back_the_same(tmp_path: Path):
    dataset: dict[str, Any] = {
        "generated": "2026-10-06",
        "sources": {},
        "additives": [
            {
                "code": "E330",
                "name_en": "Citric acid",
                "name_fr": "Acide citrique",
                "ref": "A",
            }
        ],
    }

    write_dataset(dataset, tmp_path / "additives.json")
    read, entries = read_dataset(tmp_path / "additives.json")

    assert read == dataset
    assert entries == [DatasetEntry("E330", "Citric acid", "Acide citrique", "A")]


def test_the_dataset_is_read_from_the_repository_unless_a_path_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    other = tmp_path / "other.json"
    write_dataset({"additives": [{"code": "E999", "name_en": "X"}]}, other)

    monkeypatch.setattr(additive_sync, "DATASET", other)

    assert [e.code for e in read_dataset()[1]] == ["E999"]
    assert DATASET.name == "additives.json"


# ----------------------------------------------------------------------------
# Loading it
# ----------------------------------------------------------------------------
def test_the_whole_dataset_loads_to_review_with_no_class():
    _dataset, entries = read_dataset()

    report = sync_additives(entries)

    assert report.created == Additive.objects.count() == len(entries)
    citric = named("E330")
    assert (citric.status, citric.function) == (Additive.Status.TO_REVIEW, "")
    assert citric.description.startswith(EU_SOURCE)
    assert (citric.name_en, citric.name_fr) == ("Citric acid", "Acide citrique")


def test_loading_again_changes_nothing():
    _dataset, entries = read_dataset()
    sync_additives(entries)

    report = sync_additives(entries)

    assert (report.created, report.completed) == (0, 0)
    assert report.unchanged == len(entries)


def test_an_additive_with_the_code_is_completed_and_never_overwritten():
    mine = Additive.objects.create(
        name_en="Acid of lemons",
        code="e330",
        function=Additive.Function.ACID,
        status=Additive.Status.CURATED,
    )

    sync_additives([CITRIC])

    mine.refresh_from_db()
    assert (mine.name_en, mine.function, mine.status) == (
        "Acid of lemons",
        "acid",
        "curated",
    )
    # Its French name was missing, and is given.
    assert mine.name_fr == "Acide citrique"
    assert Additive.objects.filter(code__iexact="E330").count() == 1


def test_an_additive_with_the_name_and_no_code_is_given_the_code_not_made_twice():
    mine = Additive.objects.create(name_en="Citric acid")

    sync_additives([CITRIC])

    mine.refresh_from_db()
    assert (mine.code, mine.name_fr) == ("E330", "Acide citrique")
    assert Additive.objects.count() == 1


def test_a_name_a_reference_or_a_preparation_has_is_kept_on_the_additive():
    ReferenceIngredient.objects.create(name_fr="acide citrique")
    Preparation.objects.create(name_en="citric acid")

    sync_additives([CITRIC])

    assert (named("E330").name_en, named("E330").name_fr) == (
        "Citric acid",
        "Acide citrique",
    )


def test_a_name_two_entries_share_goes_to_the_first_and_the_other_has_its_code():
    first = DatasetEntry("E101", "Riboflavin", "Riboflavine", "a")
    second = DatasetEntry("E101I", "Riboflavin", "Riboflavine", "b")

    report = sync_additives([first, second])

    assert (named("E101").name_en, named("E101").name_fr) == (
        "Riboflavin",
        "Riboflavine",
    )
    assert (named("E101I").name_en, named("E101I").name_fr) == ("E101I", "")
    assert report.shared_names == 2  # noqa: PLR2004


def test_an_entry_with_no_name_in_either_language_is_named_by_its_code():
    sync_additives([DatasetEntry("E999", "", "", "x")])

    assert named("E999").name_en == "E999"


def test_an_entry_with_a_french_name_only_has_no_english_one_made_up():
    sync_additives([DatasetEntry("E999", "", "Un nom", "x")])

    assert (named("E999").name_en, named("E999").name_fr) == ("", "Un nom")


# ----------------------------------------------------------------------------
# What an earlier way of filling the table left
# ----------------------------------------------------------------------------
def legacy(code: str, **fields: Any) -> Additive:
    return Additive.objects.create(
        name_en=f"Off {code}",
        code=code,
        description=f"Imported from OpenFoodFacts' additives (en:{code.lower()}).",
        **fields,
    )


def test_every_untouched_additive_an_import_made_is_deleted_to_be_loaded_again():
    legacy("E103")
    legacy("E330")
    sync_additives([ASCORBIC])

    deleted = clear_untouched()

    assert deleted == 3  # noqa: PLR2004
    assert not Additive.objects.exists()


def test_what_an_import_made_comes_back_from_the_dataset_with_its_names():
    legacy("E330", name_fr="Acide citrique (OFF)")
    legacy("E103")

    clear_untouched()
    sync_additives([CITRIC])

    citric = named("E330")
    assert (citric.name_en, citric.name_fr) == ("Citric acid", "Acide citrique")
    assert citric.description == f"{EU_SOURCE} (POL-FAD-IMPORT-3099)."
    assert list(Additive.objects.values_list("code", flat=True)) == ["E330"]


def test_a_used_additive_of_openfoodfacts_keeps_what_it_has_and_says_where_from():
    used = legacy("E330", name_fr="Acide citrique (nom de la personne)")
    label = Product.objects.create(barcode="3017620422003", name="Chocolate")
    Ingredient.objects.create(product=label, additive=used)
    Additive.objects.filter(pk=used.pk).update(
        description=(
            "Imported from OpenFoodFacts' additives (en:e330).\nCreated from a label."
        )
    )

    clear_untouched()
    sync_additives([CITRIC])

    used.refresh_from_db()
    assert used.name_fr == "Acide citrique (nom de la personne)"
    assert used.description == (
        f"{EU_SOURCE} (POL-FAD-IMPORT-3099).\nCreated from a label."
    )


@pytest.mark.parametrize(
    "touched", ["curated", "used", "nutrient", "food", "made by hand", "no source"]
)
def test_whatever_a_person_or_a_product_has_touched_is_kept(touched: str):
    additive = legacy("E103")
    if touched == "curated":
        Additive.objects.filter(pk=additive.pk).update(status="curated")
    elif touched == "used":
        label = Product.objects.create(barcode="3017620422003", name="Chocolate")
        Ingredient.objects.create(product=label, additive=additive)
    elif touched == "nutrient":
        additive.nutrients.create(nutrient=Nutrient.objects.get(code="fat"), amount=1)
    elif touched == "food":
        additive.source_foods.add(
            SourceFood.objects.create(
                source=Source.objects.create(code="ciqual-2025", name="Ciqual"),
                code="1",
            )
        )
    elif touched == "made by hand":
        Additive.objects.filter(pk=additive.pk).update(description="Made by hand.")
    else:
        Additive.objects.filter(pk=additive.pk).update(description="")

    assert clear_untouched() == 0
    assert Additive.objects.filter(pk=additive.pk).exists()


# ----------------------------------------------------------------------------
# The migration
# ----------------------------------------------------------------------------
def test_the_migration_loads_the_dataset_and_clears_what_the_old_import_left():
    migration = importlib.import_module(
        "opennutrilab.products.migrations.0013_load_additives"
    )
    legacy("E103")
    legacy("E330", name_fr="Acide citrique (OFF)")
    _dataset, entries = read_dataset()

    migration.load_additives(apps, None)

    assert Additive.objects.count() == len(entries)
    assert not Additive.objects.filter(code="E103").exists()
    citric = named("E330")
    assert citric.name_fr == "Acide citrique"
    assert citric.description.startswith(EU_SOURCE)
    assert not Additive.objects.filter(
        description__startswith="Imported from OpenFoodFacts"
    ).exists()


def test_the_migration_keeps_an_additive_that_is_used():
    migration = importlib.import_module(
        "opennutrilab.products.migrations.0013_load_additives"
    )
    used = legacy("E103")
    label = Product.objects.create(barcode="3017620422003", name="Chocolate")
    Ingredient.objects.create(product=label, additive=used)

    migration.load_additives(apps, None)

    assert Additive.objects.filter(pk=used.pk).exists()
