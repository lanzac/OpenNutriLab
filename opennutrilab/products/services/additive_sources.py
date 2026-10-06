"""
Where the additives come from: the European Commission's list, and Wikipedia for
their French names.

The list that says which additives exist is the Union list of Regulation (EC)
1333/2008, as the Commission's DG SANTE data API serves it
(`/food-additives/food-additives-list`, which needs no key): each substance with its
E number and its English name. It has no French names, and no classes. The French
names are those of the table of E numbers of the French Wikipedia page "Liste des
additifs alimentaires" (CC BY-SA 4.0), whose cell often lists several ("Acide
ascorbique, vitamine C"): the first is the name, since a label names one.

Nothing here touches the database. `build_dataset` puts the two together as the
dataset the table is loaded from (data/additives.json, see additive_sync), which is
what the `regenerate_additives` command writes.

An entry of the list that has no usable E number is left out and said: a substance
that was removed from the list, one that has no number yet, a placeholder ("E XXX",
".."), a range ("E 334 - 337"). The portal's data was typed by hand: names can carry
the HTML of the page they were typed in, and "Carbomer" is written "1210".
"""

import html
import re
from html.parser import HTMLParser
from typing import Any
from typing import NamedTuple
from typing import cast

import requests

from opennutrilab.products.services.label_parser import e_number

UNION_LIST_URL = (
    "https://api.datalake.sante.service.ec.europa.eu/food-additives/food-additives-list"
)
UNION_LIST_PARAMS = {"format": "json", "api-version": "v2.0"}
WIKIPEDIA_API_URL = "https://fr.wikipedia.org/w/api.php"
WIKIPEDIA_URL = "https://fr.wikipedia.org/wiki/"
WIKIPEDIA_PAGE = "Liste des additifs alimentaires"
# Both ask for a User-Agent that says who is calling.
HEADERS = {
    "User-Agent": "OpenNutriLab/0.1.0 (https://github.com/lanzac/OpenNutriLab)",
    "Accept": "application/json",
    # The Commission's gateway asks for it on a GET.
    "Content-Type": "application/json",
}
TIMEOUT = 120
# Pages of the list to follow at most: it has about 400 entries, 100 to a page.
MAX_PAGES = 50
MAX_NAME = 255

_TAG = re.compile(r"<[^>]+>")
_E_ROW = re.compile(r"^E\s?\d", re.IGNORECASE)
# Where a name ends in a cell that lists several: "A, B", "A ou B", "A [note]".
_FIRST_NAME_END = re.compile(r",\s|\s+ou\s+|\s*\[")
_TRAILING_PARENTHESIS = re.compile(r"\s*\([^()]*\)\s*$")
# What a name is trimmed of: punctuation, and the stray quote the list has.
_EDGE = " ,;.:\u2019'\"\u00a0"


class AdditiveSourceError(Exception):
    """A source could not be read."""


class UnionAdditive(NamedTuple):
    # The entry in the Commission's portal ("POL-FAD-IMPORT-3099").
    ref: str
    code: str
    name_en: str


# ----------------------------------------------------------------------------
# The Commission's list
# ----------------------------------------------------------------------------
def fetch_union_list() -> list[dict[str, Any]]:
    """Every item of the Union list, following the pages the API gives."""
    items: list[dict[str, Any]] = []
    url: str | None = UNION_LIST_URL
    params: dict[str, str] | None = UNION_LIST_PARAMS
    for _page in range(MAX_PAGES):
        if url is None:
            break
        try:
            response = requests.get(
                url, params=params, headers=HEADERS, timeout=TIMEOUT
            )
            response.raise_for_status()
            payload: object = response.json()
        except (requests.RequestException, ValueError) as e:
            msg = f"Could not read the Union list from {url}: {e}"
            raise AdditiveSourceError(msg) from e
        if not isinstance(payload, dict) or not isinstance(
            cast("dict[str, Any]", payload).get("value"), list
        ):
            msg = "Not the Union list of additives: expected {'value': [...]}."
            raise AdditiveSourceError(msg)
        body = cast("dict[str, Any]", payload)
        items += cast("list[dict[str, Any]]", body["value"])
        # The next page is a link that already has its parameters.
        url, params = body.get("nextLink"), None
    else:
        msg = f"The Union list has more than {MAX_PAGES} pages: refusing to go on."
        raise AdditiveSourceError(msg)
    return items


