import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests

from opennutrilab.products.services import additive_sources
from opennutrilab.products.services.additive_sources import MAX_PAGES
from opennutrilab.products.services.additive_sources import UNION_LIST_URL
from opennutrilab.products.services.additive_sources import AdditiveSourceError
from opennutrilab.products.services.additive_sources import UnionAdditive
from opennutrilab.products.services.additive_sources import additives_of_union_list
from opennutrilab.products.services.additive_sources import build_dataset
from opennutrilab.products.services.additive_sources import fetch_french_page
from opennutrilab.products.services.additive_sources import fetch_union_list
from opennutrilab.products.services.additive_sources import french_name
from opennutrilab.products.services.additive_sources import french_names_of_page

DATA = Path(__file__).parents[1] / "data"
GET = "opennutrilab.products.services.additive_sources.requests.get"


@pytest.fixture
def items() -> list[dict[str, Any]]:
    """Real items of the Commission's API: usable codes, and what is not."""
    return json.loads((DATA / "union_list_api.json").read_text(encoding="utf-8"))


@pytest.fixture
def page() -> str:
    """Real rows of the French Wikipedia tables of E numbers."""
    return (DATA / "wikipedia_additifs.html").read_text(encoding="utf-8")


def item(code: str | None, name: str, kind: str = "substanceFAD") -> dict[str, Any]:
    return {
        "policy_item_code": f"POL-{name}",
        "additive_e_code": code,
        "additive_name": name,
        "additive_type": kind,
    }


def response(body: object) -> MagicMock:
    answer = MagicMock()
    answer.json.return_value = body
    return answer


# ----------------------------------------------------------------------------
# The Commission's list
# ----------------------------------------------------------------------------
def test_the_substances_with_a_usable_code_are_read_in_the_order_of_their_numbers(
    items: list[dict[str, Any]],
):
    found, _left_out = additives_of_union_list(items)

    assert [a.code for a in found] == [
        "E101",
        "E150A",
        "E160A",
        "E300",
        "E322",
        "E322A",
        "E330",
        "E334",
        "E415",
        "E440",
        "E471",
        "E960A",
        "E960B",
        "E1210",
    ]


def test_what_is_left_out_is_said_and_a_group_is_not_an_additive(
    items: list[dict[str, Any]],
):
    _found, left_out = additives_of_union_list(items)

    assert sorted(left_out) == [
        "Anthrapen: no usable E number (..)",
        "Hydrogen peroxide: no usable E number (none)",
        "Monk fruit extract: no usable E number (E XXX)",
        "Octyl gallate: removed from the Union list",
    ]


def test_a_name_is_the_substance_without_the_markup_and_the_stray_quote(
    items: list[dict[str, Any]],
):
    found, _left_out = additives_of_union_list(items)

    names = {a.code: a.name_en for a in found}
    assert names["E330"] == "Citric acid"
    assert names["E960A"] == "Steviol glycosides from Stevia"
    assert names["E960B"] == "Steviol glycosides from fermentation"


def test_a_number_the_list_wrote_without_its_e_is_read_as_the_code_it_is(
    items: list[dict[str, Any]],
):
    found, _left_out = additives_of_union_list(items)

    assert {a.code: a.name_en for a in found}["E1210"] == "Carbomer"


def test_the_reference_of_an_entry_is_its_code_in_the_portal():
    found, _left_out = additives_of_union_list([item("E 330", "Citric acid")])

    assert found == [UnionAdditive("POL-Citric acid", "E330", "Citric acid")]


def test_a_code_the_list_has_twice_is_kept_once():
    found, _left_out = additives_of_union_list(
        [item("E 330", "Citric acid"), item("E330", "Another name")]
    )

    assert [(a.code, a.name_en) for a in found] == [("E330", "Citric acid")]


@pytest.mark.parametrize(
    "number", ["E XXX", "xxx", "..", "", None, "E 334 " + chr(0x2013) + " 337"]
)
def test_what_is_not_a_code_is_left_out_and_said(number: str | None):
    found, left_out = additives_of_union_list([item(number, "Something")])

    assert found == []
    assert left_out == [f"Something: no usable E number ({number or 'none'})"]


def test_the_pages_of_the_api_are_followed_to_the_last():
    first = response(
        {"value": [item("E 330", "Citric acid")], "nextLink": "http://next"}
    )
    last = response({"value": [item("E 300", "Ascorbic acid")]})

    with patch(GET, side_effect=[first, last]) as get:
        found = fetch_union_list()

    assert [i["additive_name"] for i in found] == ["Citric acid", "Ascorbic acid"]
    assert get.call_args_list[0].args[0] == UNION_LIST_URL
    assert get.call_args_list[0].kwargs["params"] == {
        "format": "json",
        "api-version": "v2.0",
    }
    # The link of the next page has its parameters already.
    assert get.call_args_list[1].args[0] == "http://next"
    assert get.call_args_list[1].kwargs["params"] is None


@pytest.mark.parametrize(
    "failure", [requests.ConnectionError("down"), requests.Timeout("slow")]
)
def test_an_api_that_does_not_answer_is_an_error_that_says_so(failure: Exception):
    with (
        patch(GET, side_effect=failure),
        pytest.raises(AdditiveSourceError, match="Could not read the Union list"),
    ):
        fetch_union_list()


