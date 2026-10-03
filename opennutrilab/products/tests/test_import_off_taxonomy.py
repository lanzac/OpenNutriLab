import json
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError

from opennutrilab.products.management.commands.import_off_taxonomy import TAXONOMY_URL
from opennutrilab.products.models import IngredientTaxon

EXTRACT = Path(__file__).parent / "data" / "off_ingredients_taxonomy.json"
pytestmark = pytest.mark.django_db


def test_the_names_are_loaded_in_english_and_french():
    call_command("import_off_taxonomy", path=EXTRACT)

    oats = IngredientTaxon.objects.get(off_id="en:oat-flakes")
    assert (oats.name_en, oats.name_fr) == ("oat flakes", "flocons d'avoine")
    assert IngredientTaxon.objects.count() == 14  # noqa: PLR2004


def test_an_entry_without_an_english_name_is_loaded_with_it_blank():
    call_command("import_off_taxonomy", path=EXTRACT)

    onion = IngredientTaxon.objects.get(off_id="fr:oignon-et-ail-en-poudre")
    assert (onion.name_en, onion.name_fr) == ("", "oignon et ail en poudre")
    # Named in neither language: kept, as a row that gives no name.
    finnish = IngredientTaxon.objects.get(off_id="fi:rapsi-ja-auringonkukkaöljy")
    assert (finnish.name_en, finnish.name_fr) == ("", "")


def test_loading_again_updates_what_changed_and_adds_what_is_new(tmp_path, capsys):
    taxonomy = tmp_path / "ingredients.json"
    taxonomy.write_text(json.dumps({"en:oat": {"name": {"en": "oat"}}}))
    call_command("import_off_taxonomy", path=taxonomy)

    taxonomy.write_text(
        json.dumps(
            {
                "en:oat": {"name": {"en": "oats", "fr": "avoine"}},
                "en:rye": {"name": {"en": "rye"}},
            }
        )
    )
    call_command("import_off_taxonomy", path=taxonomy)

    assert dict(IngredientTaxon.objects.values_list("off_id", "name_en")) == {
        "en:oat": "oats",
        "en:rye": "rye",
    }
    assert IngredientTaxon.objects.get(off_id="en:oat").name_fr == "avoine"
    assert "2 taxonomy entries loaded (1 new)" in capsys.readouterr().out


def test_without_a_path_the_taxonomy_is_downloaded():
    response = MagicMock()
    response.json.return_value = {"en:oat": {"name": {"en": "oat"}}}

    with patch(
        "opennutrilab.products.management.commands.import_off_taxonomy.requests.get",
        return_value=response,
    ) as get:
        call_command("import_off_taxonomy")

    assert get.call_args.args == (TAXONOMY_URL,)
    # OFF answers 403 to a client that does not name itself.
    assert "OpenNutriLab" in get.call_args.kwargs["headers"]["User-Agent"]
    assert IngredientTaxon.objects.filter(off_id="en:oat", name_en="oat").exists()


def test_a_failed_download_is_an_error_and_loads_nothing():
    with (
        patch(
            "opennutrilab.products.management.commands.import_off_taxonomy.requests.get",
            side_effect=requests.ConnectionError("unreachable"),
        ),
        pytest.raises(CommandError, match="Could not read the taxonomy"),
    ):
        call_command("import_off_taxonomy")

    assert not IngredientTaxon.objects.exists()


def test_a_file_that_is_not_a_taxonomy_is_an_error(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(CommandError, match="Could not read the taxonomy"):
        call_command("import_off_taxonomy", path=missing)

    not_json = tmp_path / "not.json"
    not_json.write_text("<html>")
    with pytest.raises(CommandError, match="Could not read the taxonomy"):
        call_command("import_off_taxonomy", path=not_json)

    not_an_object = tmp_path / "list.json"
    not_an_object.write_text("[]")
    with pytest.raises(CommandError, match="Not an OpenFoodFacts taxonomy"):
        call_command("import_off_taxonomy", path=not_an_object)
