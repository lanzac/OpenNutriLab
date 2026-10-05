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

Only what the text says is kept: no name is corrected or guessed. Names come out
in lower case, without the marks a label adds around them (the asterisk of
organic ingredients, the capitals of allergens, the word "bio"). The list ends
where the label's own sentence does, before "Peut contenir...". Labels differ,
so what cannot be read as a list (a note in parentheses, a heading) is left out
rather than turned into an ingredient, and a name that is wrong is the curator's
to see: it makes a reference to review.

A note in parentheses, such as "(origine : Italie)" or "(bio)", says nothing of
what an ingredient is made of and is ignored wherever it stands, so that the
parentheses that do list its parts are read whether it comes before them or not:

    Gnocchi (origine : Italie) [semoule, pomme de terre 19,4 %]
        ->  gnocchi: semoule, pomme de terre (19,4 %)

So is an allergen declaration: parentheses that hold nothing but allergens, as in
"semoule de blé (gluten)", "lécithines (soja)" or "(contient lait)". An allergen
is a mention of what an ingredient may cause, not one of its parts. Only the
allergens the regulation lists count (_ALLERGENS), and only when they are all
the parentheses say: "(lait écrémé)" and "(blé, eau)" list parts, and are read.

A text can also have been read badly from the label, by whoever entered it or by
the software that did: a bracket closed by a parenthesis, a letter taken for a
digit, the nutrition table or an address caught in the list, a percentage on its
own (after a comma, or in parentheses of its own). Nothing is done to
repair it: guessing what was meant would put invented ingredients in a product.
read_label says so and reads nothing, and the text is corrected where it comes
from. Its absence of warnings is no proof either: a word that is missing
altogether cannot be seen from the text.

Percentages that add up to more than 100 are only a warning: the label itself may
say so, and the ingredients are read as they are.
"""

import re
import unicodedata
from decimal import Decimal
from decimal import InvalidOperation
from typing import NamedTuple

from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _


class LabelItem(NamedTuple):
    name: str
    percentage: Decimal | None = None
    parts: tuple["LabelItem", ...] = ()


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


class LabelReading(NamedTuple):
    """The ingredients read, and the warnings. A text that looks badly read gives no
    ingredients at all, and says why."""

    items: list[LabelItem]
    warnings: list[LabelWarning]


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
_ALLERGEN_SEPARATOR = re.compile(r"\s*(?:[,;/]|\bet\b|\band\b|\bou\b|\bor\b)\s*")
_NOTE = re.compile(
    r"^\W*(?:bio|biologiques?|organic|origine\b.*|d'origine\b.*|origin\b.*"
    r"|issus?\b.*)\W*$",
    re.IGNORECASE,
)
# Words that introduce what follows rather than name it: "(dont sucre 5 %)".
_INTRO = re.compile(
    r"^(?:dont|including|of which|davon|di cui|de los cuales"
    r"|contient|contains|contiene|enth[äa]lt)\s+",
    re.IGNORECASE,
)
_ORGANIC = re.compile(
    r"\b(?:bio|biologiques?|organic|biologic[oa]s?|ecol[óo]gic[oa]s?)\b", re.IGNORECASE
)
_MARKS = str.maketrans("", "", "*†‡°_")
_BRACKETS = str.maketrans("[]{}", "()()")
_MAX_DECIMALS = 2
# What a name is trimmed of: punctuation, dashes, quotes.
_EDGE = " .,;:-\u2013\u2014'\""

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
    r"o?m[ée]ga-?\d[\d-]*|[a-z]-?\d+[a-z]?|e-?\d+[a-z]?", re.IGNORECASE
)
_PAIRS = {")": "(", "]": "[", "}": "{"}
_LONG_NAME_WORDS = 12
_NOT_A_LIST_LENGTH = 150
_PERCENT_SUM_LIMIT = Decimal("100.5")


def parse_label(text: str) -> list[LabelItem]:
    """The ingredients of a label's text, as a tree, in the order it lists them."""
    return read_label(text).items


