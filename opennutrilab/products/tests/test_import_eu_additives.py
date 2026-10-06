import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError

from opennutrilab.products.management.commands.import_eu_additives import UNION_LIST_URL
from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.additive_import import EU_SOURCE
from opennutrilab.products.services.additive_import import OFF_SOURCE
from opennutrilab.products.services.additive_import import ImportedAdditive
from opennutrilab.products.services.additive_import import additives_of_union_list
from opennutrilab.products.services.additive_import import import_additives
from opennutrilab.products.services.additive_import import prune_additives

# A real extract of the portal's list: ten substances with a code, four that have
# none that can be used (removed, no number yet, a placeholder), and a group.
EXTRACT = Path(__file__).parent / "data" / "eu_food_additives.json"
pytestmark = pytest.mark.django_db


@pytest.fixture
def union_list() -> list[Any]:
    return json.loads(EXTRACT.read_text(encoding="utf-8"))


def named(code: str) -> Additive:
    return Additive.objects.get(code=code)


# ----------------------------------------------------------------------------
# Reading the list
# ----------------------------------------------------------------------------
def test_the_substances_with_a_code_are_read_in_the_order_of_their_numbers(
    union_list: list[Any],
):
    found, _left_out = additives_of_union_list(union_list)

    assert [a.code for a in found] == [
        "E101",
        "E110",
        "E120",
        "E150A",
        "E300",
        "E322",
        "E330",
        "E415",
        "E423",
        "E440",
    ]


def test_what_is_left_out_is_said_and_a_group_is_not_an_additive(
    union_list: list[Any],
):
    _found, left_out = additives_of_union_list(union_list)

    assert sorted(left_out) == [
        "Anthrapen: no usable E number (..)",
        "Hydrogen peroxide: no usable E number (none)",
        "Monk fruit extract: no usable E number (E XXX)",
        "Octyl gallate: removed from the Union list",
    ]


def test_the_names_are_those_of_the_list_without_the_markup_it_was_typed_in(
    union_list: list[Any],
):
    found, _left_out = additives_of_union_list(union_list)

    names = {a.code: a.name_en for a in found}
    assert names["E330"] == "Citric acid"
    assert names["E120"] == "Carminic acid, Carmine"
    assert names["E110"] == "Sunset Yellow FCF/Orange Yellow S"
    # The list has English names only.
    assert not any(a.name_fr for a in found)


def test_the_reference_of_an_entry_is_its_code_in_the_portal(union_list: list[Any]):
    found, _left_out = additives_of_union_list(union_list)

    assert {a.code: a.source_ref for a in found}["E330"].startswith("POL-FAD-")


def policy_item(number: str, name: str) -> dict[str, Any]:
    """A substance as the portal nests it, with only what is read."""
    return {
        "valueIdentifier": "policyItemObject",
        "value": None,
        "childrenValues": [
            {"valueIdentifier": "policyItemCode", "value": f"POL-{name}"},
            {
                "valueIdentifier": "policyItemSpecs",
                "value": None,
                "childrenValues": [
                    {"valueIdentifier": "policyItemType", "value": "substanceFAD"},
                    {"valueIdentifier": "displayName", "value": name},
                    {
                        "valueIdentifier": "substanceFAD",
                        "value": None,
                        "childrenValues": [
                            {"valueIdentifier": "eNumber", "value": number}
                        ],
                    },
                ],
            },
        ],
    }


def test_a_code_written_twice_is_kept_once():
    item = policy_item("E 330", "Citric acid")

    found, _left_out = additives_of_union_list([item, item])

    assert [a.code for a in found] == ["E330"]


def test_a_number_the_list_wrote_without_its_e_is_read_as_the_code_it_is():
    found, left_out = additives_of_union_list([policy_item("1210", "Carbomer")])

    assert [(a.code, a.name_en) for a in found] == [("E1210", "Carbomer")]
    assert left_out == []


