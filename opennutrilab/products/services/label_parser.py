"""
Reading an ingredient list as the label prints it.

The text of the label is the reliable source: whoever holds the product reads
it, and it is what a manufacturer is bound to. What a database made of it
(OpenFoodFacts' parsed ingredients) keeps is not: it drops what its taxonomy
has no word for ("Flocons de soja" became "soja", "Fruits rouges lyophilisés"
"Fruits rouges", and "Graines de sarrasin" was left out altogether), and those
words are what tell one food from another. So the ingredients are read from the
text, here, and nothing else is trusted.

An ingredient is a name, the percentage written next to it if there is one, and
the ingredients in the parentheses that follow it:

    Dattes* 7% (dattes*, farine de riz*)  ->  dattes, 7 %: dattes, farine de riz

Ingredients are parted by commas and semicolons, and by a dash on its own between
spaces ("farine - sucre - sel"), not by the dash of a word ("oméga-3").

Only what the text says is kept: no name is corrected or guessed. Names come out
in lower case, without the marks a label adds around them (the asterisk of
organic ingredients, the capitals of allergens, the word "bio"). The one thing put
back is the accent that capitals are printed without: "GLUTEN de BLE" is "gluten de
blé". It is done for the few French words the allergens are written in capitals
with (_CAPITALS_ACCENTED), and only for a word in capitals: "ble" in lower case is
what the text says. The list ends where the label's own sentence does, before
"Peut contenir...". Labels differ, so what cannot be read as a list (a note in
parentheses, a heading) is left out rather than turned into an ingredient, and a
name that is wrong is the curator's to see: it makes a reference to review.

A percentage may be written in parentheses right after the name it belongs to, as
some labels do: "Dattes (38 %)" is "Dattes 38 %". Parentheses that hold nothing
else are that percentage and no part of the ingredient (see _percent_beside).

A functional class of additives heading a list is not an ingredient either.
"Acidifiant : acide citrique" and "colorant (E150a)" list additives, and the class
is what the text says they are for: it is not kept as an ingredient with the
additive in it, and the additive carries it (`function`). With a colon the class
applies to the item that follows it, since the text does not say where the list
ends; in parentheses to all of them, but only when they are E numbers, or when the
class is not a word that is also an ingredient ("amidon modifié (maïs)" is
cornstarch). A class with nothing after it is read as any word is. An E number
written next to a name, in either order ("acide citrique (E330)", "E330 (acide
citrique)"), is that additive's code (`code`), not one of its parts.

A note in parentheses, such as "(origine : Italie)" or "(bio)", says nothing of
what an ingredient is made of and is ignored wherever it stands, so that the
parentheses that do list its parts are read whether it comes before them or not:

    Gnocchi (origine : Italie) [semoule, pomme de terre 19,4 %]
        ->  gnocchi: semoule, pomme de terre (19,4 %)

So is an origin written without the word: parentheses that hold nothing but
countries, as in "Pâte cuite 60,5 % (Allemagne) [eau, semoule]" or "(UE/non UE)". Only
the countries of the closed list _ORIGINS count, and only when they are all the
parentheses say: a country is not a part of the ingredient, and read as one it hid
the brackets that follow.

So is an allergen declaration: parentheses that hold nothing but allergens, as in
"semoule de blé (gluten)", "lécithines (soja)" or "(contient lait)". An allergen
is a mention of what an ingredient may cause, not one of its parts. Only the
allergens the regulation lists count (_ALLERGENS), and only when they are all
the parentheses say: "(lait écrémé)" and "(blé, eau)" list parts, and are read.

A text can also have been read badly from the label, by whoever entered it or by
the software that did: a bracket closed by a parenthesis, a letter taken for a
digit, the nutrition table or an address caught in the list, a percentage on its
own (after a comma, or in parentheses with no name before them). Nothing is done to
repair it: guessing what was meant would put invented ingredients in a product.
read_label says so and reads nothing, and the text is corrected where it comes
from. Its absence of warnings is no proof either: a word that is missing
altogether cannot be seen from the text.

Percentages that add up to more than 100 are only a warning: the label itself may
say so, and the ingredients are read as they are.

Where the ingredients were read is told too (LabelReading.used): the places of the
text, as (start, end) positions in it, that make up the names and the percentages,
and no others. It is for showing a person what the reading made of the text. When it
is wrong, the person says which places are not ingredients (`ignored`), and the text
is read as if they were not there. That is all they can do, take places out: a
reading is still the label's words, and nothing is added to it or repaired.
"""

import re
import unicodedata
from collections.abc import Iterable
from decimal import Decimal
from decimal import InvalidOperation
from typing import NamedTuple

from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _

from opennutrilab.products.services.vitamins import HEADINGS
from opennutrilab.products.services.vitamins import vitamin_called
from opennutrilab.products.services.vitamins import vitamin_nutrient


class LabelItem(NamedTuple):
    name: str
    percentage: Decimal | None = None
    parts: tuple["LabelItem", ...] = ()
    # The functional class a heading gave it ("acidifiant : ..."), as an
    # Additive.Function value, and the E number written next to its name.
    function: str = ""
    code: str = ""


