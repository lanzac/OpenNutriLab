import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.custom_foods import parse_spec

CONSTITUENTS_FILE = Path(__file__).parent / "data" / "ciqual_const_2025.xml"

pytestmark = pytest.mark.django_db


@pytest.fixture
def soy(tmp_path: Path) -> Path:
    """A table with the soybean, and the spec of the flakes made from it."""
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    food = SourceFood.objects.create(
        source=Source.objects.create(code="ciqual-2025", name="Ciqual"),
        code="20901",
        name_fr="Soja, graine entière",
    )
    for code, amount in (("fat", "19.9"), ("proteins", "40"), ("energy", "1840")):
        SourceFoodNutrient.objects.create(
            food=food, nutrient=Nutrient.objects.get(code=code), amount=amount
        )
    ReferenceIngredient.objects.create(name_fr="flocons de soja")
    spec = tmp_path / "soy-flakes.json"
    spec.write_text(
        json.dumps(
            {
                "name_fr": "Flocons de soja",
                "name_en": "Soy flakes",
                "proxies": [{"source": "ciqual-2025", "code": "20901"}],
                "references": ["flocons de soja"],
            }
        )
    )
    return spec


def run(*args: str | Path) -> str:
    out = StringIO()
    call_command("create_custom_food", *map(str, args), stdout=out)
    return out.getvalue()


def test_the_food_is_made_linked_and_reported_with_its_ranges(soy: Path):
    output = run(soy)

    food = SourceFood.objects.get(source__code="Manual", code="soy-flakes")
    reference = ReferenceIngredient.objects.get(name_fr="flocons de soja")
    assert reference.source_foods.get() == food
    assert (
        "Flocons de soja (estimé d'après Soja, graine entière Ciqual 20901)" in output
    )
    assert "proteins      40 [34 - 46] g" in output
    assert "energy        1840 [1560 - 2120] kJ" in output
    assert "Linked to" in output
    assert "flocons de soja (to_review)" in output
    assert "1 food(s) of Manual made, 0 replaced, 1 link(s) to references." in output


def test_a_dry_run_says_what_would_be_made_and_keeps_nothing(soy: Path):
    output = run(soy, "--dry-run")

    assert "Dry run, nothing kept. 1 food(s) of Manual made" in output
    assert not SourceFood.objects.filter(source__code="Manual").exists()
    assert not Source.objects.filter(code="Manual").exists()


def test_a_second_run_needs_replace(soy: Path):
    run(soy)

    with pytest.raises(CommandError, match="already has a food 'soy-flakes'"):
        run(soy)

    assert "0 food(s) of Manual made, 1 replaced" in run(soy, "--replace")


def test_what_the_spec_gets_wrong_is_said_with_the_file_name(soy: Path, tmp_path: Path):
    wrong = tmp_path / "wrong.json"
    wrong.write_text('{"name_fr": "x", "proxy": []}')
    broken = tmp_path / "broken.json"
    broken.write_text("{")

    with pytest.raises(CommandError, match=r"wrong\.json: Unknown key"):
        run(wrong)
    with pytest.raises(CommandError, match=r"broken\.json"):
        run(broken)
    with pytest.raises(CommandError, match="Cannot read"):
        run(tmp_path / "missing.json")


def test_warnings_and_what_was_left_out_are_reported(soy: Path, tmp_path: Path):
    spec = tmp_path / "salt.json"
    spec.write_text(
        json.dumps({"name_en": "Salt", "nutrients": {"salt": 98}, "basis_en": "x"})
    )

    output = run(spec)

    assert "Warning: No fat, carbohydrates, proteins" in output
    assert "salt          98 [83.3 - 100] g" in output


def test_a_folder_makes_every_spec_in_it_and_goes_on_past_one_that_fails(
    soy: Path, tmp_path: Path
):
    folder = tmp_path / "specs"
    folder.mkdir()
    soy.rename(folder / "b-soy.json")
    (folder / "a-lost.json").write_text(
        json.dumps(
            {
                "name_en": "Lost",
                "nutrients": {"fat": 1},
                "basis_en": "x",
                "references": ["not there yet"],
            }
        )
    )

    with pytest.raises(CommandError, match=r"(?s)1 spec\(s\) not made.*a-lost\.json"):
        run(folder)

    assert SourceFood.objects.filter(source__code="Manual", code="soy-flakes").exists()
    assert not SourceFood.objects.filter(source__code="Manual", code="lost").exists()


def test_a_folder_without_a_spec_is_said(tmp_path: Path):
    with pytest.raises(CommandError, match=r"No spec \(\*\.json\)"):
        run(tmp_path)


def test_the_specs_kept_in_the_repository_are_valid():
    folder = Path(__file__).parents[1] / "data" / "custom_foods"
    specs = sorted(folder.glob("*.json"))

    assert specs
    for path in specs:
        spec = parse_spec(json.loads(path.read_text(encoding="utf-8")))
        assert path.stem == spec.code
