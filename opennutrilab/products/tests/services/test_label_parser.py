from decimal import Decimal
from itertools import pairwise
from typing import Any

import pytest
from django.utils import translation

from opennutrilab.products.models import Additive
from opennutrilab.products.services.label_parser import (
    _CLASS_WORDS,  # pyright: ignore[reportPrivateUsage]
)
from opennutrilab.products.services.label_parser import LabelItem
from opennutrilab.products.services.label_parser import Problem
from opennutrilab.products.services.label_parser import (
    _name,  # pyright: ignore[reportPrivateUsage]
)
from opennutrilab.products.services.label_parser import (
    _name_spans,  # pyright: ignore[reportPrivateUsage]
)
from opennutrilab.products.services.label_parser import e_number
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


# A ready meal, with a note ahead of its parts, brackets, a semicolon, and a
# sentence that ends the list. The comma that was before "2,3 %" is corrected,
# as it was on OpenFoodFacts: see the test after the next one.
GNOCCHI = (
    "Gnocchi à la pomme de terre précuit (origine : Italie) [semoule de blé "
    "(gluten), pomme de terre déshydratée 19,4 %, eau, sel], purée de tomate "
    "12,2%, oignon grillé 6,3 %, mozzarella 6 % [lait, sel, présure microbienne, "
    "acidifiant : acide citrique], tomate cerise 4.2 %; épinard 3,1 %, tomate "
    "cerise mi séchée 2,6 %, huile d'olive vierge extra 2,3 %, basilic, ail, "
    "préparation d'oignon (jus d'oignon concentré, huile de tournesol), sel, "
    "poivre.\npeut contenir des traces de : oeuf, arachide, moutarde."
)


def test_a_note_ahead_of_the_parts_does_not_hide_them_or_take_their_percentage():
    """The 19,4 % was put on the gnocchi and its parts were lost, in silence."""
    assert tree(parse_label(GNOCCHI)) == [
        (
            "gnocchi à la pomme de terre précuit",
            None,
            [
                ("semoule de blé", None, []),
                ("pomme de terre déshydratée", "19.4", []),
                ("eau", None, []),
                ("sel", None, []),
            ],
        ),
        ("purée de tomate", "12.2", []),
        ("oignon grillé", "6.3", []),
        (
            "mozzarella",
            "6",
            [
                ("lait", None, []),
                ("sel", None, []),
                ("présure microbienne", None, []),
                # The class that headed it is what it is for, not an ingredient.
                ("acide citrique", None, []),
            ],
        ),
        ("tomate cerise", "4.2", []),
        ("épinard", "3.1", []),
        ("tomate cerise mi séchée", "2.6", []),
        ("huile d'olive vierge extra", "2.3", []),
        ("basilic", None, []),
        ("ail", None, []),
        (
            "préparation d'oignon",
            None,
            [("jus d'oignon concentré", None, []), ("huile de tournesol", None, [])],
        ),
        ("sel", None, []),
        ("poivre", None, []),
    ]
    assert read_label(GNOCCHI).warnings == []


def test_a_comma_between_a_percentage_and_its_ingredient_stops_the_reading():
    """The same list as OpenFoodFacts had it: the 2,3 % was dropped without a word."""
    text = GNOCCHI.replace("extra 2,3 %", "extra, 2,3 %")

    reading = read_label(text)

    assert reading.items == []
    assert [w.problem for w in reading.warnings] == [Problem.NAMELESS_PERCENT]
    assert reading.warnings[0].stops_reading
    assert "2,3 %" in reading.warnings[0].message()


@pytest.mark.parametrize(
    "text",
    [
        "Gnocchi (origine : Italie) [semoule, eau 5 %], sel",
        "Gnocchi [semoule, eau 5 %] (origine : Italie), sel",
        "Gnocchi (bio) (origine UE) (semoule, eau 5 %), sel",
        "Gnocchi (origine : Italie) (semoule, eau 5 %), sel",
    ],
)
def test_a_note_is_ignored_wherever_it_stands_among_the_parentheses(text: str):
    assert tree(parse_label(text)) == [
        (
            "gnocchi",
            None,
            [("semoule", None, []), ("eau", "5", [])],
        ),
        ("sel", None, []),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Tomates 40 % (origine : Italie), sel",
        "Tomates (origine : Italie) 40 %, sel",
        "Tomates (bio) 40 % (origine UE), sel",
    ],
)
def test_a_note_next_to_a_percentage_leaves_the_percentage_where_it_was(text: str):
    assert tree(parse_label(text)) == [("tomates", "40", []), ("sel", None, [])]


# Salade à l'italienne (3270160642601): the origin of the pasta, with no "origine".
ITALIAN_SALAD = (
    "Pâte cuite 60,5% (Allemagne) [eau, semoule de blé dur (gluten)], "
    "mini-involtini 12% [fromage de vache (lait) 8,4%, speck 3,6% (viande de porc, "
    "sel)], tomate 11%, huile d'olive vierge extra."
)


