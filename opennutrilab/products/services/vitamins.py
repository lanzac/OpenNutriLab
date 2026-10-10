"""
The names a label gives a vitamin, and the nutrient each one is.

"Vitamine B6" on a label is a vitamin and not a food: it has no composition to
draw on, it is the nutrient `vitamin_b6` of the catalogue added to the product. So
an ingredient of that name is that nutrient (Ingredient.nutrient), a kind of
ingredient of its own as an additive is, and no reference is made for it (see
reference_services).

Only what is certain is here, a closed list as the countries and the allergens of
label_parser are: the vitamin as "vitamine B6" / "vitamin B6" / "vit. B6" (the letter
and the digits being the nutrient's), and the forms a label names it by
("chlorhydrate de pyridoxine", "cholécalciférol"). A name not in it is no vitamin
as far as this goes: it makes a reference to review as any name does. The forms
that are additives with an E number (ascorbic acid, riboflavin) are in it too, so
that "acide ascorbique (vitamine C)" is read as one substance; an additive of that
name is found before the nutrient is.

The module needs nothing of Django, so that the reading of a label can use it.
"""

import re
import unicodedata

# The letters (and digits) a vitamin is called by, as the nutrient they are. "PP" is
# the old name of B3.
LETTERS: dict[str, str] = {
    "a": "vitamin_a",
    "b1": "vitamin_b1",
    "b2": "vitamin_b2",
    "b3": "vitamin_b3",
    "pp": "vitamin_b3",
    "b5": "vitamin_b5",
    "b6": "vitamin_b6",
    "b9": "vitamin_b9",
    "b12": "vitamin_b12",
    "c": "vitamin_c",
    "d": "vitamin_d",
    "d2": "vitamin_d2",
    "d3": "vitamin_d3",
    "e": "vitamin_e",
    "k": "vitamin_k",
    "k1": "vitamin_k1",
    "k2": "vitamin_k2",
}

# What a label heads a list of them with: "Vitamines (B6, D)".
HEADINGS = frozenset({"vitamine", "vitamines", "vitamin", "vitamins"})

# The forms a label names a vitamin by, folded (no accents, lower case), and the
# nutrient of the catalogue each is.
FORMS: dict[str, str] = {
    # B1
    "thiamine": "vitamin_b1",
    "thiamin": "vitamin_b1",
    "chlorhydrate de thiamine": "vitamin_b1",
    "hydrochlorure de thiamine": "vitamin_b1",
    "mononitrate de thiamine": "vitamin_b1",
    "thiamine hydrochloride": "vitamin_b1",
    "thiamine mononitrate": "vitamin_b1",
    # B2
    "riboflavine": "vitamin_b2",
    "riboflavin": "vitamin_b2",
    # B3
    "niacine": "vitamin_b3",
    "niacin": "vitamin_b3",
    "nicotinamide": "vitamin_b3",
    "acide nicotinique": "vitamin_b3",
    # B5
    "acide pantothenique": "vitamin_b5",
    "pantothenic acid": "vitamin_b5",
    "pantothenate de calcium": "vitamin_b5",
    "d-pantothenate de calcium": "vitamin_b5",
    "calcium pantothenate": "vitamin_b5",
    # B6
    "pyridoxine": "vitamin_b6",
    "chlorhydrate de pyridoxine": "vitamin_b6",
    "hydrochlorure de pyridoxine": "vitamin_b6",
    "pyridoxine hydrochloride": "vitamin_b6",
    # B9
    "folate": "vitamin_b9",
    "folates": "vitamin_b9",
    "acide folique": "folic_acid",
    "folic acid": "folic_acid",
    # B12
    "cobalamine": "vitamin_b12",
    "cyanocobalamine": "vitamin_b12",
    "methylcobalamine": "vitamin_b12",
    "hydroxocobalamine": "vitamin_b12",
    "cobalamin": "vitamin_b12",
    "cyanocobalamin": "vitamin_b12",
    # C
    "acide ascorbique": "vitamin_c",
    "ascorbic acid": "vitamin_c",
    "ascorbate de sodium": "vitamin_c",
    "ascorbate de calcium": "vitamin_c",
    # D
    "cholecalciferol": "vitamin_d3",
    "ergocalciferol": "vitamin_d2",
    # K
    "phylloquinone": "vitamin_k1",
    "menaquinone": "vitamin_k2",
    # A
    "retinol": "retinol",
    "palmitate de retinyle": "vitamin_a",
    "acetate de retinyle": "vitamin_a",
    "retinyl palmitate": "vitamin_a",
    "retinyl acetate": "vitamin_a",
    # E
    "acetate de tocopheryle": "vitamin_e",
    "acetate de d-alpha-tocopheryle": "vitamin_e",
    "acetate de dl-alpha-tocopheryle": "vitamin_e",
    "tocopheryl acetate": "vitamin_e",
}

# "vitamine B6", "vitamin b6", "vit. b6", "vit B6": the word, then the letters.
_NAMED = re.compile(r"^(?:vitamine|vitamin|vit)(?:\.\s*|\s+)([a-z]{1,2}\d{0,2})$")


def _folded(name: str) -> str:
    """Lower case, no accents, single spaces: "Cholécalciférol" is "cholecalciferol"."""
    text = unicodedata.normalize("NFD", name.casefold())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(text.split())


def vitamin_nutrient(name: str) -> str:
    """
    The code of the nutrient a name is, "" when it is no vitamin of the closed list.
    "vitamine B6" is `vitamin_b6`, "cholécalciférol" `vitamin_d3`.
    """
    key = _folded(name)
    if (named := _NAMED.match(key)) is not None:
        return LETTERS.get(named.group(1), "")
    return FORMS.get(key, "")


def vitamin_called(name: str, heading: str) -> str:
    """
    A vitamin as a list under `heading` ("vitamines") names it, "" when it is none:
    the letters alone, "B6" and "pp", are "vitamine b6" and "vitamine pp"; a vitamin's
    name or form is as it is.
    """
    key = _folded(name)
    if key in LETTERS:
        word = "vitamine" if _folded(heading).startswith("vitamine") else "vitamin"
        return f"{word} {key}"
    return name if vitamin_nutrient(name) else ""
