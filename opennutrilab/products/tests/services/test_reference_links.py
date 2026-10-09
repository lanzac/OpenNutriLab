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
from opennutrilab.products.services.reference_links import links_as_data
from opennutrilab.products.services.reference_links import links_to_keep
from opennutrilab.products.services.reference_links import parse_links

LINKS_FILE = Path(__file__).parents[2] / "data" / "reference_links.json"


@pytest.fixture
def table(db: None) -> Source:
    source = Source.objects.create(code="ciqual-2025", name="Ciqual")
    SourceFood.objects.create(source=source, code="9340", name_fr="Quinoa, cru")
    SourceFood.objects.create(source=source, code="9341", name_fr="Quinoa, cuit")
    return source


def link(
    reference: int | str = "quinoa blanc", *codes: str, default: str | None = None
) -> ReferenceLink:
    return ReferenceLink(
        reference,
        tuple(FoodKey("ciqual-2025", code) for code in codes or ("9340",)),
        FoodKey("ciqual-2025", default) if default else None,
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


def test_a_default_is_read():
    links = parse_links(
        [
            {
                "reference": "quinoa",
                "foods": [{"source": "ciqual-2025", "code": "9340"}],
                "default": {"source": "ciqual-2025", "code": "9340"},
            }
        ]
    )

    assert links == [link("quinoa", default="9340")]


def test_a_reference_without_a_default_gets_the_one_of_the_link(table: Source):
    reference = ReferenceIngredient.objects.create(name_fr="quinoa blanc")

    result = link_reference_foods(link("quinoa blanc", "9340", "9341", default="9341"))

    reference.refresh_from_db()
    assert reference.default_food is not None
    assert reference.default_food.code == "9341"
    assert result.default_set == reference.default_food
    assert result.default_kept is None


def test_the_default_a_reference_has_is_kept(table: Source):
    reference = ReferenceIngredient.objects.create(
        name_fr="quinoa blanc", default_food=SourceFood.objects.get(code="9341")
    )

    result = link_reference_foods(link("quinoa blanc", "9340", "9341", default="9340"))

    reference.refresh_from_db()
    assert reference.default_food is not None
    assert reference.default_food.code == "9341"
    assert result.default_set is None
    assert result.default_kept == reference.default_food


def test_a_default_that_is_not_one_of_the_foods_is_refused(table: Source):
    reference = ReferenceIngredient.objects.create(name_fr="quinoa blanc")

    with pytest.raises(CustomFoodError, match="not one of its foods"):
        link_reference_foods(link("quinoa blanc", "9340", default="9341"))

    assert not reference.source_foods.exists()
    reference.refresh_from_db()
    assert reference.default_food is None


def test_the_links_to_keep_are_the_foods_of_a_table_with_the_defaults(table: Source):
    both = ReferenceIngredient.objects.create(name_fr="quinoa blanc")
    both.source_foods.add(*SourceFood.objects.filter(code__in=["9340", "9341"]))
    both.default_food = SourceFood.objects.get(code="9341")
    both.save()
    ReferenceIngredient.objects.create(name_fr="sans aliment")

    kept = links_to_keep()

    assert kept.links == [link("quinoa blanc", "9340", "9341", default="9341")]
    assert kept.unnamed == []
    assert links_as_data(kept.links) == [
        {
            "reference": "quinoa blanc",
            "foods": [
                {"source": "ciqual-2025", "code": "9340"},
                {"source": "ciqual-2025", "code": "9341"},
            ],
            "default": {"source": "ciqual-2025", "code": "9341"},
        }
    ]


def test_a_food_made_by_hand_is_left_out_as_its_spec_links_it(table: Source):
    manual = Source.objects.create(code="Manual", name="Manual")
    made = SourceFood.objects.create(source=manual, code="soy-flakes", name_fr="x")
    only_made = ReferenceIngredient.objects.create(name_fr="flocons de soja")
    only_made.source_foods.add(made)
    mixed = ReferenceIngredient.objects.create(name_fr="quinoa blanc")
    mixed.source_foods.add(made, SourceFood.objects.get(code="9340"))
    mixed.default_food = made
    mixed.save()

    kept = links_to_keep()

    assert [each.reference for each in kept.links] == ["quinoa blanc"]
    assert kept.links[0].foods == (FoodKey("ciqual-2025", "9340"),)
    assert kept.links[0].default == FoodKey("Manual", "soy-flakes")


def test_a_reference_that_no_name_finds_alone_is_not_kept(table: Source):
    # Each one's name in a language is the other's in the other language.
    food = SourceFood.objects.get(code="9340")
    twins = [
        ReferenceIngredient.objects.create(name_fr="pain", name_en="bread"),
        ReferenceIngredient.objects.create(name_fr="bread", name_en="pain"),
    ]
    for twin in twins:
        twin.source_foods.add(food)

    kept = links_to_keep()

    assert kept.links == []
    assert {r.pk for r in kept.unnamed} == {t.pk for t in twins}