class Problem(TextChoices):
    """
    What looks wrong in a text. The label carries "%(detail)s" where there is
    one. All stop the reading but MISSING (there is nothing to read) and
    PERCENT_SUM (the text is read, and is said to be inconsistent).
    """

    MISSING = "missing", _("There is no ingredient list.")
    NOTHING_READ = "nothing_read", _("No ingredient could be read from the list.")
    UNBALANCED = (
        "unbalanced",
        _("Parentheses or brackets that do not match: %(detail)s"),
    )
    GARBLED = "garbled", _("Characters or words that look badly read: %(detail)s")
    OTHER_TEXT = (
        "other_text",
        _("Text that does not belong to a list of ingredients: %(detail)s"),
    )
    LONG_NAME = "long_name", _("An ingredient that is a whole sentence: %(detail)s")
    SHORT_NAME = "short_name", _("An ingredient of one or two letters: %(detail)s")
    EMPTY_ITEM = "empty_item", _("An empty place between two commas.")
    NAMELESS_PERCENT = (
        "nameless_percent",
        _("A percentage with no ingredient name: %(detail)s"),
    )
    NOT_A_LIST = (
        "not_a_list",
        _("A long text with no separator, read as a single ingredient."),
    )
    PERCENT_SUM = (
        "percent_sum",
        _("The percentages add up to more than 100: %(detail)s"),
    )


# Only these leave the ingredients read.
_NOT_BLOCKING = frozenset({Problem.MISSING, Problem.PERCENT_SUM})


class LabelWarning(NamedTuple):
    problem: Problem
    detail: str = ""

    def message(self) -> str:
        return str(self.problem.label) % {"detail": self.detail}

    @property
    def stops_reading(self) -> bool:
        return self.problem not in _NOT_BLOCKING


# A place in the text: where it starts, and where it ends (not in it).
Span = tuple[int, int]


class LabelReading(NamedTuple):
    """The ingredients read, and the warnings. A text that looks badly read gives no
    ingredients at all, and says why. `used` is where in the text they were read from,
    in order, without overlap (see the module's docstring)."""

    items: list[LabelItem]
    warnings: list[LabelWarning]
    used: tuple[Span, ...] = ()


# What a label puts before its list, and the statements it puts after.
_LEADING_TITLE = re.compile(
    r"^\s*(?:ingr[ée]dients?|ingredients?|zutaten|ingredienti|ingredientes)"
    r"\s*[:\uff1a]\s*",
    re.IGNORECASE,
)
_STATEMENT = re.compile(
    r"\b(?:peut contenir|peuvent contenir|pourrait contenir"
    r"|traces? (?:[ée]ventuelles? )?d[e']"
    r"|may contain|can contain|might contain|puede contener|puo contenere|può contenere"
    r"|kann spuren|allerg[èe]nes?|allergens?)\b",
    re.IGNORECASE,
)
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")