def test_a_country_alone_in_parentheses_is_an_origin_not_a_part():
    """ "allemagne" was read as a part of the pasta, and the brackets after it lost."""
    reading = read_label(ITALIAN_SALAD)

    assert reading.warnings == []
    assert tree(reading.items) == [
        (
            "pâte cuite",
            "60.5",
            [("eau", None, []), ("semoule de blé dur", None, [])],
        ),
        (
            "mini-involtini",
            "12",
            [
                ("fromage de vache", "8.4", []),
                ("speck", "3.6", [("viande de porc", None, []), ("sel", None, [])]),
            ],
        ),
        ("tomate", "11", []),
        ("huile d'olive vierge extra", None, []),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Jambon (France), sel",
        "Jambon (FRANCE*), sel",
        "Jambon (Pays-Bas), sel",
        "Jambon (Pays Bas), sel",
        "Jambon (Royaume-Uni), sel",
        "Jambon (France, Espagne), sel",
        "Jambon (France et Espagne), sel",
        "Jambon (UE), sel",
        "Jambon (UE/non UE), sel",
        "Jambon (hors UE), sel",
        "Jambon (Germany), sel",
        "Jambon (Côte d'Ivoire), sel",
        "Jambon [Allemagne], sel",
    ],
)
def test_an_origin_is_not_a_part_of_the_ingredient(text: str):
    assert tree(parse_label(text)) == [("jambon", None, []), ("sel", None, [])]


def test_an_origin_ahead_of_the_parts_does_not_hide_them():
    text = "Gnocchi (Italie) [semoule, eau 5 %], sel"

    assert tree(parse_label(text)) == [
        ("gnocchi", None, [("semoule", None, []), ("eau", "5", [])]),
        ("sel", None, []),
    ]


def test_an_origin_next_to_a_percentage_leaves_the_percentage_where_it_was():
    assert tree(parse_label("Tomates 40 % (Italie), sel")) == [
        ("tomates", "40", []),
        ("sel", None, []),
    ]


# Parentheses that hold more than countries, or a word that is also a food.
NOT_ORIGINS: list[tuple[str, list[Any]]] = [
    ("Saucisse (Allemagne, porc), sel", [("allemagne", None, []), ("porc", None, [])]),
    ("Saucisse (dinde, Italie), sel", [("dinde", None, []), ("italie", None, [])]),
    ("Saucisse (turkey, pork), sel", [("turkey", None, []), ("pork", None, [])]),
    ("Sauce (chili), sel", [("chili", None, [])]),
]


@pytest.mark.parametrize(("text", "parts"), NOT_ORIGINS)
def test_parentheses_that_hold_more_than_countries_are_read_as_parts(
    text: str, parts: list[Any]
):
    [first, _salt] = tree(parse_label(text))

    assert first[2] == parts


@pytest.mark.parametrize(
    "text",
    [
        "Semoule de blé (gluten), sel",
        "Semoule de blé (GLUTEN*), sel",
        "Semoule de blé (blé, lait), sel",
        "Semoule de blé (blé et lait), sel",
        "Semoule de blé (contient du lait), sel",
        "Semoule de blé (Contains milk), sel",
        "Semoule de blé (œufs), sel",
        "Semoule de blé (OEUFS), sel",
        "Semoule de blé (noix de cajou), sel",
        "Semoule de blé (fruits à coque), sel",
        "Semoule de blé (anhydride sulfureux), sel",
        "Semoule de blé [soja], sel",
    ],
)
def test_an_allergen_declaration_is_not_a_part_of_the_ingredient(text: str):
    assert tree(parse_label(text)) == [("semoule de blé", None, []), ("sel", None, [])]


def test_an_allergen_declaration_ahead_of_the_parts_does_not_hide_them():
    text = "Gnocchi (gluten) [semoule, eau 5 %], sel"

    assert tree(parse_label(text)) == [
        ("gnocchi", None, [("semoule", None, []), ("eau", "5", [])]),
        ("sel", None, []),
    ]


# Parts that are not allergens, or that say more than an allergen does.
NOT_ALLERGENS: list[tuple[str, list[Any]]] = [
    ("Pâtes (blé, eau), sel", [("blé", None, []), ("eau", None, [])]),
    ("Pâte (lait écrémé), sel", [("lait écrémé", None, [])]),
    ("Farine (gluten de blé), sel", [("gluten de blé", None, [])]),
    ("Pâte (lait 5 %, eau), sel", [("lait", "5", []), ("eau", None, [])]),
    ("Chocolat (lait, cacao), sel", [("lait", None, []), ("cacao", None, [])]),
]


