import json
from pathlib import Path

import pytest

from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.custom_foods import CustomFoodError
from opennutrilab.products.services.reference_links import FoodKey
from opennutrilab.products.services.reference_links import ReferenceLink
from opennutrilab.products.services.reference_links import link_reference_foods
from opennutrilab.products.services.reference_links import parse_links

LINKS_FILE = Path(__file__).parents[2] / "data" / "reference_links.json"


@pytest.fixture
def table(db: None) -> Source:
    source = Source.objects.create(code="ciqual-2025", name="Ciqual")
    SourceFood.objects.create(source=source, code="9340", name_fr="Quinoa, cru")
    SourceFood.objects.create(source=source, code="9341", name_fr="Quinoa, cuit")
    return source


def link(reference: int | str = "quinoa blanc", *codes: str) -> ReferenceLink:
    return ReferenceLink(
        reference, tuple(FoodKey("ciqual-2025", code) for code in codes or ("9340",))
    )


def test_a_link_adds_the_food_and_a_second_one_adds_nothing(table: Source):
    reference = ReferenceIngredient.objects.create(name_fr="quinoa blanc")

    first = link_reference_foods(link())
    second = link_reference_foods(link())

    assert [f.code for f in first.added] == ["9340"]
    assert first.already == ()
    assert second.added == ()
    assert [f.code for f in second.already] == ["9340"]
    assert [f.code for f in reference.source_foods.all()] == ["9340"]


def test_a_reference_keeps_the_foods_it_has(table: Source):
    reference = ReferenceIngredient.objects.create(name_fr="quinoa blanc")
    reference.source_foods.add(SourceFood.objects.get(code="9341"))

    result = link_reference_foods(link())

    assert [f.code for f in result.added] == ["9340"]
    assert {f.code for f in reference.source_foods.all()} == {"9340", "9341"}


def test_the_reference_is_found_by_an_id_or_a_name_whatever_its_case(table: Source):
    reference = ReferenceIngredient.objects.create(name_fr="Sel fumé")

    assert link_reference_foods(link("sel FUMÉ")).reference == reference
    assert link_reference_foods(link(reference.pk)).reference == reference


def test_a_food_or_a_reference_not_found_links_nothing(table: Source):
    reference = ReferenceIngredient.objects.create(name_fr="quinoa blanc")

    with pytest.raises(CustomFoodError, match="No food '1' in the source"):
        link_reference_foods(link("quinoa blanc", "9340", "1"))
    with pytest.raises(CustomFoodError, match="No reference ingredient is"):
        link_reference_foods(link("nothing"))

    assert not reference.source_foods.exists()


def test_the_links_of_a_file_are_read():
    links = parse_links(
        [{"reference": "quinoa", "foods": [{"source": "ciqual-2025", "code": "9340"}]}]
    )

    assert links == [link("quinoa")]


WRONG: list[tuple[object, str]] = [
    ({}, "a list of"),
    (["quinoa"], "A link is"),
    ([{"reference": "q", "foods": [], "x": 1}], "Unknown key"),
    ([{"reference": "q"}], 'needs its "foods"'),
    ([{"reference": "q", "foods": []}], 'needs its "foods"'),
    ([{"reference": None, "foods": ["9340"]}], "A reference is an id or a name"),
    ([{"reference": "q", "foods": ["9340"]}], "A food is"),
    ([{"reference": "q", "foods": [{"source": "c"}]}], 'needs its "source"'),
    ([{"reference": "q", "foods": [{"source": "c", "code": 1}]}], "needs its"),
    (
        [{"reference": "q", "foods": [{"source": "c", "code": "1", "w": 1}]}],
        "Unknown key",
    ),
]


@pytest.mark.parametrize(("data", "message"), WRONG)
def test_what_a_file_gets_wrong_is_said(data: object, message: str):
    with pytest.raises(CustomFoodError, match=message):
        parse_links(data)


def test_the_file_that_is_kept_in_the_repo_is_valid():
    links = parse_links(json.loads(LINKS_FILE.read_text(encoding="utf-8")))

    assert links
    assert all(isinstance(each.reference, str) for each in links)