def additives_of_union_list(
    items: list[dict[str, Any]],
) -> tuple[list[UnionAdditive], list[str]]:
    """
    The substances of the Union list that have a usable E number, in the order of
    their numbers, and what was left out and why. A group of additives (the groups
    its conditions of use are written for) is not an additive and is not said.
    """
    found: dict[str, UnionAdditive] = {}
    left_out: list[str] = []
    for item in items:
        if item.get("additive_type") != "substanceFAD":
            continue
        name = _plain(str(item.get("additive_name") or ""))
        raw = str(item.get("additive_e_code") or "").strip()
        if raw.isdigit():
            raw = f"E{raw}"  # The list has "1210" for E 1210: a number is a number.
        if "REMOVED" in raw.upper():
            left_out.append(f"{name}: removed from the Union list")
        elif not (code := e_number(raw)):
            left_out.append(f"{name}: no usable E number ({raw or 'none'})")
        elif code not in found:
            ref = str(item.get("policy_item_code") or code)
            found[code] = UnionAdditive(ref, code, name[:MAX_NAME])
    return sorted(found.values(), key=lambda a: _number_order(a.code)), left_out


def _plain(text: str) -> str:
    """A name without the markup and the entities it was typed in."""
    return " ".join(html.unescape(_TAG.sub("", text)).split()).strip(_EDGE)


def _number_order(code: str) -> tuple[int, str]:
    """E100 before E1000, and E160a before E160b."""
    digits = re.match(r"E(\d+)", code)
    return (int(digits.group(1)) if digits else 0, code)


# ----------------------------------------------------------------------------
# The French names
# ----------------------------------------------------------------------------
def fetch_french_page() -> tuple[str, int]:
    """The HTML of the Wikipedia page, and the revision it is."""
    params = {
        "action": "parse",
        "page": WIKIPEDIA_PAGE,
        "prop": "text|revid",
        "format": "json",
        "formatversion": "2",
        "disabletoc": "1",
    }
    try:
        response = requests.get(
            WIKIPEDIA_API_URL, params=params, headers=HEADERS, timeout=TIMEOUT
        )
        response.raise_for_status()
        parsed = response.json()["parse"]
        return str(parsed["text"]), int(parsed["revid"])
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        msg = f"Could not read the page '{WIKIPEDIA_PAGE}' from Wikipedia: {e}"
        raise AdditiveSourceError(msg) from e


def french_names_of_page(page: str) -> dict[str, str]:
    """
    The French name of each E number of the page's tables, by code ("E330").

    A table row that starts with an E number gives it in its first cell and its
    name in the second. The sub-forms (E100(i)) are there too, read as E100I. The
    first row of a code keeps it.
    """
    reader = _TableReader()
    reader.feed(page)
    names: dict[str, str] = {}
    for row in reader.rows:
        if len(row) >= 2 and _E_ROW.match(row[0]) and (code := e_number(row[0])):  # noqa: PLR2004
            if name := french_name(row[1]):
                names.setdefault(code, name)
    return names


def french_name(cell: str) -> str:
    """
    The name a label would use, out of a cell that may list several and explain: the
    first, without a trailing explanation in parentheses.
    """
    first = _FIRST_NAME_END.split(cell, maxsplit=1)[0]
    return _TRAILING_PARENTHESIS.sub("", first).strip(_EDGE)[:MAX_NAME]


class _TableReader(HTMLParser):
    """The rows of every table of a page, as the text of their cells."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._notes = 0  # Inside a footnote mark, which is no part of a name.

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "sup":
            self._notes += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "sup" and self._notes:
            self._notes -= 1

    def handle_data(self, data: str) -> None:
        if self._cell is not None and not self._notes:
            self._cell.append(data)


# ----------------------------------------------------------------------------
# Putting them together
# ----------------------------------------------------------------------------
def build_dataset(
    union: list[UnionAdditive],
    french: dict[str, str],
    *,
    generated: str,
    wikipedia_revision: int,
) -> dict[str, Any]:
    """
    The dataset the table is loaded from: each substance of the Union list, with its
    English name and, when the page has one, its French name.
    """
    return {
        "generated": generated,
        "sources": {
            "union_list": UNION_LIST_URL,
            "french_names": (
                f"{WIKIPEDIA_URL}{WIKIPEDIA_PAGE.replace(' ', '_')} "
                f"(revision {wikipedia_revision}), CC BY-SA 4.0"
            ),
        },
        "additives": [
            {
                "code": a.code,
                "name_en": a.name_en,
                "name_fr": french.get(a.code, ""),
                "ref": a.ref,
            }
            for a in union
        ],
    }