@pytest.mark.parametrize(("text", "parts"), NOT_ALLERGENS)
def test_parentheses_that_hold_more_than_allergens_are_read_as_parts(
    text: str, parts: list[Any]
):
    [first, _salt] = tree(parse_label(text))

    assert first[2] == parts


def test_a_note_inside_the_parts_is_ignored_there_too():
    text = "Gnocchi (semoule (origine : France), eau (bio)), sel"

    assert tree(parse_label(text)) == [
        ("gnocchi", None, [("semoule", None, []), ("eau", None, [])]),
        ("sel", None, []),
    ]


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
    """A heading that is not a class of additives: the rest is in what it names."""
    text = "Sucre, préparation de fruits : fraises [SOJA]; vanilline, sel"

    assert tree(parse_label(text)) == [
        ("sucre", None, []),
        ("préparation de fruits", None, [("fraises", None, [])]),
        ("vanilline", None, []),
        ("sel", None, []),
    ]


def test_a_percentage_after_the_parenthesis_belongs_to_the_ingredient():
    text = "sucre de canne (contient BLE) 8,5%, LACTOSE"

    assert tree(parse_label(text)) == [
        ("sucre de canne", "8.5", []),
        ("lactose", None, []),
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("GLUTEN de BLE", ["gluten de blé"]),
        (
            "Farine de BLE, GLUTEN de BLE, sel",
            ["farine de blé", "gluten de blé", "sel"],
        ),
        ("FARINE DE BLE, OEUFS, EPEAUTRE", ["farine de blé", "œufs", "épeautre"]),
        (
            "CELERI, CRUSTACES, noix du BRESIL",
            ["céleri", "crustacés", "noix du brésil"],
        ),
        # What a label spells with the accent is kept, and so is a word that is not
        # in capitals: the text says "ble".
        ("GLUTEN de BLÉ", ["gluten de blé"]),
        ("gluten de ble", ["gluten de ble"]),
        # Words that are not French only are left as written.
        ("SESAME, CEREALES, CACAHUETE", ["sesame", "cereales", "cacahuete"]),
        ("WHEAT FLOUR, MAIS", ["wheat flour", "mais"]),
    ],
)
def test_capitals_get_back_the_accent_labels_print_them_without(
    text: str, expected: list[str]
):
    assert [i.name for i in parse_label(text)] == expected


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
    text = "Sucre (origine UE), cacao (bio), farine, sel"

    assert tree(parse_label(text)) == [
        ("sucre", None, []),
        ("cacao", None, []),
        ("farine", None, []),
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
        ("e-150d", None, []),
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
        ("Farine, huile d'olive, 2,3 %, sel", Problem.NAMELESS_PERCENT),
        ("Farine, 5 %, sel", Problem.NAMELESS_PERCENT),
        ("Glucides (sucres, 5 %), sel", Problem.NAMELESS_PERCENT),
        ("Farine; soit 12 %; sel", Problem.NAMELESS_PERCENT),
        # A percentage in parentheses is its name's only when it is plain whose it is.
        ("Farine, (7 %), sel", Problem.NAMELESS_PERCENT),
        ("Dattes 7 % (7 %), sel", Problem.NAMELESS_PERCENT),
        ("Dattes (7 %) 8 %, sel", Problem.NAMELESS_PERCENT),
        ("Dattes (150 %), sel", Problem.NAMELESS_PERCENT),
        ("Farine, a, sel", Problem.SHORT_NAME),
        ("Peut contenir des traces de lait", Problem.NOTHING_READ),
    ],
)
def test_signs_of_a_text_read_badly_stop_the_reading(text: str, problem: Problem):
    reading = read_label(text)

    assert reading.items == []
    assert problem in [w.problem for w in reading.warnings]


def test_the_warning_for_a_percentage_with_no_name_is_in_the_language_served():
    warning = read_label("Farine, huile, 2,3 %, sel").warnings[0]

    with translation.override("fr"):
        assert warning.message() == "Un pourcentage sans nom d'ingrédient : 2,3 %"


# A name with its percentage in parentheses is a part, whose percentage is its
# share of the ingredient: it used to be taken for the ingredient's own.
PARTS_WITH_PERCENTAGE: list[tuple[str, Any]] = [
    ("Chocolat (cacao 70 %), sucre", ("chocolat", None, [("cacao", "70", [])])),
    ("Dattes 7 % (riz 2 %), sucre", ("dattes", "7", [("riz", "2", [])])),
    ("Dattes (riz 2 %) 7 %, sucre", ("dattes", "7", [("riz", "2", [])])),
]


@pytest.mark.parametrize(("text", "first"), PARTS_WITH_PERCENTAGE)
def test_a_name_and_a_percentage_in_parentheses_are_a_part(text: str, first: Any):
    assert tree(parse_label(text))[0] == first
    assert read_label(text).warnings == []


