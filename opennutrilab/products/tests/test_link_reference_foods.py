import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood

pytestmark = pytest.mark.django_db


@pytest.fixture
def links(tmp_path: Path) -> Path:
    """A table with the raw quinoa, a reference for it, and the file that links them."""
    source = Source.objects.create(code="ciqual-2025", name="Ciqual")
    SourceFood.objects.create(source=source, code="9340", name_fr="Quinoa, cru")
    ReferenceIngredient.objects.create(name_fr="quinoa blanc")
    file = tmp_path / "links.json"
    file.write_text(
        json.dumps(
            [
                {
                    "reference": "quinoa blanc",
                    "foods": [{"source": "ciqual-2025", "code": "9340"}],
                }
            ]
        )
    )
    return file


def run(*args: str | Path) -> str:
    out = StringIO()
    call_command("link_reference_foods", *map(str, args), stdout=out)
    return out.getvalue()


def test_the_reference_is_linked_and_it_is_said(links: Path):
    output = run(links)

    reference = ReferenceIngredient.objects.get(name_fr="quinoa blanc")
    assert [f.code for f in reference.source_foods.all()] == ["9340"]
    assert "9340 Quinoa, cru" in output
    assert "1 link(s) made, 0 already there." in output


def test_a_second_run_adds_nothing(links: Path):
    run(links)

    output = run(links)

    assert "Already linked" in output
    assert "0 link(s) made, 1 already there." in output


def test_a_dry_run_keeps_nothing(links: Path):
    output = run(links, "--dry-run")

    assert "Dry run, nothing kept. 1 link(s) made" in output
    assert not ReferenceIngredient.objects.get(
        name_fr="quinoa blanc"
    ).source_foods.exists()


def test_a_link_that_fails_does_not_stop_the_others(links: Path, tmp_path: Path):
    file = tmp_path / "two.json"
    file.write_text(
        json.dumps(
            [
                {
                    "reference": "unknown",
                    "foods": [{"source": "ciqual-2025", "code": "9340"}],
                },
                *json.loads(links.read_text()),
            ]
        )
    )

    with pytest.raises(
        CommandError, match="1 link\\(s\\) not made, 1 link\\(s\\) made"
    ):
        run(file)

    assert ReferenceIngredient.objects.get(name_fr="quinoa blanc").source_foods.exists()


def test_what_the_file_gets_wrong_is_said_with_its_name(tmp_path: Path):
    wrong = tmp_path / "wrong.json"
    wrong.write_text('{"quinoa": 1}')
    broken = tmp_path / "broken.json"
    broken.write_text("[")

    with pytest.raises(CommandError, match=r"wrong\.json: The links are a list"):
        run(wrong)
    with pytest.raises(CommandError, match=r"broken\.json"):
        run(broken)
    with pytest.raises(CommandError, match="Cannot read"):
        run(tmp_path / "missing.json")


def test_the_default_of_a_reference_is_given_and_said(links: Path, tmp_path: Path):
    entries = json.loads(links.read_text())
    entries[0]["default"] = {"source": "ciqual-2025", "code": "9340"}
    file = tmp_path / "default.json"
    file.write_text(json.dumps(entries))

    output = run(file)

    reference = ReferenceIngredient.objects.get(name_fr="quinoa blanc")
    assert reference.default_food is not None
    assert reference.default_food.code == "9340"
    assert "Default of" in output
    assert "9340 Quinoa, cru" in output


def test_what_is_exported_links_again_what_a_reset_lost(links: Path, tmp_path: Path):
    reference = ReferenceIngredient.objects.get(name_fr="quinoa blanc")
    food = SourceFood.objects.get(code="9340")
    reference.source_foods.add(food)
    reference.default_food = food
    reference.save()
    kept = tmp_path / "kept.json"

    out = StringIO()
    call_command("export_reference_links", str(kept), stdout=out)
    reference.source_foods.clear()
    reference.default_food = None
    reference.save()
    run(kept)

    assert "1 reference(s) with 1 food(s) and 1 default(s) written" in out.getvalue()
    reference.refresh_from_db()
    assert reference.source_foods.get() == food
    assert reference.default_food == food


def test_a_reference_that_no_name_finds_alone_is_said_on_export(
    links: Path, tmp_path: Path
):
    food = SourceFood.objects.get(code="9340")
    for fr, en in (("pain", "bread"), ("bread", "pain")):
        ReferenceIngredient.objects.create(name_fr=fr, name_en=en).source_foods.add(
            food
        )

    out = StringIO()
    call_command("export_reference_links", str(tmp_path / "kept.json"), stdout=out)

    assert "Not written, no name finds it alone" in out.getvalue()
