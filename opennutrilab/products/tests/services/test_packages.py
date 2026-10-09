from decimal import Decimal

import pytest

from opennutrilab.products.services.packages import Package
from opennutrilab.products.services.packages import read_package

D = Decimal
# Written by their code, which no editor or formatter then changes: the sign of a
# multiplication, and the sign of an estimated quantity (U+212E).
TIMES = chr(0x00D7)
ESTIMATED = chr(0x212E)


@pytest.mark.parametrize(
    ("text", "package"),
    [
        ("500 g", Package(D(500), "g")),
        ("500g", Package(D(500), "g")),
        ("  375 g ", Package(D(375), "g")),
        ("1,5 kg", Package(D(1500), "g")),
        ("1.5kg", Package(D(1500), "g")),
        ("250 gr", Package(D(250), "g")),
        ("250 grammes", Package(D(250), "g")),
        ("1 L", Package(D(1000), "ml")),
        ("1,5 l", Package(D(1500), "ml")),
        ("75 cl", Package(D(750), "ml")),
        ("33cl", Package(D(330), "ml")),
        ("2 dl", Package(D(200), "ml")),
        ("250 mL", Package(D(250), "ml")),
    ],
)
def test_a_quantity_is_read_in_grams_or_millilitres(text: str, package: Package):
    assert read_package(text) == package


@pytest.mark.parametrize(
    ("text", "package"),
    [
        ("6 x 125 g", Package(D(750), "g")),
        ("6x125g", Package(D(750), "g")),
        ("6 X 125 g", Package(D(750), "g")),
        ("6 * 125 g", Package(D(750), "g")),
        (f"6{TIMES}125 g", Package(D(750), "g")),
        ("4 x 33 cl", Package(D(1320), "ml")),
        ("2 x 0,5 kg", Package(D(1000), "g")),
    ],
)
def test_a_number_of_packs_is_the_total_of_them(text: str, package: Package):
    assert read_package(text) == package


@pytest.mark.parametrize(
    ("text", "package"),
    [
        # The sign of an estimated quantity, as the packaging writes it.
        ("500 g e", Package(D(500), "g")),
        ("500 g E", Package(D(500), "g")),
        (f"500 g {ESTIMATED}", Package(D(500), "g")),
        (f"1,5 L {ESTIMATED}", Package(D(1500), "ml")),
        # A note in parentheses is not read, and the first quantity is the package's.
        ("135 g (3 x 45 g)", Package(D(135), "g")),
        ("135 g (3 portions)", Package(D(135), "g")),
        ("250 g (150 g égoutté)", Package(D(250), "g")),
        (f"250 g {ESTIMATED} (3 biscuits)", Package(D(250), "g")),
        ("250 g (3 x 80 g) e", Package(D(250), "g")),
        ("3 x 45 g (135 g)", Package(D(135), "g")),
    ],
)
def test_the_sign_of_an_estimated_quantity_and_a_note_are_left_out(
    text: str, package: Package
):
    assert read_package(text) == package


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        # No unit, or no quantity.
        "100",
        "2 pots",
        "un sachet",
        # Two quantities, or the count first with the quantity in parentheses.
        "x10 (350g)",
        "200g 8x25g",
        "210 g, 5 barres doubles de 42 g",
        "135g / 95g (net égoutté)",
        "2x14 crackers, 150 g",
        # Said to be approximate.
        "environ 500 g",
        # Nothing, or more than a package can hold.
        "0 g",
        "6 x 0 g",
        "99999 kg",
    ],
)
def test_any_other_text_is_not_read(text: str | None):
    assert read_package(text) is None