# The percentage some labels write in parentheses right after the name: the same
# as one written next to it.
ENGLISH_BAR = (
    "Dates (38%), Peanuts (35%), Chicory fibre (10%), Peanut flour (8%), "
    "Hazelnuts (5%), Fat-reduced cocoa powder (3%), natural flavouring."
)


def test_a_percentage_in_parentheses_after_the_name_is_the_ingredients():
    """Product 5060088700112: the reading used to stop on its first percentage."""
    reading = read_label(ENGLISH_BAR)

    assert tree(reading.items) == [
        ("dates", "38", []),
        ("peanuts", "35", []),
        ("chicory fibre", "10", []),
        ("peanut flour", "8", []),
        ("hazelnuts", "5", []),
        ("fat-reduced cocoa powder", "3", []),
        ("natural flavouring", None, []),
    ]
    assert reading.warnings == []


PERCENT_IN_PARENTHESES: list[tuple[str, Any]] = [
    ("Dattes (7 %), sel", ("dattes", "7", [])),
    ("Farine (min. 12 %), sel", ("farine", "12", [])),
    ("Sucre (56,3%), sel", ("sucre", "56.3", [])),
    ("Dattes (bio) (7 %), sel", ("dattes", "7", [])),
    # What follows names the parts, as it does after a percentage written beside.
    (
        "Dattes (7 %) (dattes, farine de riz), sel",
        ("dattes", "7", [("dattes", None, []), ("farine de riz", None, [])]),
    ),
    (
        "Chocolat (12 %) [cacao, sucre], sel",
        ("chocolat", "12", [("cacao", None, []), ("sucre", None, [])]),
    ),
    # Inside the parts.
    (
        "Chocolat (cacao (70 %), sucre), sel",
        ("chocolat", None, [("cacao", "70", []), ("sucre", None, [])]),
    ),
]


@pytest.mark.parametrize(("text", "expected"), PERCENT_IN_PARENTHESES)
def test_a_percentage_in_parentheses_is_read_as_one_written_beside(
    text: str, expected: Any
):
    assert tree(parse_label(text))[0] == expected
    assert read_label(text).warnings == []


def test_a_percentage_in_parentheses_after_a_class_is_the_additives():
    items = parse_label("Acidifiant : acide citrique (0,5 %), sel")

    assert [(i.name, i.percentage, i.function) for i in items] == [
        ("acide citrique", D("0.5"), "acid"),
        ("sel", None, ""),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Sel 5 %, sucre",
        "Farine, noisettes 13%, sel",
        "Sucre 56,3 %, lait (lait écrémé)",
        "Céréale 50 % (Farine de blé 34,8 %, farine de blé complet 15,2 %), sucre",
    ],
)
def test_a_percentage_next_to_its_ingredient_is_not_a_percentage_with_none(text: str):
    assert Problem.NAMELESS_PERCENT not in problems(text)
    assert read_label(text).items


def test_a_long_text_with_no_separator_is_not_read_as_one_ingredient():
    text = " ".join(["farine de blé sucre sel huile de palme levure"] * 5)

    reading = read_label(text)

    assert reading.items == []
    assert Problem.NOT_A_LIST in [w.problem for w in reading.warnings]
    assert Problem.LONG_NAME in [w.problem for w in reading.warnings]


@pytest.mark.parametrize(
    "text",
    [
        "Farine - sucre - sel",
        "Farine \u2013 sucre \u2014 sel",
        "Farine, sucre - sel",
        "- farine - sucre - sel",
        "Farine -\nSucre -\nSel",
    ],
)
def test_a_dash_on_its_own_parts_ingredients_as_a_comma_does(text: str):
    reading = read_label(text)

    assert [i.name for i in reading.items] == ["farine", "sucre", "sel"]
    assert reading.warnings == []


def test_a_dash_parts_ingredients_in_parentheses_and_leaves_their_percentages():
    reading = read_label("Chocolat 40 % (cacao - sucre 20 %) - sel")

    assert tree(reading.items) == [
        ("chocolat", "40", [("cacao", None, []), ("sucre", "20", [])]),
        ("sel", None, []),
    ]
    assert reading.warnings == []


def test_a_dash_is_no_part_of_the_places_read():
    text = "Farine - sucre"

    reading = read_label(text)

    assert [text[start:end] for start, end in reading.used] == ["Farine", "sucre"]


def test_a_dash_in_a_word_is_the_word_s():
    reading = read_label("Oméga-3 - lait demi-écrémé, sirop de glucose-fructose")

    assert [i.name for i in reading.items] == [
        "oméga-3",
        "lait demi-écrémé",
        "sirop de glucose-fructose",
    ]