@pytest.mark.parametrize(
    "number", ["E XXX", "xxx", "..", "", "E 334 \u2013 337 and E 354:"]
)
def test_what_is_not_a_code_is_left_out_and_said(number: str):
    found, left_out = additives_of_union_list([policy_item(number, "Something")])

    assert found == []
    assert left_out == [f"Something: no usable E number ({number.strip() or 'none'})"]


# ----------------------------------------------------------------------------
# Filling the table
# ----------------------------------------------------------------------------
def test_the_additives_are_created_to_review_with_their_code_and_english_name(
    union_list: list[Any],
):
    imported, _left_out = additives_of_union_list(union_list)

    report = import_additives(imported, source=EU_SOURCE)

    citric = named("E330")
    assert (citric.name_en, citric.name_fr) == ("Citric acid", "")
    assert (citric.status, citric.function) == (Additive.Status.TO_REVIEW, "")
    assert citric.description.startswith(EU_SOURCE)
    assert report.created == Additive.objects.count() == 10  # noqa: PLR2004


def test_importing_again_changes_nothing(union_list: list[Any]):
    imported, _left_out = additives_of_union_list(union_list)
    import_additives(imported, source=EU_SOURCE)

    report = import_additives(imported, source=EU_SOURCE)

    assert (report.created, report.completed, report.unchanged) == (0, 0, 10)


def test_an_additive_with_the_code_is_never_overwritten(union_list: list[Any]):
    mine = Additive.objects.create(
        name_en="Acid of lemons",
        code="e330",
        function=Additive.Function.ACID,
        status=Additive.Status.CURATED,
    )
    imported, _left_out = additives_of_union_list(union_list)

    import_additives(imported, source=EU_SOURCE)

    mine.refresh_from_db()
    assert (mine.name_en, mine.function, mine.status) == (
        "Acid of lemons",
        "acid",
        "curated",
    )
    assert Additive.objects.filter(code__iexact="E330").count() == 1


def test_an_additive_with_the_code_and_no_english_name_is_given_it(
    union_list: list[Any],
):
    mine = Additive.objects.create(name_fr="Acide des citrons", code="e330")
    imported, _left_out = additives_of_union_list(union_list)

    import_additives(imported, source=EU_SOURCE)

    mine.refresh_from_db()
    assert (mine.name_en, mine.name_fr) == ("Citric acid", "Acide des citrons")


def test_an_additive_with_the_name_and_no_code_is_given_the_code_not_made_twice(
    union_list: list[Any],
):
    mine = Additive.objects.create(name_en="Citric acid")
    imported, _left_out = additives_of_union_list(union_list)

    import_additives(imported, source=EU_SOURCE)

    mine.refresh_from_db()
    assert mine.code == "E330"
    assert Additive.objects.filter(name_en__iexact="citric acid").count() == 1


def test_a_name_a_reference_has_is_kept_on_the_additive(union_list: list[Any]):
    ReferenceIngredient.objects.create(name_en="citric acid")
    imported, _left_out = additives_of_union_list(union_list)

    import_additives(imported, source=EU_SOURCE)

    assert named("E330").name_en == "Citric acid"


def test_a_name_two_entries_share_goes_to_the_first_and_the_other_has_its_code():
    first = ImportedAdditive("a", "E101", "Riboflavin", "")
    second = ImportedAdditive("b", "E101I", "Riboflavin", "")

    report = import_additives([first, second], source=EU_SOURCE)

    assert named("E101").name_en == "Riboflavin"
    assert named("E101I").name_en == "E101I"
    assert report.shared_names == 1


# ----------------------------------------------------------------------------
# Deleting what an earlier list left that this one does not have
# ----------------------------------------------------------------------------
def off_additive(code: str, **fields: Any) -> Additive:
    return Additive.objects.create(
        name_en=f"Off {code}",
        code=code,
        description=f"{OFF_SOURCE} (en:{code.lower()}).",
        **fields,
    )