@pytest.mark.parametrize(
    "body", [["not", "an", "object"], {"nothing": 1}, {"value": 3}]
)
def test_an_answer_that_is_not_the_list_is_an_error(body: object):
    with (
        patch(GET, return_value=response(body)),
        pytest.raises(AdditiveSourceError, match="Not the Union list"),
    ):
        fetch_union_list()


def test_an_api_that_never_ends_is_not_followed_for_ever():
    endless = response({"value": [], "nextLink": "http://again"})

    with (
        patch(GET, return_value=endless) as get,
        pytest.raises(AdditiveSourceError, match="more than"),
    ):
        fetch_union_list()

    assert get.call_count == MAX_PAGES


# ----------------------------------------------------------------------------
# The French names
# ----------------------------------------------------------------------------
def test_the_french_name_of_each_code_of_the_tables_is_read(page: str):
    assert french_names_of_page(page) == {
        "E100": "Curcumines",
        "E100I": "Curcumine",
        "E101": "Riboflavines",
        "E101I": "Riboflavine",
        "E150A": "Caramel ordinaire",
        "E160A": "β-carotène",
        "E300": "Acide ascorbique",
        "E322": "Lécithines",
        "E330": "Acide citrique",
        "E334": "Acide tartrique",
        "E415": "Gomme xanthane",
        "E440": "Pectines",
        "E471": "Mono- et diglycérides d'acides gras alimentaires",
        "E476": "Esters polyglycériques d'acides gras d'huile de ricin",
    }


def test_a_row_that_is_not_an_e_number_gives_no_name(page: str):
    assert "Sans numéro" not in " ".join(french_names_of_page(page))
    assert (
        french_names_of_page("<table><tr><td>Autre</td><td>Chose</td></tr></table>")
        == {}
    )


def test_a_footnote_mark_is_no_part_of_a_name():
    table = (
        "<table><tr><td>E330</td>"
        '<td>Acide citrique<sup class="reference">[1]</sup></td></tr></table>'
    )

    assert french_names_of_page(table) == {"E330": "Acide citrique"}


def test_the_first_row_of_a_code_keeps_it():
    table = (
        "<table><tr><td>E330</td><td>Acide citrique</td></tr>"
        "<tr><td>E 330</td><td>Autre nom</td></tr></table>"
    )

    assert french_names_of_page(table) == {"E330": "Acide citrique"}


@pytest.mark.parametrize(
    ("cell", "name"),
    [
        ("Acide ascorbique, vitamine C", "Acide ascorbique"),
        ("Gomme xanthane ou gomme de maïs", "Gomme xanthane"),
        ("Acide tartrique [L (+) - ]", "Acide tartrique"),
        ("Riboflavine (vitamine B2)", "Riboflavine"),
        ("Buthylhydroxyanisol (BHA)", "Buthylhydroxyanisol"),
        # A comma inside a name is no separator: only a comma and a space is.
        ("Propane-1,2-diol", "Propane-1,2-diol"),
        ("Curcumines", "Curcumines"),
        ("  Lécithines. ", "Lécithines"),
    ],
)
def test_the_name_is_the_first_of_a_cell_that_lists_several(cell: str, name: str):
    assert french_name(cell) == name


# ----------------------------------------------------------------------------
# The dataset
# ----------------------------------------------------------------------------
def test_the_dataset_has_each_substance_with_its_french_name_when_there_is_one():
    union = [
        UnionAdditive("POL-1", "E330", "Citric acid"),
        UnionAdditive("POL-2", "E960A", "Steviol glycosides"),
    ]

    dataset = build_dataset(
        union,
        {"E330": "Acide citrique", "E999": "Not in the list"},
        generated="2026-10-06",
        wikipedia_revision=42,
    )

    assert dataset["additives"] == [
        {
            "code": "E330",
            "name_en": "Citric acid",
            "name_fr": "Acide citrique",
            "ref": "POL-1",
        },
        {
            "code": "E960A",
            "name_en": "Steviol glycosides",
            "name_fr": "",
            "ref": "POL-2",
        },
    ]
    assert dataset["generated"] == "2026-10-06"
    assert dataset["sources"]["union_list"] == UNION_LIST_URL
    assert "revision 42" in dataset["sources"]["french_names"]
    assert "CC BY-SA 4.0" in dataset["sources"]["french_names"]


def test_the_french_page_is_read_with_the_revision_it_is():
    body = {"parse": {"text": "<p>page</p>", "revid": 7}}

    with patch(GET, return_value=response(body)) as get:
        assert fetch_french_page() == ("<p>page</p>", 7)

    assert get.call_args.kwargs["params"]["page"] == additive_sources.WIKIPEDIA_PAGE


@pytest.mark.parametrize("body", [{"error": "missing"}, {"parse": {"text": "x"}}, []])
def test_a_page_that_is_not_one_is_an_error(body: object):
    with (
        patch(GET, return_value=response(body)),
        pytest.raises(AdditiveSourceError, match="Could not read the page"),
    ):
        fetch_french_page()


def test_a_wikipedia_that_does_not_answer_is_an_error_that_says_so():
    with (
        patch(GET, side_effect=requests.ConnectionError("down")),
        pytest.raises(AdditiveSourceError, match="Could not read the page"),
    ):
        fetch_french_page()