@pytest.mark.parametrize(
    "text", ["Farine (gluten - lait), sel", "Farine (UE - USA), sel"]
)
def test_a_dash_parts_the_allergens_and_the_origins_of_a_note(text: str):
    assert tree(parse_label(text)) == [("farine", None, []), ("sel", None, [])]


def test_two_dashes_in_a_row_leave_an_empty_place_as_two_commas_do():
    assert problems("Farine - - sucre") == [Problem.EMPTY_ITEM]


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


# ----------------------------------------------------------------------------
# Additives: the class that heads them, and the E number next to a name
# ----------------------------------------------------------------------------
def classes(items: list[LabelItem] | tuple[LabelItem, ...]) -> list[Any]:
    """Names with the class and the code the label gave them, and their parts."""
    return [
        (i.name, i.function, i.code, classes(i.parts)) if i.parts else
        (i.name, i.function, i.code)
        for i in items
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("E330", "E330"),
        ("e330", "E330"),
        ("E 330", "E330"),
        ("E-150d", "E150D"),
        ("  e  330 ", "E330"),
        ("E160a", "E160A"),
        ("E 160 a", "E160A"),
        ("E1001(ii)", "E1001II"),
        ("E1001ii", "E1001II"),
        ("E100", "E100"),
        ("E160aiii", "E160AIII"),
        ("e450viii", "E450VIII"),
    ],
)
def test_an_e_number_is_read_as_the_code_it_is(name: str, code: str):
    assert e_number(name) == code


@pytest.mark.parametrize(
    "name",
    [
        "",
        "E",
        "E33",
        "E12345",
        "acide citrique",
        "E330 acid",
        "vitamine E",
        "eau",
        "E3a0",
        "Exxx",
        "E14xx",
        "E15x",
    ],
)
def test_a_name_that_is_not_an_e_number_gives_no_code(name: str):
    assert e_number(name) == ""


def test_a_class_with_a_colon_is_what_the_item_that_follows_is_for():
    items = parse_label("Farine, acidifiant : acide citrique, sel")

    assert classes(items) == [
        ("farine", "", ""),
        ("acide citrique", "acid", ""),
        ("sel", "", ""),
    ]


def test_a_class_with_a_colon_applies_to_the_item_that_follows_and_no_further():
    """The text does not say where the list ends, so it is not guessed."""
    items = parse_label("Sucre, colorants : caramel, rocou, sel")

    assert classes(items) == [
        ("sucre", "", ""),
        ("caramel", "colour", ""),
        ("rocou", "", ""),
        ("sel", "", ""),
    ]


def test_a_class_with_a_colon_keeps_the_parts_of_the_item_that_follows():
    items = parse_label("Chocolat, émulsifiants : lécithines (tournesol), vanilline")

    assert classes(items) == [
        ("chocolat", "", ""),
        ("lécithines", "emulsifier", "", [("tournesol", "", "")]),
        ("vanilline", "", ""),
    ]


def test_a_class_with_a_colon_and_its_item_inside_a_bracketed_list():
    """The label of the gnocchi: the mozzarella lists an acidifier among its parts."""
    items = parse_label("Mozzarella 6 % [lait, sel, acidifiant : acide citrique]")

    assert tree(items) == [
        (
            "mozzarella",
            "6",
            [("lait", None, []), ("sel", None, []), ("acide citrique", None, [])],
        )
    ]
    [mozzarella] = items
    assert [part.function for part in mozzarella.parts] == ["", "", "acid"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("colorant (E150a)", [("e150a", "colour", "")]),
        (
            "conservateurs (E202, E211)",
            [("e202", "preservative", ""), ("e211", "preservative", "")],
        ),
        ("colorants (E 150 a)", [("e 150 a", "colour", "")]),
        ("antioxydant (acide ascorbique)", [("acide ascorbique", "antioxidant", "")]),
        ("épaississants (pectines, gomme guar)", [
            ("pectines", "thickener", ""),
            ("gomme guar", "thickener", ""),
        ]),
        (
            "preservative (potassium sorbate)",
            [("potassium sorbate", "preservative", "")],
        ),
        ("colour (E150d)", [("e150d", "colour", "")]),
        ("stabilisants (E412)", [("e412", "stabiliser", "")]),
    ],
)  # fmt: skip
def test_a_class_with_parentheses_is_what_every_item_in_them_is_for(
    text: str, expected: list[tuple[str, str, str]]
):
    assert classes(parse_label(text)) == expected


@pytest.mark.parametrize(
    "text",
    [
        "amidon modifié (maïs)",
        "poudre à lever (bicarbonate de sodium)",
        "support (huile)",
    ],
)
def test_a_class_that_is_also_an_ingredient_is_a_heading_only_with_e_numbers(
    text: str,
):
    [item] = parse_label(text)

    assert item.function == ""
    assert [part.name for part in item.parts]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("amidons modifiés (E1422)", [("e1422", "modified_starch", "")]),
        ("poudres à lever (E500, E450)", [
            ("e500", "raising_agent", ""),
            ("e450", "raising_agent", ""),
        ]),
    ],
)  # fmt: skip
def test_those_classes_head_a_list_of_e_numbers_all_the_same(
    text: str, expected: list[tuple[str, str, str]]
):
    assert classes(parse_label(text)) == expected