def test_an_untouched_additive_of_the_other_list_that_this_one_lacks_is_deleted():
    off_additive("E103")
    kept = off_additive("E330")

    deleted = prune_additives({"E330"})

    assert deleted == 1
    assert list(Additive.objects.all()) == [kept]


@pytest.mark.parametrize(
    "touched",
    ["curated", "used", "nutrient", "food", "other source"],
)
def test_whatever_a_person_or_a_product_has_touched_is_kept(touched: str):
    additive = off_additive("E103")
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
    else:
        Additive.objects.filter(pk=additive.pk).update(description="Made by hand.")

    assert prune_additives(set()) == 0
    assert Additive.objects.filter(pk=additive.pk).exists()


# ----------------------------------------------------------------------------
# The command
# ----------------------------------------------------------------------------
def test_the_command_reads_a_file_and_says_what_it_did_and_what_it_left_out(
    capsys: pytest.CaptureFixture[str],
):
    call_command("import_eu_additives", path=EXTRACT)

    out = capsys.readouterr().out
    assert "10 additive(s) created, 0 completed, 0 already complete" in out
    assert "4 substance(s) left out" in out
    assert "Left out, Octyl gallate: removed from the Union list" in out
    assert "French names are not in this list" in out
    assert Additive.objects.count() == 10  # noqa: PLR2004


def test_a_dry_run_says_what_would_change_and_keeps_nothing(
    capsys: pytest.CaptureFixture[str],
):
    off_additive("E103")

    call_command("import_eu_additives", path=EXTRACT, dry_run=True, prune=True)

    out = capsys.readouterr().out
    assert "Dry run, nothing kept: 10 additive(s) created" in out
    assert "1 untouched additive(s) of the other list deleted" in out
    assert list(Additive.objects.values_list("code", flat=True)) == ["E103"]


def test_the_command_prunes_only_when_asked(capsys: pytest.CaptureFixture[str]):
    off_additive("E103")

    call_command("import_eu_additives", path=EXTRACT)
    assert Additive.objects.filter(code="E103").exists()

    call_command("import_eu_additives", path=EXTRACT, prune=True)
    assert not Additive.objects.filter(code="E103").exists()
    assert Additive.objects.count() == 10  # noqa: PLR2004


def test_the_command_says_which_references_are_known_as_additives(
    capsys: pytest.CaptureFixture[str],
):
    ReferenceIngredient.objects.create(name_en="citric acid")
    ReferenceIngredient.objects.create(name_en="milk")

    call_command("import_eu_additives", path=EXTRACT)

    assert "1 reference(s) have the name of an additive" in capsys.readouterr().out


def test_the_list_is_downloaded_when_no_file_is_given(union_list: list[Any]):
    response = MagicMock()
    response.json.return_value = union_list

    with patch(
        "opennutrilab.products.management.commands.import_eu_additives.requests.get",
        return_value=response,
    ) as get:
        call_command("import_eu_additives")

    assert get.call_args.args[0] == UNION_LIST_URL
    assert Additive.objects.count() == 10  # noqa: PLR2004


@pytest.mark.parametrize(
    "error", [requests.ConnectionError("down"), requests.Timeout("slow")]
)
def test_a_download_that_fails_is_an_error_that_says_so(error: Exception):
    with (
        patch(
            "opennutrilab.products.management.commands.import_eu_additives.requests.get",
            side_effect=error,
        ),
        pytest.raises(CommandError, match="Could not read the Union list"),
    ):
        call_command("import_eu_additives")


def test_a_file_that_is_not_the_list_is_an_error(tmp_path: Path):
    bad = tmp_path / "list.json"
    bad.write_text('{"not": "a list"}')

    with pytest.raises(CommandError, match="Not the Union list"):
        call_command("import_eu_additives", path=bad)


def test_a_file_that_is_missing_is_an_error(tmp_path: Path):
    with pytest.raises(CommandError, match="Could not read the Union list"):
        call_command("import_eu_additives", path=tmp_path / "nothing.json")