# "31 %", "1,4%", "min. 31 %": the number is what counts.
_PERCENT = re.compile(
    r"(?:\b(?:min|max|minimum|maximum|soit|environ)\.?\s*)?"
    r"(?<![\d.,])(\d{1,3}(?:[.,]\d+)?)\s*%",
    re.IGNORECASE,
)
# A percentage and nothing else but the words that qualify it. Strict on purpose:
# it is used to tell that a percentage has no name, which stops the reading, so
# "sel 5 %" must not pass for one.
_BARE_PERCENT = re.compile(
    r"^\W*(?:(?:min|max|minimum|maximum|soit|environ)\.?\s*)?"
    r"\d{1,3}(?:[.,]\d+)?\s*%\W*$",
    re.IGNORECASE,
)
# The 14 allergens of Regulation (EU) 1169/2011, Annex II, with the words labels
# give them, in French and in English: no accents, "oe" for the ligature, and the
# plural next to the singular (see _folded).
_ALLERGENS = frozenset(
    {
        # Cereals containing gluten.
        "gluten", "ble", "seigle", "orge", "avoine", "epeautre", "kamut",
        "cereales contenant du gluten", "cereales contenant gluten",
        "wheat", "rye", "barley", "oat", "oats", "spelt",
        "cereals containing gluten",
        # Crustaceans, eggs, fish, peanuts, soya, milk.
        "crustace", "crustaces", "crustacean", "crustaceans",
        "oeuf", "oeufs", "egg", "eggs",
        "poisson", "poissons", "fish",
        "arachide", "arachides", "cacahuete", "cacahuetes", "peanut", "peanuts",
        "soja", "soya", "soy", "soybean", "soybeans",
        "lait", "lactose", "milk",
        # Tree nuts.
        "fruits a coque", "fruit a coque", "nuts", "tree nuts",
        "amande", "amandes", "almond", "almonds",
        "noisette", "noisettes", "hazelnut", "hazelnuts",
        "noix", "walnut", "walnuts",
        "noix de cajou", "cashew", "cashews",
        "noix de pecan", "pecan", "pecans",
        "noix du bresil", "brazil nuts",
        "pistache", "pistaches", "pistachio", "pistachios",
        "noix de macadamia", "noix du queensland", "macadamia",
        # The others.
        "celeri", "celery", "moutarde", "mustard",
        "sesame", "graines de sesame", "sesame seeds",
        "sulfite", "sulfites", "sulphite", "sulphites", "anhydride sulfureux",
        "dioxyde de soufre", "so2", "sulphur dioxide", "sulfur dioxide",
        "lupin", "lupine",
        "mollusque", "mollusques", "mollusc", "molluscs", "mollusk", "mollusks",
    }
)  # fmt: skip
# "contient du lait", "contains milk": what introduces an allergen declaration.
_ALLERGEN_INTRO = re.compile(
    r"^(?:contient|contiennent|contains|allergenes?|allergens?)\b\s*:?\s*"
    r"(?:(?:du|de la|de l'|des|de|d')\s*)?"
)
_ALLERGEN_SEPARATOR = re.compile(
    r"\s*(?:[,;/]|(?<=\s)[-\u2013\u2014](?=\s)|\bet\b|\band\b|\bou\b|\bor\b)\s*"
)
_NOTE = re.compile(
    r"^\W*(?:bio|biologiques?|organic|origine\b.*|d'origine\b.*|origin\b.*"
    r"|issus?\b.*)\W*$",
    re.IGNORECASE,
)
# The countries a label gives as the origin of an ingredient without saying "origine":
# "Pâte cuite (Allemagne)". Folded (see _folded) with the hyphens as spaces, in French
# and in English. A word that is also a food is left out, since "(turkey)" is a meat
# and "(chili)" a pepper: "Turkey", "Chile" and "Chili" are not here.
_ORIGINS = frozenset(
    {
        # Blocs.
        "ue", "union europeenne", "hors ue", "non ue", "eu", "european union",
        "non eu", "outside eu", "uk", "usa",
        # Europe.
        "france", "allemagne", "germany", "italie", "italy", "espagne", "spain",
        "portugal", "belgique", "belgium", "pays bas", "netherlands", "holland",
        "luxembourg", "irlande", "ireland", "royaume uni", "united kingdom",
        "suisse", "switzerland", "autriche", "austria", "danemark", "denmark",
        "suede", "sweden", "norvege", "norway", "finlande", "finland", "islande",
        "iceland", "pologne", "poland", "republique tcheque", "czech republic",
        "czechia", "slovaquie", "slovakia", "slovenie", "slovenia", "hongrie",
        "hungary", "roumanie", "romania", "bulgarie", "bulgaria", "croatie",
        "croatia", "serbie", "serbia", "grece", "greece", "chypre", "cyprus",
        "malte", "malta", "estonie", "estonia", "lettonie", "latvia", "lituanie",
        "lithuania", "ukraine", "russie", "russia", "albanie", "albania",
        # Africa and the Middle East.
        "maroc", "morocco", "tunisie", "tunisia", "algerie", "algeria", "egypte",
        "egypt", "senegal", "cote d'ivoire", "ivory coast", "ghana", "nigeria",
        "cameroun", "cameroon", "madagascar", "kenya", "ethiopie", "ethiopia",
        "tanzanie", "tanzania", "afrique du sud", "south africa", "israel",
        "liban", "lebanon", "iran", "jordanie", "jordan",
        # Asia and Oceania.
        "chine", "china", "japon", "japan", "inde", "india", "pakistan",
        "thailande", "thailand", "vietnam", "viet nam", "cambodge", "cambodia",
        "laos", "indonesie", "indonesia", "malaisie", "malaysia", "philippines",
        "sri lanka", "coree du sud", "south korea", "turquie", "australie",
        "australia", "nouvelle zelande", "new zealand",
        # The Americas.
        "canada", "etats unis", "united states", "mexique", "mexico", "bresil",
        "brazil", "argentine", "argentina", "perou", "peru", "colombie",
        "colombia", "equateur", "ecuador", "bolivie", "bolivia", "uruguay",
        "paraguay", "cuba", "costa rica", "guatemala", "honduras",
    }
)  # fmt: skip
# Words that introduce what follows rather than name it: "(dont sucre 5 %)".
_INTRO = re.compile(
    r"^(?:dont|including|of which|davon|di cui|de los cuales"
    r"|contient|contains|contiene|enth[äa]lt)\s+",
    re.IGNORECASE,
)
_ORGANIC = re.compile(
    r"\b(?:bio|biologiques?|organic|biologic[oa]s?|ecol[óo]gic[oa]s?)\b", re.IGNORECASE
)
# The functional classes of additives, as the words a label uses for them, folded
# (see _folded), the plural next to the singular. The values are those of
# Additive.Function (a test keeps them together).
_CLASS_WORDS = {
    "acid": (
        "acidifiant", "acidifiants", "acidulant", "acidulants",
        "acidifier", "acidifiers", "acid", "acids",
    ),
    "acidity_regulator": (
        "correcteur d'acidite", "correcteurs d'acidite",
        "regulateur d'acidite", "regulateurs d'acidite",
        "acidity regulator", "acidity regulators",
    ),
    "anti_caking_agent": (
        "anti-agglomerant", "anti-agglomerants", "antiagglomerant",
        "antiagglomerants", "agent anti-agglomerant", "agents anti-agglomerants",
        "anti-caking agent", "anti-caking agents", "anticaking agent",
        "anticaking agents",
    ),
    "anti_foaming_agent": (
        "antimousse", "antimousses", "anti-mousse", "anti-mousses",
        "anti-foaming agent", "anti-foaming agents", "antifoaming agent",
        "antifoaming agents",
    ),
    "antioxidant": ("antioxydant", "antioxydants", "antioxidant", "antioxidants"),
    "bulking_agent": (
        "agent de charge", "agents de charge", "bulking agent", "bulking agents",
    ),
    "carrier": ("support", "supports", "carrier", "carriers"),
    "colour": (
        "colorant", "colorants", "colour", "colours", "color", "colors",
        "colorante", "colorantes",
    ),
    "emulsifier": (
        "emulsifiant", "emulsifiants", "emulsifier", "emulsifiers", "emulsionante",
        "emulsionantes",
    ),
    "emulsifying_salt": (
        "sel de fonte", "sels de fonte", "emulsifying salt", "emulsifying salts",
    ),
    "firming_agent": (
        "affermissant", "affermissants", "firming agent", "firming agents",
    ),
    "flavour_enhancer": (
        "exhausteur de gout", "exhausteurs de gout", "flavour enhancer",
        "flavour enhancers", "flavor enhancer", "flavor enhancers",
    ),
    "flour_treatment_agent": (
        "agent de traitement de la farine", "agents de traitement de la farine",
        "flour treatment agent", "flour treatment agents",
    ),
    "foaming_agent": (
        "agent moussant", "agents moussants", "foaming agent", "foaming agents",
    ),
    "gelling_agent": ("gelifiant", "gelifiants", "gelling agent", "gelling agents"),
    "glazing_agent": (
        "agent d'enrobage", "agents d'enrobage", "agent de glacage",
        "agents de glacage", "glazing agent", "glazing agents",
    ),
    "humectant": ("humectant", "humectants"),
    "modified_starch": (
        "amidon modifie", "amidons modifies", "modified starch", "modified starches",
    ),
    "packaging_gas": (
        "gaz d'emballage", "packaging gas", "packaging gases",
    ),
    "preservative": (
        "conservateur", "conservateurs", "preservative", "preservatives",
        "conservante", "conservantes",
    ),
    "propellant": ("gaz propulseur", "propellant", "propellants", "propellent gas"),
    "raising_agent": (
        "poudre a lever", "poudres a lever", "agent levant", "agents levants",
        "raising agent", "raising agents",
    ),
    "sequestrant": ("sequestrant", "sequestrants"),
    "stabiliser": (
        "stabilisant", "stabilisants", "stabiliser", "stabilisers", "stabilizer",
        "stabilizers",
    ),
    "sweetener": ("edulcorant", "edulcorants", "sweetener", "sweeteners"),
    "thickener": (
        "epaississant", "epaississants", "thickener", "thickeners",
        "thickening agent", "thickening agents",
    ),
}  # fmt: skip
_CLASS_OF = {
    word: function for function, words in _CLASS_WORDS.items() for word in words
}
# Classes whose word is also what an ingredient is called ("amidon modifié (maïs)",
# "poudre à lever"): their parentheses are read as additives only when E numbers.
_ALSO_INGREDIENTS = frozenset({"modified_starch", "raising_agent", "carrier"})
# An E number as a label writes it: "E330", "E 330", "e330", "E160a", "E1001(ii)".
# One letter may stand apart ("E 160 a"); a longer suffix is attached to the number
# ("E160aiii", "E450viii"), so that "E330 acid" is not a code.
_E_NUMBER = re.compile(
    r"e\s?-?(\d{3,4})(?:\s?([a-z])|([a-z]{1,4}))?\s?(?:\(([ivx]+)\))?",
    re.IGNORECASE,
)
# The words of the allergens that a label prints in capitals without their accent,
# as the lower case word they are. Only those that are French and nothing else:
# "SESAME", "CACAHUETE" and "CEREALES" are as well English and Spanish words, which
# have no accent, so they are left as written.
_CAPITALS_ACCENTED = {
    "BLE": "blé",
    "EPEAUTRE": "épeautre",
    "OEUF": "œuf",
    "OEUFS": "œufs",
    "CRUSTACE": "crustacé",
    "CRUSTACES": "crustacés",
    "CELERI": "céleri",
    "BRESIL": "brésil",
}
_CAPITAL_WORD = re.compile(r"\b[A-Z]{2,}\b")
# What takes the place of a character a person ignored: white space, but one that
# tells the place is empty because they emptied it, not because the label has two
# commas in a row.
_IGNORED = "\u2008"
_MARK_CHARS = "*†‡°_"
_MARKS = str.maketrans("", "", _MARK_CHARS)
_BRACKETS = str.maketrans("[]{}", "()()")
_MAX_DECIMALS = 2
# What a name is trimmed of: punctuation, dashes, quotes.
_DASHES = "-\u2013\u2014"
_EDGE = f" .,;:{_DASHES}'\""

