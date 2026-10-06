from decimal import Decimal
from typing import Any

import pytest
from django.utils import translation

from opennutrilab.products.models import Additive
from opennutrilab.products.services.label_parser import (
    _CLASS_WORDS,  # pyright: ignore[reportPrivateUsage]
)
from opennutrilab.products.services.label_parser import LabelItem
from opennutrilab.products.services.label_parser import Problem
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
        # A percentage is written next to its ingredient, not in parentheses of its own.
        ("Dattes (7 %), sel", Problem.NAMELESS_PERCENT),
        ("Farine (min. 12 %), sel", Problem.NAMELESS_PERCENT),
        ("Dattes 7 % (7 %), sel", Problem.NAMELESS_PERCENT),
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
