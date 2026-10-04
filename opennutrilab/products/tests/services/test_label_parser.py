from decimal import Decimal
from typing import Any

import pytest

from opennutrilab.products.services.label_parser import LabelItem
from opennutrilab.products.services.label_parser import Problem
from opennutrilab.products.services.label_parser import parse_label
from opennutrilab.products.services.label_parser import read_label

D = Decimal


def tree(items: list[LabelItem] | tuple[LabelItem, ...]) -> list[Any]:
    """Names, percentages as text, and parts: easy to write and to read."""
    return [
        (i.name, None if i.percentage is None else str(i.percentage), tree(i.parts))
        for i in items
    ]


def problems(text: str | None) -> list[Problem]:
    return [w.problem for w in read_label(text).warnings]


# ----------------------------------------------------------------------------
# Real labels, as OpenFoodFacts has them
# ----------------------------------------------------------------------------
MUESLI = (
    "Flocons de soja* 31%, Flocons de blé*, Flocons d'avoine*, Dattes* 7% "
    "(dattes*, farine de riz*), Raisins secs* (raisins*, huile de tournesol*), "
    "Fruits rouges* lyophilisés 1,4% (groseilles*, cassis*, framboises*), "
    "Graines de sarrasin*\nPeut contenir du lait, des fruits à coque et des "
    "graines de sésame. *Ingrédients biologiques."
)


def test_the_muesli_is_read_as_its_label_says_with_nothing_dropped():
    """OpenFoodFacts turned the first into "soja", lost "lyophilisés", lost the last."""
    assert tree(parse_label(MUESLI)) == [
        ("flocons de soja", "31", []),
        ("flocons de blé", None, []),
        ("flocons d'avoine", None, []),
        ("dattes", "7", [("dattes", None, []), ("farine de riz", None, [])]),
        (
            "raisins secs",
            None,
            [("raisins", None, []), ("huile de tournesol", None, [])],
        ),
        (
            "fruits rouges lyophilisés",
            "1.4",
            [("groseilles", None, []), ("cassis", None, []), ("framboises", None, [])],
        ),
        ("graines de sarrasin", None, []),
    ]
    assert read_label(MUESLI).warnings == []


def test_a_percentage_with_a_space_and_a_decimal_comma_is_read_whole():
    text = "Céréale 50 % (Farine de blé 34,8 %, farine de blé complet 15,2 %), sucre"

    assert tree(parse_label(text)) == [
        (
            "céréale",
            "50",
            [("farine de blé", "34.8", []), ("farine de blé complet", "15.2", [])],
        ),
        ("sucre", None, []),
    ]


def test_a_heading_with_a_colon_names_the_ingredient_the_rest_is_in():
    text = "Sucre, émulsifiants : lécithines [SOJA]; vanilline, sel"

    assert tree(parse_label(text)) == [
        ("sucre", None, []),
        ("émulsifiants", None, [("lécithines", None, [("soja", None, [])])]),
        ("vanilline", None, []),
        ("sel", None, []),
    ]


def test_a_percentage_after_the_parenthesis_belongs_to_the_ingredient():
    text = "sucre de canne (contient BLE) 8,5%, LACTOSE"

    assert tree(parse_label(text)) == [
        ("sucre de canne", "8.5", [("ble", None, [])]),
        ("lactose", None, []),
    ]


def test_allergens_and_the_organic_mark_do_not_change_a_name():
    text = "Farine de BLÉ bio 63%, **noisettes**, <b>lait</b> écrémé, _soja_"

    assert [i.name for i in parse_label(text)] == [
        "farine de blé",
        "noisettes",
        "lait écrémé",
        "soja",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Farine de blé, sel. Peut contenir des traces de lait.",
        "Farine de blé, sel\nPeut contenir du lait",
        "Farine de blé, sel, peut contenir des traces de lait",
        "Farine de blé, sel. Sans gluten.",
        "Ingrédients : farine de blé, sel",
    ],
)
def test_the_list_ends_where_the_labels_sentence_does(text: str):
    assert [i.name for i in parse_label(text)] == ["farine de blé", "sel"]


def test_a_note_in_parentheses_is_not_an_ingredient():
    text = "Sucre (origine UE), cacao (bio), farine (min. 12 %), sel"

    assert tree(parse_label(text)) == [
        ("sucre", None, []),
        ("cacao", None, []),
        ("farine", "12", []),
        ("sel", None, []),
    ]