# Signs of a text that was read badly, or that is not only a list.
_GARBLE_CHARS = "\ufffd|¦~^@#§\\"
_OTHER_TEXT = re.compile(
    r"\b(?:kj|kcal|valeurs? nutritionnelles?|valeur [ée]nerg[ée]tique"
    r"|[àa] consommer|[àa] conserver|dlc|dluo|fabriqu[ée]e?s?|distribu[ée]e?s?"
    r"|t[ée]l|mode d'emploi|nutrition facts|best before|store in)\b"
    r"|www\.|https?:",
    re.IGNORECASE,
)
# Letters on both sides of a digit ("S0JA", "fari1e"), but not "oméga-3" or "B6".
_DIGIT_IN_WORD = re.compile(r"(?=\S*[^\W\d_]{2})(?=\S*\d)\S+")
_KNOWN_WITH_DIGITS = re.compile(
    r"o?m[ée]ga-?\d[\d-]*|[a-z]-?\d+[a-z]?|e-?\d+[a-z]{0,4}", re.IGNORECASE
)
_PAIRS = {")": "(", "]": "[", "}": "{"}
_LONG_NAME_WORDS = 12
_NOT_A_LIST_LENGTH = 150
_PERCENT_SUM_LIMIT = Decimal("100.5")


def parse_label(text: str) -> list[LabelItem]:
    """The ingredients of a label's text, as a tree, in the order it lists them."""
    return read_label(text).items


def read_label(text: str | None, ignored: Iterable[Span] = ()) -> LabelReading:
    """
    The ingredients of a label's text, and what looks wrong in the text.

    `ignored` are places of the text to read it without, as a person marked them
    (positions in `text`): they are blank to the reading, which then does not see
    what is wrong in them either.
    """
    if text is None or not text.strip():
        return LabelReading([], [LabelWarning(Problem.MISSING)])
    written, origin = _clean(text)
    written = _blank(written, origin, ignored, len(text))
    # Same length, so the same positions: the list is read with one kind of
    # bracket, and checked with the ones the label has.
    part = _list_part(written.translate(_BRACKETS))
    used: list[Span] = []
    items = _parse_list(part, 0, used)
    warnings = _warnings(part, written[: len(part)], items)
    if any(warning.stops_reading for warning in warnings):
        return LabelReading([], warnings)
    return LabelReading(items, warnings, _in_text(used, origin, text))