@pytest.mark.parametrize(
    "text",
    ["sucre, antioxydant, sel", "sucre, colorants :, sel", "sucre, stabilisant"],
)
def test_a_class_with_nothing_after_it_is_read_as_any_word_is(text: str):
    reading = read_label(text)

    assert [i.function for i in reading.items] == [""] * len(reading.items)
    assert any(
        item.name in ("antioxydant", "colorants", "stabilisant")
        for item in reading.items
    )
    assert reading.warnings == []


def test_a_class_with_a_percentage_is_still_an_ingredient():
    """A share written on the heading cannot go to the items under it."""
    items = parse_label("Chocolat, émulsifiants 0,5 % (lécithines), sel")

    assert classes(items) == [
        ("chocolat", "", ""),
        ("émulsifiants", "", "", [("lécithines", "", "")]),
        ("sel", "", ""),
    ]
    assert items[1].percentage == D("0.5")


@pytest.mark.parametrize(
    ("text", "name", "code"),
    [
        ("acide citrique (E330)", "acide citrique", "E330"),
        ("Acide citrique (e 330)", "acide citrique", "E330"),
        ("E330 (acide citrique)", "acide citrique", "E330"),
        ("E 471 (mono- et diglycérides)", "mono- et diglycérides", "E471"),
    ],
)  # fmt: skip
def test_an_e_number_next_to_a_name_is_its_code_and_not_one_of_its_parts(
    text: str, name: str, code: str
):
    [item] = parse_label(text)

    assert (item.name, item.code, item.parts) == (name, code, ())


def test_the_percentage_of_an_additive_with_a_code_is_kept():
    [item] = parse_label("acide citrique (E330) 0,2 %")

    assert (item.name, item.code, item.percentage) == (
        "acide citrique",
        "E330",
        D("0.2"),
    )


def test_two_codes_or_more_in_parentheses_stay_the_parts_they_were():
    [item] = parse_label("lécithines (E322, E471)")

    assert (item.name, item.code, [p.name for p in item.parts]) == (
        "lécithines",
        "",
        ["e322", "e471"],
    )


def test_an_allergen_next_to_a_code_is_still_dropped_and_the_code_is_the_name():
    [item] = parse_label("E322 (soja)")

    assert (item.name, item.code) == ("e322", "")
    assert item.parts == ()


def test_an_e_number_among_ingredients_is_not_a_name_that_is_too_short():
    reading = read_label("Farine de blé, E330, sel")

    assert [i.name for i in reading.items] == ["farine de blé", "e330", "sel"]
    assert reading.warnings == []


def test_every_class_of_additives_has_its_words_and_is_one_of_the_closed_list():
    assert set(_CLASS_WORDS) == set(Additive.Function.values)
    assert all(words for words in _CLASS_WORDS.values())


# ----------------------------------------------------------------------------
# Where in the text the ingredients were read
# ----------------------------------------------------------------------------
def marked(text: str, ignored: list[tuple[int, int]] | None = None) -> str:
    """The text with the places read between ⟦ ⟧: a reading made visible."""
    reading = read_label(text, ignored or [])
    out, position = "", 0
    for start, end in reading.used:
        out += text[position:start] + "⟦" + text[start:end] + "⟧"
        position = end
    return out + text[position:]


# Colin d'Alaska (3270160196876): the fishing zone in brackets was read as parts.
POLLOCK = (
    "Filets de colin d'Alaska MSC (POISSONS) 72% qualité sans arête* "
    "[Theragra chalcogramma sauvage pêché dans l'Océan Pacifique Nord-Est (FAO 67) "
    "ou Nord-Ouest (FAO 61), zone de pêche indiquée dans le cadre de datage], "
    "farine de BLÉ (GLUTEN), huile de colza, eau. Peut contenir des traces de : "
    "sésame. Malgré tout le soin apporté à nos poissons, la présence d'arête "
    "n'est jamais exclue."
)
POLLOCK_ZONE = (
    POLLOCK.index("[Theragra"),
    POLLOCK.index("datage]") + len("datage]"),
)


def test_the_names_and_percentages_are_the_places_that_were_read():
    text = "Flocons de soja* 31%, Dattes* 7% (dattes*, farine de riz*), sel"

    assert marked(text) == (
        "⟦Flocons de soja* 31%⟧, ⟦Dattes* 7%⟧ (⟦dattes*⟧, ⟦farine de riz*⟧), ⟦sel⟧"
    )


