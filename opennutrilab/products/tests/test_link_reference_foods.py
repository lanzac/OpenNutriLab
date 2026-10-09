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