def _clean(text: str) -> tuple[str, list[int]]:
    """
    `text` as it is read, and for each of its characters where it is in `text`
    (what is taken out has no place in the result, and so is not there to find).
    """
    origin = list(range(len(text)))
    text, origin = _without(text, origin, [m.span() for m in _TAG.finditer(text)])
    text = text.replace("\xa0", " ").replace("\u2019", "'")
    text, origin = _without(text, origin, [m.span() for m in re.finditer("\r", text)])
    trailing = len(text.rstrip())
    edges = [(0, len(text) - len(text.lstrip())), (trailing, len(text))]
    text, origin = _without(text, origin, edges)
    if (title := _LEADING_TITLE.match(text)) is not None:
        text, origin = _without(text, origin, [title.span()])
    return text, origin


def _without(
    text: str, origin: list[int], spans: Iterable[Span]
) -> tuple[str, list[int]]:
    """`text` without the characters in `spans`, and `origin` without theirs."""
    gone = {index for start, end in spans for index in range(start, end)}
    kept = [index for index in range(len(text)) if index not in gone]
    return "".join(text[index] for index in kept), [origin[index] for index in kept]


def _blank(text: str, origin: list[int], ignored: Iterable[Span], size: int) -> str:
    """
    `text` with a blank (_IGNORED) for each character the person ignored: same
    length. A blank is white space to the reading, whatever it looks at.
    """
    gone = {
        index
        for start, end in ignored
        for index in range(max(0, start), min(end, size))
    }
    if not gone:
        return text
    return "".join(
        _IGNORED if origin[index] in gone else char for index, char in enumerate(text)
    )


def _in_text(used: list[Span], origin: list[int], text: str) -> tuple[Span, ...]:
    """
    The places `used` has in what was read, as places in `text`: in order, the
    ones that touch or are parted by nothing but white space made one.
    """
    placed = sorted((origin[start], origin[end - 1] + 1) for start, end in used)
    merged: list[Span] = []
    for start, end in placed:
        if merged and not text[merged[-1][1] : start].strip():
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _list_part(text: str) -> str:
    """The text up to where the list ends: its sentence, or a statement."""
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            if char == "." and _ends_sentence(text, index):
                return text[:index]
            if char == "\n" and _ends_line(text, index):
                return text[:index]
            if char in "pPtTmMkKaAdD" and _statement_at(text, index):
                return text[:index]
    return text


def _ends_sentence(text: str, index: int) -> bool:
    before = text[index - 1] if index else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    return not (before.isdigit() and after.isdigit()) and (
        after == "" or after.isspace()
    )


def _ends_line(text: str, index: int) -> bool:
    before = text[:index].rstrip()
    after = text[index:].lstrip()
    return (
        bool(before)
        and bool(after)
        and not _separates(text, len(before) - 1)
        and after[0].isupper()
    )


def _statement_at(text: str, index: int) -> bool:
    previous = text[index - 1] if index else " "
    return not previous.isalnum() and bool(_STATEMENT.match(text, index))


def e_number(name: str) -> str:
    """
    The code of an additive when the name is one, as it is stored: "E330" for
    "e 330", "E1001II" for "E1001(ii)". Blank when the name is not an E number,
    which is all a word with other letters or fewer digits is.
    """
    found = _E_NUMBER.fullmatch(" ".join(name.split()))
    if found is None:
        return ""
    digits, spaced, attached, roman = found.groups(default="")
    return f"E{digits}{spaced or attached}{roman}".upper()


def _parse_list(text: str, at: int, used: list[Span]) -> list[LabelItem]:
    """
    The ingredients of `text`, which starts at `at` in what is read. The places they
    are read from are added to `used`.
    """
    return [
        item
        for start, piece in _pieces(text)
        for item in _parse_items(piece, at + start, used)
    ]


def _pieces(text: str) -> list[tuple[int, str]]:
    """
    The pieces between the separators (see _separates) that are not in parentheses.
    """
    pieces: list[tuple[int, str]] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and _separates(text, index):
            pieces.append((start, text[start:index]))
            start = index + 1
    pieces.append((start, text[start:]))
    return pieces


def _split(text: str) -> list[str]:
    return [piece for _start, piece in _pieces(text)]


def _separates(text: str, index: int) -> bool:
    """
    Whether the character at `index` parts two ingredients: a semicolon, a comma
    that is not a decimal one ("7,4 %"), or a dash on its own between white space
    ("sucre - sel"). A dash inside a word is the word's ("oméga-3", "demi-écrémé").
    """
    char = text[index]
    if char in _DASHES:
        before = text[index - 1] if index else ""
        after = text[index + 1] if index + 1 < len(text) else ""
        return before.isspace() and after.isspace()
    return char == ";" or (char == "," and not _decimal_comma(text, index))


def _has_separator(text: str) -> bool:
    return any(_separates(text, index) for index in range(len(text)))


def _decimal_comma(text: str, index: int) -> bool:
    """Whether the comma at `index` is a decimal one, as in "7,4 %"."""
    before = text[index - 1] if index else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    return text[index] == "," and before.isdigit() and after.isdigit()