def test_what_is_not_an_ingredient_is_not_a_place_that_was_read():
    """Notes, origins, allergens, the heading of a class, the statements after."""
    text = (
        "Pâte cuite 60,5% (Allemagne) [eau, semoule de blé (gluten)], "
        "acidifiant : acide citrique, tomates (origine : Italie), lait (bio). "
        "Peut contenir des traces de sésame."
    )

    assert marked(text) == (
        "⟦Pâte cuite 60,5%⟧ (Allemagne) [⟦eau⟧, ⟦semoule de blé⟧ (gluten)], "
        "acidifiant : ⟦acide citrique⟧, ⟦tomates⟧ (origine : Italie), ⟦lait⟧ (bio). "
        "Peut contenir des traces de sésame."
    )


def test_a_percentage_in_parentheses_is_read_with_its_name():
    assert marked("Dattes (7 %), riz") == "⟦Dattes⟧ (⟦7 %⟧), ⟦riz⟧"


def test_an_allergen_between_the_words_of_a_name_is_left_out_of_the_place():
    """The notes are not the name's, though they stand inside it."""
    text = "Filets de colin (POISSONS) 72% qualité sans arête*, sel"

    assert (
        marked(text) == "⟦Filets de colin⟧ (POISSONS) ⟦72% qualité sans arête*⟧, ⟦sel⟧"
    )


def test_the_codes_next_to_a_name_are_read_places_too():
    assert marked("acide citrique (E330), E322 (lécithine)") == (
        "⟦acide citrique⟧ (⟦E330⟧), ⟦E322⟧ (⟦lécithine⟧)"
    )


def test_the_places_are_those_of_the_text_given_not_of_the_text_cleaned():
    """A title, tags, carriage returns and the white space around are taken out."""
    text = "  Ingrédients : <b>sucre</b>\r\n, _lait_ (bio)"

    assert marked(text) == "  Ingrédients : <b>⟦sucre⟧</b>\r\n, ⟦_lait_⟧ (bio)"


def test_a_text_that_is_not_read_has_no_place_that_was_read():
    reading = read_label("Farine, huile, 2,3 %, sel")

    assert reading.items == []
    assert reading.used == ()


def test_the_places_do_not_overlap_and_are_in_order():
    reading = read_label(MUESLI)
    spans = list(reading.used)

    assert spans == sorted(spans)
    assert all(a_end <= b_start for (_, a_end), (b_start, _) in pairwise(spans))
    assert all(MUESLI[start:end].strip() == MUESLI[start:end] for start, end in spans)


def test_the_fishing_zone_is_read_as_parts_until_a_person_ignores_it():
    first = read_label(POLLOCK)
    [fish, *others] = first.items

    assert [p.name for p in fish.parts][:1] == [
        "theragra chalcogramma sauvage pêché dans l'océan pacifique nord-est"
    ]
    assert [i.name for i in others] == ["farine de blé", "huile de colza", "eau"]

    second = read_label(POLLOCK, [POLLOCK_ZONE])
    [fish, *others] = second.items

    assert tree([fish]) == [
        ("filets de colin d'alaska msc qualité sans arête", "72", [])
    ]
    assert [i.name for i in others] == ["farine de blé", "huile de colza", "eau"]
    assert second.warnings == []


def test_an_ignored_place_is_not_marked_and_the_rest_is_still():
    text = marked(POLLOCK, [POLLOCK_ZONE])

    assert "[Theragra" in text
    assert "⟦Theragra" not in text
    assert text.startswith("⟦Filets de colin d'Alaska MSC⟧ (POISSONS) ⟦72% qualité")
    assert "⟦farine de BLÉ⟧ (GLUTEN), ⟦huile de colza⟧, ⟦eau⟧." in text


def test_what_is_wrong_in_an_ignored_place_is_not_seen_any_more():
    text = "Farine, sucre, Valeurs nutritionnelles 100 kJ, sel"
    start = text.index("Valeurs")
    end = text.index(", sel")

    assert Problem.OTHER_TEXT in problems(text)
    reading = read_label(text, [(start, end)])

    assert reading.warnings == []
    assert [i.name for i in reading.items] == ["farine", "sucre", "sel"]


def test_the_half_of_a_group_ignored_leaves_the_other_unbalanced_and_says_so():
    """Nothing is repaired: a person who takes out half of a group is told."""
    text = "Farine, sucre (cassonade, miel), sel"
    start = text.index("miel")

    reading = read_label(text, [(start, start + len("miel)"))])

    assert Problem.UNBALANCED in [w.problem for w in reading.warnings]
    assert reading.items == []


def test_ignoring_everything_reads_nothing():
    text = "Farine, sucre"

    reading = read_label(text, [(0, len(text))])

    assert reading.items == []
    assert [w.problem for w in reading.warnings] == [Problem.NOTHING_READ]


