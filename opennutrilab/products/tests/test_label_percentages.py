from decimal import Decimal

import pytest

from opennutrilab.products.api.openfoodfacts.label_percentages import (
    declared_percentages,
)
from opennutrilab.products.api.openfoodfacts.label_percentages import percentages_in

NO_BREAK_SPACE = chr(0xA0)
NARROW_NO_BREAK_SPACE = chr(0x202F)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Flocons de soja 33%, raisins 8 % (raisins, huile)", ["8", "33"]),
        # A comma or a point, and "1,4" is not also "4".
        ("fruits rouges 1,4%, sésame 10.6%", ["1.4", "10.6"]),
        # French typography puts a (narrow) no-break space before the sign.
        (f"sucre 5{NO_BREAK_SPACE}%, sel 2{NARROW_NO_BREAK_SPACE}%", ["2", "5"]),
        # No space after the previous item.
        ("sucre,5%", ["5"]),
        # The same figure twice is one number.
        ("farine 5,4%, germe 5,4%", ["5.4"]),
        # More precision than Ingredient.percentage holds, and no percentage.
        ("sel 0,125%, eau 5 g", []),
        ("", []),
    ],
)
def test_the_percentages_a_text_declares(text: str, expected: list[str]):
    assert percentages_in(text) == tuple(Decimal(n) for n in expected)


def numbers(*figures: str) -> tuple[Decimal, ...]:
    return tuple(Decimal(figure) for figure in figures)


def test_a_value_the_label_declares_is_the_labels_number():
    declared = declared_percentages([13.0, 7.4, None], numbers("6.6", "7.4", "13"))

    assert declared == [Decimal(13), Decimal("7.4"), None]


def test_values_rescaled_by_one_factor_give_back_the_label_numbers():
    label = numbers("1", "1.4", "5", "8", "25", "26", "33")
    off = [value / 0.994 for value in (33.0, 26.0, 25.0, 1.4)]

    assert declared_percentages(off, label) == [
        Decimal(33),
        Decimal(26),
        Decimal(25),
        Decimal("1.4"),
    ]


def test_a_value_the_label_does_not_back_is_left_out():
    # Alone, a value fits any factor: nothing says what it was rescaled from.
    assert declared_percentages([33.2], numbers("33")) == [None]
    # Two values that no single factor maps onto the label.
    assert declared_percentages([33.2, 26.5], numbers("33", "26")) == [None, None]


def test_several_possible_factors_recover_nothing():
    # 3 and 6 come from 1 and 2 (x3) or from 2 and 4 (x1.5).
    assert declared_percentages([3.0, 6.0], numbers("1", "2", "4")) == [None, None]


@pytest.mark.parametrize("value", [-1.0, 180.0, float("nan")])
def test_a_value_outside_zero_to_a_hundred_is_left_out(value: float):
    assert declared_percentages([value], numbers("180", "1")) == [None]


def test_a_value_of_zero_is_not_a_rescaling_anchor():
    assert declared_percentages([0.0, 7.0], numbers("10", "20")) == [None, None]