def test_dont_introduces_what_is_in_an_ingredient():
    text = "Glucides (dont sucres 5 %), sel"

    assert tree(parse_label(text)) == [
        ("glucides", None, [("sucres", "5", [])]),
        ("sel", None, []),
    ]


def test_labels_in_other_languages_are_read_the_same_way():
    italian = "Polpa di pomodoro 70%, concentrato di pomodoro 13%, cipolla, sale"
    spanish = (
        "Agua carbonatada, colorante (E-150d), aromas naturales (contiene cafeína)."
    )

    assert tree(parse_label(italian))[:2] == [
        ("polpa di pomodoro", "70", []),
        ("concentrato di pomodoro", "13", []),
    ]
    assert tree(parse_label(spanish)) == [
        ("agua carbonatada", None, []),
        ("colorante", None, [("e-150d", None, [])]),
        ("aromas naturales", None, [("cafeína", None, [])]),
    ]


def test_a_percentage_that_cannot_be_kept_as_written_is_left_out():
    assert tree(parse_label("sel 0,125 %, sucre 150 %")) == [
        ("sel", None, []),
        ("sucre", None, []),
    ]


# ----------------------------------------------------------------------------
# A text that looks badly read is not read, and says why
# ----------------------------------------------------------------------------
def test_a_bracket_closed_by_a_parenthesis_stops_the_reading():
    """The Nutella jar's label, as OpenFoodFacts has it."""
    text = (
        "Sucre, huile de palme, NOISETTES 13%, cacao maigre 7,4%, émulsifiants: "
        "lécithines [SOJA), vanilline. Sans gluten."
    )

    reading = read_label(text)

    assert reading.items == []
    assert [w.problem for w in reading.warnings] == [Problem.UNBALANCED]
    assert "[SOJA)" in reading.warnings[0].message()
    assert reading.warnings[0].stops_reading


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Farine (blé, sucre, sel", Problem.UNBALANCED),
        ("Farine, sucre), sel", Problem.UNBALANCED),
        ("Farine de blé, sucre, S0JA, sel", Problem.GARBLED),
        ("Farine, fari1e de blé, sel", Problem.GARBLED),
        ("Farine, sucre �, sel", Problem.GARBLED),
        ("Farine | sucre, sel", Problem.GARBLED),
        ("Farine, énergie 1500 kJ 360 kcal, sel", Problem.OTHER_TEXT),
        ("Farine, sel, à consommer de préférence avant la fin", Problem.OTHER_TEXT),
        ("Farine,, sucre", Problem.EMPTY_ITEM),
        ("Farine, a, sel", Problem.SHORT_NAME),
        ("Peut contenir des traces de lait", Problem.NOTHING_READ),
    ],
)
def test_signs_of_a_text_read_badly_stop_the_reading(text: str, problem: Problem):
    reading = read_label(text)

    assert reading.items == []
    assert problem in [w.problem for w in reading.warnings]


def test_a_long_text_with_no_separator_is_not_read_as_one_ingredient():
    text = " ".join(["farine de blé sucre sel huile de palme levure"] * 5)

    reading = read_label(text)

    assert reading.items == []
    assert Problem.NOT_A_LIST in [w.problem for w in reading.warnings]
    assert Problem.LONG_NAME in [w.problem for w in reading.warnings]


@pytest.mark.parametrize(
    "text",
    [
        "Vitamines (E, PP, B6, B1, B9), oméga-3, colorant (E150d), coenzyme Q10",
        "Farine de blé 57%, émulsifiant : lécithines, poudres à lever (E500)",
        "Sirop de glucose-fructose, maltodextrine, eau, sel, arôme naturel",
    ],
)
def test_letters_with_digits_that_are_names_are_not_taken_for_a_misreading(text: str):
    assert read_label(text).warnings == []
    assert read_label(text).items


def test_percentages_over_one_hundred_are_said_but_the_text_is_still_read():
    reading = read_label("Farine 70%, sucre 40%, sel")

    assert [i.name for i in reading.items] == ["farine", "sucre", "sel"]
    assert [w.problem for w in reading.warnings] == [Problem.PERCENT_SUM]
    assert not reading.warnings[0].stops_reading
    assert "110" in reading.warnings[0].message()


@pytest.mark.parametrize("text", [None, "", "   \n"])
def test_a_missing_list_is_said_and_there_is_nothing_to_stop(text: str | None):
    reading = read_label(text)

    assert reading.items == []
    assert problems(text) == [Problem.MISSING]
    assert not reading.warnings[0].stops_reading