@pytest.mark.parametrize("ignored", [[(-5, 3)], [(10, 10_000)], [(7, 3)], [(100, 200)]])
def test_places_outside_the_text_or_empty_are_harmless(ignored: list[tuple[int, int]]):
    reading = read_label("Farine, sucre, sel", ignored)

    assert reading.items or reading.warnings


def test_ignoring_nothing_reads_the_text_as_it_is():
    assert read_label(MUESLI, []) == read_label(MUESLI)
    assert read_label(MUESLI, ()) == read_label(MUESLI)


@pytest.mark.parametrize(
    "head",
    [
        "Flocons de soja* 31%",
        "dont sucre 5 %",
        "  Fruits rouges* lyophilisés 1,4% ",
        "_lait_",
        "Filets  de colin 72% qualité\nsans arête*",
        "min. 12 % sucre",
        "Dattes bio",
        "E330",
        "dont dont sucre",
    ],
)
def test_the_name_kept_in_the_places_read_is_the_name_read(head: str):
    """_name_spans does what _name does on blanks, and must stay where it does."""
    spans = _name_spans(head, 0, ())
    placed = " ".join(head[a:b] for a, b in spans)

    assert _name(placed) == _name(head)


# ----------------------------------------------------------------------------
# Vitamins: a list of them is one ingredient each, a name said twice is one
# ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "names"),
    [
        (
            "Farine, vitamines (E, PP, B6, B1, B9), sel",
            ["farine", "vitamine e", "vitamine pp", "vitamine b6", "vitamine b1",
             "vitamine b9", "sel"],
        ),
        ("Farine, Vitamines (B6, D3)", ["farine", "vitamine b6", "vitamine d3"]),
        ("Flour, vitamins (B6, D), salt", ["flour", "vitamin b6", "vitamin d", "salt"]),
        ("Farine, vitamines : C, sel", ["farine", "vitamine c", "sel"]),
        (
            "Vitamines (vitamine C, cholécalciférol)",
            ["vitamine c", "cholécalciférol"],
        ),
    ],
)  # fmt: skip
def test_a_list_of_vitamins_is_one_ingredient_each_and_no_ingredient_with_parts(
    text: str, names: list[str]
):
    reading = read_label(text)

    assert [i.name for i in reading.items] == names
    assert all(not i.parts for i in reading.items)
    assert reading.warnings == []


def test_the_vitamins_of_a_list_keep_their_own_percentage():
    items = parse_label("Farine, vitamines (B6 0,1 %, D)")

    assert tree(items) == [
        ("farine", None, []),
        ("vitamine b6", "0.1", []),
        ("vitamine d", None, []),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Farine, vitamines (B6, fer), sel",
        "Farine, vitamines 0,1 % (B6, D), sel",
        "Farine, vitamines (B6, D) 0,1 %, sel",
        "Farine, vitamines (de la bonne famille), sel",
    ],
)
def test_vitamins_that_are_not_only_vitamins_of_the_list_are_read_as_parts(text: str):
    items = parse_label(text)

    assert [i.name for i in items] == ["farine", "vitamines", "sel"]
    assert items[1].parts


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Farine, acide ascorbique (vitamine C)", "acide ascorbique"),
        ("Farine, riboflavine (vitamine B2)", "riboflavine"),
        ("Farine, vitamine D (cholécalciférol)", "vitamine d"),
        ("Farine, vitamine B6 (chlorhydrate de pyridoxine)", "vitamine b6"),
        ("Flour, vitamin D (cholecalciferol)", "vitamin d"),
    ],
)
def test_a_vitamin_and_the_name_of_its_vitamin_are_one_substance_not_a_part(
    text: str, name: str
):
    items = parse_label(text)

    assert tree(items) == [("farine" if "Farine" in text else "flour", None, []),
                           (name, None, [])]  # fmt: skip


def test_the_vitamin_a_food_is_fortified_with_stays_one_of_its_parts():
    items = parse_label("Lait enrichi (lait, vitamine D), sel")

    assert tree(items) == [
        ("lait enrichi", None, [("lait", None, []), ("vitamine d", None, [])]),
        ("sel", None, []),
    ]


def test_a_vitamin_next_to_a_name_that_is_not_one_keeps_its_parts():
    items = parse_label("Farine, premix (vitamine C, vitamine D)")

    assert tree(items) == [
        ("farine", None, []),
        ("premix", None, [("vitamine c", None, []), ("vitamine d", None, [])]),
    ]


def test_the_places_of_a_list_of_vitamins_are_those_of_the_letters_not_the_heading():
    text = "Farine, vitamines (B6, D)"
    reading = read_label(text)

    read = [text[start:end] for start, end in reading.used]

    assert read == ["Farine", "B6", "D"]