def _matching(text: str, open_at: int) -> int:
    """Where the parenthesis opened at `open_at` closes (the end if it does not)."""
    depth = 0
    for index in range(open_at, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def _class_of(heading: str) -> str:
    """The Additive.Function a heading names, "" if it names none."""
    return _CLASS_OF.get(_folded(_name(heading) or ""), "")


def _parse_items(raw: str, at: int, used: list[Span]) -> list[LabelItem]:
    """
    What one piece of the list says: an ingredient, or the additives of a class.
    The piece starts at `at` in what is read; where its ingredients are read from
    is added to `used`.
    """
    noted, notes = _without_notes(raw)
    text = _percent_beside(noted)
    group = _split_group(text)
    head, inner, tail = group.head, group.inner, group.tail
    inner_at, tail_at = at + group.inner_at, at + group.tail_at
    if ":" in head:
        title, _colon, after = head.partition(":")
        after_at = len(title) + 1
        # "émulsifiants : lécithines (soja)": the heading names it, the rest is in it.
        if inner and after.strip():
            listed, listed_at = text[after_at : group.tail_at], at + after_at
        elif after:
            listed, listed_at = after, at + after_at
        else:
            listed, listed_at = inner, inner_at
        function = _class_of(title)
        if (
            function
            and listed.strip()
            and not (_percentage(title) or _percentage(tail))
        ):
            # "acidifiant : acide citrique": the class is what the item that
            # follows is for, and is not an ingredient.
            return _under_class(function, listed, listed_at, used)
        head, inner, inner_at = title, listed, listed_at
    elif (
        (function := _class_of(head))
        and inner.strip()
        and not (_percentage(head) or _percentage(tail))
    ):
        # "colorant (E150a)": the class and what it is for, in parentheses.
        read_from: list[Span] = []
        listed_items = _parse_list(inner, inner_at, read_from)
        if listed_items and (
            function not in _ALSO_INGREDIENTS
            or all(e_number(item.name) for item in listed_items)
        ):
            used.extend(read_from)
            return [item._replace(function=function) for item in listed_items]

    if (vitamins := _vitamins_listed(head, inner, inner_at, tail, used)) is not None:
        return vitamins
    name = _name(head)
    if name is None:
        return []
    percentage = _percentage_read(head, at, tail, tail_at, used)
    used.extend(_name_spans(head, at, notes))
    return [_with_code(name, percentage, inner, inner_at, used)]


def _percentage_read(
    head: str, at: int, tail: str, tail_at: int, used: list[Span]
) -> Decimal | None:
    """The percentage written in the head of a piece, else after its parentheses."""
    percentage = _percentage(head)
    if percentage:
        used.extend(_percent_span(head, at))
        return percentage
    percentage = _percentage(tail)
    if percentage:
        used.extend(_percent_span(tail, tail_at))
    return percentage


def _under_class(
    function: str, listed: str, at: int, used: list[Span]
) -> list[LabelItem]:
    return [item._replace(function=function) for item in _parse_list(listed, at, used)]


def _vitamins_listed(
    head: str, inner: str, inner_at: int, tail: str, used: list[Span]
) -> list[LabelItem] | None:
    """
    The vitamins a heading lists, "vitamine" followed by their letters in
    parentheses ("Vitamines (E, PP, B6)") or after a colon: one ingredient each,
    "vitamine e", "vitamine pp", "vitamine b6", and no "vitamines" with letters as
    its parts. None when it is not that: another heading, a percentage, or a name
    in it that is no vitamin of the closed list (see vitamins), and the text is then
    read as any is.
    """
    heading = _name(head) or ""
    if (
        _folded(heading) not in HEADINGS
        or not inner.strip()
        or _percentage(head)
        or _percentage(tail)
    ):
        return None
    read_from: list[Span] = []
    listed = _parse_list(inner, inner_at, read_from)
    called = [vitamin_called(item.name, heading) for item in listed]
    if not listed or not all(called) or any(item.parts for item in listed):
        return None
    used.extend(read_from)
    return [item._replace(name=name) for item, name in zip(listed, called, strict=True)]


def _with_code(
    name: str, percentage: Decimal | None, inner: str, inner_at: int, used: list[Span]
) -> LabelItem:
    """
    The ingredient `name` with what is in its parentheses as its parts, or as its
    code when that is an E number: "acide citrique (E330)" is one additive, and so
    is "E330 (acide citrique)", which is named by what is in the parentheses.
    """
    if not inner.strip():
        return LabelItem(name, percentage)
    code = e_number(_name(inner) or "")
    if code and not e_number(name):
        used.extend(_name_spans(inner, inner_at, ()))
        return LabelItem(name, percentage, code=code)
    named = _name(inner)
    if (
        e_number(name)
        and named is not None
        and not _has_separator(inner)
        and not any(char.isdigit() for char in inner)
    ):
        used.extend(_name_spans(inner, inner_at, ()))
        return LabelItem(named, percentage, code=e_number(name))
    # "acide ascorbique (vitamine C)", "vitamine D (cholécalciférol)": the same
    # vitamin said twice, not one made of the other.
    if (
        named is not None
        and vitamin_nutrient(name)
        and vitamin_nutrient(named)
        and not _has_separator(inner)
    ):
        used.extend(_name_spans(inner, inner_at, ()))
        return LabelItem(name, percentage)
    return LabelItem(name, percentage, tuple(_parse_list(inner, inner_at, used)))


def _folded(text: str) -> str:
    """Lower case, no accents, no marks: "BLÉ*" and "ble" are the same word."""
    text = unicodedata.normalize("NFD", text.translate(_MARKS).lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(text.replace("\u0153", "oe").replace("\u00e6", "ae").split())


def _is_allergen_declaration(inner: str) -> bool:
    """Whether the parentheses hold nothing but allergens: "(gluten)", "(blé, lait)"."""
    words = _ALLERGEN_INTRO.sub("", _folded(inner))
    terms = _ALLERGEN_SEPARATOR.split(words)
    return all(term in _ALLERGENS for term in terms)


def _is_origin(inner: str) -> bool:
    """Whether the parentheses hold nothing but countries: "(Allemagne)", "(UE)"."""
    terms = _ALLERGEN_SEPARATOR.split(_folded(inner))
    return all(term.replace("-", " ") in _ORIGINS for term in terms)


def _without_notes(text: str) -> tuple[str, list[Span]]:
    """
    `text` without its notes in parentheses ("(origine : Italie)", "(bio)"), its
    origins ("(Allemagne)") and its allergen declarations ("(gluten)", "(contient
    lait)"), and where they were. They are blank, so that the positions are the same.

    Only the first group is read as the parts of an ingredient, and what follows
    it only for a percentage, so a note ahead of the parentheses that do list the
    parts would hide them, and put their percentage on the ingredient. The notes
    inside a group are left to the reading of that group.
    """
    kept: list[str] = []
    notes: list[Span] = []
    index = 0
    while (open_at := text.find("(", index)) != -1:
        close_at = _matching(text, open_at)
        inner = text[open_at + 1 : close_at]
        is_note = (
            _NOTE.match(inner) is not None
            or _is_origin(inner)
            or _is_allergen_declaration(inner)
        )
        end = min(close_at + 1, len(text))
        kept.append(text[index:open_at])
        kept.append(" " * (end - open_at) if is_note else text[open_at:end])
        if is_note:
            notes.append((open_at, end))
        index = end
    kept.append(text[index:])
    return "".join(kept), notes


class _Group(NamedTuple):
    """A piece cut at its first parentheses, and where the two parts after the
    head start in it."""

    head: str
    inner: str
    tail: str
    inner_at: int
    tail_at: int


def _split_group(raw: str) -> _Group:
    open_at = raw.find("(")
    if open_at == -1:
        return _Group(raw, "", "", len(raw), len(raw))
    close_at = _matching(raw, open_at)
    return _Group(
        raw[:open_at],
        raw[open_at + 1 : close_at],
        raw[close_at + 1 :],
        open_at + 1,
        close_at + 1,
    )


def _split_parenthesis(raw: str) -> tuple[str, str, str]:
    group = _split_group(raw)
    return group.head, group.inner, group.tail


def _percent_beside(text: str) -> str:
    """
    `text` with a percentage that is alone in its parentheses written next to the
    name before them: "Dattes (38 %)" is "Dattes 38 %", and "Dattes (38 %) (dattes,
    riz)" is "Dattes 38 % (dattes, riz)", where the parts are read as any are. The
    parentheses are blank, so that the positions are the same.

    Only when it is plain whose percentage it is: a name before the parentheses,
    which has no percentage of its own, and none after them. "Dattes 7 % (7 %)"
    and "(7 %)" are left as they are, for what they are: a percentage with no name.
    """
    group = _split_group(text)
    head, inner, tail = group.head, group.inner, group.tail
    if (
        _BARE_PERCENT.match(inner)
        and _percentage(inner) is not None
        and _name(head) is not None
        and not _PERCENT.search(head)
        and not _PERCENT.search(tail)
    ):
        close_at = group.tail_at - 1
        closed = text[close_at : close_at + 1] == ")"
        return f"{head} {inner}{' ' if closed else ''}{tail}"
    return text


def _percentage(text: str) -> Decimal | None:
    """The first percentage in `text`, if it can be kept as it is written."""
    match = _PERCENT.search(text)
    if match is None:
        return None
    try:
        value = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    exponent = value.as_tuple().exponent
    decimals = -exponent if isinstance(exponent, int) else 0
    if value > 100 or decimals > _MAX_DECIMALS:  # noqa: PLR2004
        return None
    return value


def _name(text: str) -> str | None:
    text = _PERCENT.sub(" ", text).translate(_MARKS)
    text = _ORGANIC.sub(" ", text)
    text = " ".join(text.split()).strip(_EDGE)
    while (match := _INTRO.match(text)) is not None:
        text = text[match.end() :].strip()
    name = _CAPITAL_WORD.sub(_accent_back, text.strip(_EDGE)).lower()
    return name if any(char.isalpha() for char in name) else None


def _accent_back(word: re.Match[str]) -> str:
    return _CAPITALS_ACCENTED.get(word.group(0), word.group(0))


# ----------------------------------------------------------------------------
# Where in the text is what was read?
# ----------------------------------------------------------------------------
def _blanks(found: re.Match[str]) -> str:
    return " " * len(found.group(0))


def _percent_span(text: str, at: int) -> list[Span]:
    """Where the percentage `_percentage` keeps is in `text`, which starts at `at`."""
    found = _PERCENT.search(text)
    if found is None or _percentage(text) is None:
        return []
    return [(at + found.start(), at + found.end())]


def _name_spans(text: str, at: int, notes: Iterable[Span]) -> list[Span]:
    """
    Where in `text`, which starts at `at`, is the name `_name` makes of it: from its
    first character to its last, less the notes between, and the marks stuck to
    it ("blé*", "_lait_"). Nothing for a text that makes no name.

    It does what `_name` does on blanks rather than on nothing, so that the
    positions stay. A test keeps the two together.
    """
    if _name(text) is None:
        return []
    kept = _ORGANIC.sub(_blanks, _PERCENT.sub(_blanks, text))
    start, end = _trimmed(kept, 0, len(kept))
    while (intro := _INTRO.match(kept[start:end])) is not None:
        start, end = _trimmed(kept, start + intro.end(), end)
    while start > 0 and text[start - 1] in _MARK_CHARS:
        start -= 1
    while end < len(text) and text[end] in _MARK_CHARS:
        end += 1
    spans: list[Span] = []
    for note_start, note_end in sorted(notes):
        if note_end <= start or note_start >= end:
            continue
        spans.append((start, min(note_start, end)))
        start = max(start, note_end)
    spans.append((start, end))
    return [
        (at + a + _blank_edge(text[a:b]), at + b - _blank_edge(text[a:b][::-1]))
        for a, b in spans
        if text[a:b].strip()
    ]


def _trimmed(text: str, start: int, end: int) -> Span:
    """`start` and `end` moved inwards past what a name is trimmed of."""
    while start < end and (text[start] in _EDGE or text[start].isspace()):
        start += 1
    while end > start and (text[end - 1] in _EDGE or text[end - 1].isspace()):
        end -= 1
    return start, end


def _blank_edge(text: str) -> int:
    """How many white space characters `text` starts with."""
    return len(text) - len(text.lstrip())


# ----------------------------------------------------------------------------
# Does the text look read badly?
# ----------------------------------------------------------------------------
def _warnings(part: str, written: str, items: list[LabelItem]) -> list[LabelWarning]:
    found: list[LabelWarning] = []
    if not items:
        found.append(LabelWarning(Problem.NOTHING_READ))
    if (unbalanced := _unbalanced(written)) is not None:
        found.append(LabelWarning(Problem.UNBALANCED, unbalanced))
    found += _garbled(part)
    if (other := _OTHER_TEXT.search(part)) is not None:
        found.append(LabelWarning(Problem.OTHER_TEXT, other.group(0)))
    found += _odd_names(items)
    if len(items) == 1 and not items[0].parts and len(part) > _NOT_A_LIST_LENGTH:
        found.append(LabelWarning(Problem.NOT_A_LIST))
    if any(not piece.strip() and _IGNORED not in piece for piece in _split(part)[:-1]):
        found.append(LabelWarning(Problem.EMPTY_ITEM))
    if nameless := _nameless_percentages(part):
        found.append(LabelWarning(Problem.NAMELESS_PERCENT, ", ".join(nameless[:3])))
    total = sum((i.percentage for i in items if i.percentage is not None), Decimal(0))
    if total > _PERCENT_SUM_LIMIT:
        found.append(LabelWarning(Problem.PERCENT_SUM, f"{total} %"))
    return found


def _nameless_percentages(text: str) -> list[str]:
    """
    The places in a list that are a percentage and nothing else: "huile d'olive,
    2,3 %" (a comma between a percentage and its ingredient makes it nobody's) and
    "(7 %)" or "dattes 7 % (7 %)" (a percentage in parentheses is the one of the
    name before them, if there is one and it has none: see _percent_beside).
    Reading on would lose it, or put it where it is not, without a word.
    """
    found: list[str] = []
    for raw in _split(text):
        piece = _percent_beside(_without_notes(raw.strip())[0])
        if _BARE_PERCENT.match(piece):
            found.append(piece.strip(_EDGE + "()"))
            continue
        _head, inner, _tail = _split_parenthesis(piece)
        if inner.strip():
            found += _nameless_percentages(inner)
    return found


def _unbalanced(part: str) -> str | None:
    """The place where brackets stop matching, with what is around it."""
    stack: list[str] = []
    for index, char in enumerate(part):
        if char in "([{":
            stack.append(char)
        elif char in _PAIRS and (not stack or stack.pop() != _PAIRS[char]):
            return _around(part, index)
    return _around(part, len(part) - 1) if stack else None


def _around(text: str, index: int) -> str:
    """A few words around `index`, cut between words."""
    start, end = max(0, index - 20), index + 21
    words = text[start:end].split()
    if start > 0 and not text[start - 1].isspace():
        words = words[1:]  # The first is cut in two.
    if end < len(text) and not text[end].isspace():
        words = words[:-1]  # So is the last.
    return " ".join(words)


def _garbled(part: str) -> list[LabelWarning]:
    found: list[LabelWarning] = []
    odd = sorted({char for char in part if char in _GARBLE_CHARS})
    if odd:
        found.append(LabelWarning(Problem.GARBLED, " ".join(odd)))
    words = [
        word
        for match in _DIGIT_IN_WORD.finditer(part.replace("(", " ").replace(")", " "))
        if (word := match.group(0).strip(",;.:*%"))
        and not _KNOWN_WITH_DIGITS.fullmatch(word)
        and not word[0].isdigit()
    ]
    if words:
        found.append(LabelWarning(Problem.GARBLED, " ".join(words[:3])))
    return found


def _odd_names(items: list[LabelItem], *, root: bool = True) -> list[LabelWarning]:
    found: list[LabelWarning] = []
    for item in items:
        if len(item.name.split()) > _LONG_NAME_WORDS:
            found.append(LabelWarning(Problem.LONG_NAME, item.name[:40] + "…"))
        # An E number is short, and is a name.
        if (
            root
            and not e_number(item.name)
            and sum(char.isalpha() for char in item.name) <= 2  # noqa: PLR2004
        ):
            found.append(LabelWarning(Problem.SHORT_NAME, item.name))
        found += _odd_names(list(item.parts), root=False)
    return found
