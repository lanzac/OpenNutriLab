from decimal import Decimal

import pytest

from opennutrilab.products.services.servings import Serving
from opennutrilab.products.services.servings import read_serving


@pytest.mark.parametrize(
    ("text", "serving"),
    [
        ("30 g", Serving(Decimal(30), "g")),
        ("30g", Serving(Decimal(30), "g")),
        ("  45 g ", Serving(Decimal(45), "g")),
        ("35,7 g", Serving(Decimal("35.7"), "g")),
        ("250 ml", Serving(Decimal(250), "ml")),
        ("250 mL", Serving(Decimal(250), "ml")),
        ("25 cl", Serving(Decimal(250), "ml")),
        ("1,5 l", Serving(Decimal(1500), "ml")),
        ("30 gr", Serving(Decimal(30), "g")),
        ("30 grammes", Serving(Decimal(30), "g")),
        ("30 Gram", Serving(Decimal(30), "g")),
    ],
)
def test_a_quantity_alone_is_read_with_its_unit(text: str, serving: Serving):
    assert read_serving(text) == serving


@pytest.mark.parametrize(
    ("text", "serving"),
    [
        # The bread of the development database.
        ("35.7 g (1 tranche)", Serving(Decimal("35.7"), "g", "1 tranche")),
        ("8.4g (1 biscuit)", Serving(Decimal("8.4"), "g", "1 biscuit")),
        ("25.6 g (5 carrés)", Serving(Decimal("25.6"), "g", "5 carrés")),
        ("30 g (portion)", Serving(Decimal(30), "g", "portion")),
        ("70 g (2 saucisses.)", Serving(Decimal(70), "g", "2 saucisses")),
        ("1 portion (30 g)", Serving(Decimal(30), "g", "1 portion")),
        ("Deux biscuits (25 g)", Serving(Decimal(25), "g", "Deux biscuits")),
        ("1 can (330 ml)", Serving(Decimal(330), "ml", "1 can")),
    ],
)
def test_a_quantity_is_read_with_the_name_beside_it(text: str, serving: Serving):
    assert read_serving(text) == serving


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        # No unit, or no quantity.
        "30",
        "1 tranche",
        "1 tasse",
        # Two quantities: which one is the product's is not said.
        "40 g (40 g + 125 ml de lait demi-écrémé)",
        "205 ml (4 g + 200 ml de lait demi-écrémé)",
        "15 g (1 bol de 200 ml)",
        "15g + 200ml de lait",
        "10 g (10 Gramme)",
        # A parenthesis within the name.
        "35.7 g (1 tranche (environ 35.7 g))",
        # A "name" with no letter.
        "10 g (10)",
        # Neither of the three forms.
        "8.8g, 1 biscotte",
        "1 pot 115 g",
        "Une tranche 62,5 g",
        # More decimals than are kept, and nothing at all.
        "33.333 g",
        "0 g",
    ],
)
def test_any_other_text_is_not_read(text: str | None):
    assert read_serving(text) is None