def read_label(text: str | None) -> LabelReading:
    """The ingredients of a label's text, and what looks wrong in the text."""
    if text is None or not text.strip():
        return LabelReading([], [LabelWarning(Problem.MISSING)])
    written = _clean(text)
    # Same length, so the same positions: the list is read with one kind of
    # bracket, and checked with the ones the label has.
    part = _list_part(written.translate(_BRACKETS))
    items = _parse_list(part)
    warnings = _warnings(part, written[: len(part)], items)
    if any(warning.stops_reading for warning in warnings):
        return LabelReading([], warnings)
    return LabelReading(items, warnings)


def _clean(text: str) -> str:
    text = _TAG.sub("", text).replace("\xa0", " ")
    text = text.replace("\u2019", "'").replace("\r", "")
    return _LEADING_TITLE.sub("", text.strip())


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
    return bool(after) and before[-1:] not in ",;" and after[0].isupper()


def _statement_at(text: str, index: int) -> bool:
    previous = text[index - 1] if index else " "
    return not previous.isalnum() and bool(_STATEMENT.match(text, index))


def _parse_list(text: str) -> list[LabelItem]:
    items = (_parse_item(piece) for piece in _split(text))
    return [item for item in items if item is not None]


def _split(text: str) -> list[str]:
    """The pieces between the commas and semicolons that are not in parentheses."""
    pieces: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char in ",;" and depth == 0 and not _decimal_comma(text, index):
            pieces.append(text[start:index])
            start = index + 1
    pieces.append(text[start:])
    return pieces


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


def _parse_item(raw: str) -> LabelItem | None:
    head, inner, tail = _split_parenthesis(_without_notes(raw.strip()))
    # "émulsifiants : lécithines (soja)": the heading names it, the rest is in it.
    if ":" in head:
        head, _, after = head.partition(":")
        inner = f"{after} ({inner})" if inner and after.strip() else after or inner

    percentage = _percentage(head) or _percentage(tail)
    parts: tuple[LabelItem, ...] = ()
    if inner.strip():
        parts = tuple(_parse_list(inner))

    name = _name(head)
    if name is None:
        return None
    return LabelItem(name, percentage, parts)


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


def _without_notes(text: str) -> str:
    """
    `text` without its notes in parentheses ("(origine : Italie)", "(bio)") and its
    allergen declarations ("(gluten)", "(contient lait)").

    Only the first group is read as the parts of an ingredient, and what follows
    it only for a percentage, so a note ahead of the parentheses that do list the
    parts would hide them, and put their percentage on the ingredient. The notes
    inside a group are left to the reading of that group.
    """
    kept: list[str] = []
    index = 0
    while (open_at := text.find("(", index)) != -1:
        close_at = _matching(text, open_at)
        inner = text[open_at + 1 : close_at]
        is_note = _NOTE.match(inner) is not None or _is_allergen_declaration(inner)
        kept.append(text[index:open_at] if is_note else text[index : close_at + 1])
        index = close_at + 1
    kept.append(text[index:])
    return "".join(kept)


def _split_parenthesis(raw: str) -> tuple[str, str, str]:
    open_at = raw.find("(")
    if open_at == -1:
        return raw, "", ""
    close_at = _matching(raw, open_at)
    return raw[:open_at], raw[open_at + 1 : close_at], raw[close_at + 1 :]


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
    name = text.strip(_EDGE).lower()
    return name if any(char.isalpha() for char in name) else None


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
    if any(not piece.strip() for piece in _split(part)[:-1]):
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
    "dattes (7 %)" (a percentage is written next to the ingredient, not in
    parentheses of its own). Reading on would lose it, or put it where it is not,
    without a word.
    """
    found: list[str] = []
    for raw in _split(text):
        piece = _without_notes(raw.strip())
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
        if root and sum(char.isalpha() for char in item.name) <= 2:  # noqa: PLR2004
            found.append(LabelWarning(Problem.SHORT_NAME, item.name))
        found += _odd_names(list(item.parts), root=False)
    return found
