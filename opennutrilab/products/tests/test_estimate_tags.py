from decimal import Decimal

import pytest
from django.utils import translation

from opennutrilab.products.api.schemas.outbound import IngredientEstimateOut
from opennutrilab.products.api.schemas.outbound import RangeOut
from opennutrilab.products.api.schemas.outbound import ReferenceOut
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.templatetags.estimate_tags import figure
from opennutrilab.products.templatetags.estimate_tags import plain
from opennutrilab.products.templatetags.estimate_tags import span
from opennutrilab.products.templatetags.estimate_tags import walk

D = Decimal


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        # Three significant digits, and the integer part is never rounded.
        ("9.222606", "9.22"),
        ("1416.07197", "1416"),
        ("1739.388445", "1739"),
        # A small fraction keeps its digits, which a fixed number of decimals loses.
        ("0.012174", "0.0122"),
        ("0.000000", "0"),
        # No zero is padded on: it would claim a precision there is not.
        ("12.5", "12.5"),
        ("7.50", "7.5"),
        ("10.0", "10"),
        ("100.00", "100"),
    ],
)
def test_a_figure_has_three_significant_digits(value: str, shown: str):
    with translation.override("en"):
        assert figure(D(value)) == shown


def test_a_figure_follows_the_decimal_separator_of_the_language_served():
    with translation.override("fr"):
        assert figure(D("9.222606")) == "9,22"
        assert plain(D("9.4000")) == "9,4"


def test_nothing_gives_nothing():
    assert (figure(None), plain(None), span(None)) == ("", "", "")


@pytest.mark.parametrize(
    ("value", "shown"),
    [("9.4000", "9.4"), ("1532.0000", "1532"), ("0.0200", "0.02"), ("100", "100")],
)
def test_a_declared_figure_is_shown_as_it_was_written(value: str, shown: str):
    with translation.override("en"):
        assert plain(D(value)) == shown


def test_a_range_is_low_to_high_and_open_when_no_upper_end_is_known():
    with translation.override("en"):
        assert span(RangeOut(low=D("1416.07"), point=D("1579"), high=D("1739.39"))) == (
            "1416 \u2013 1739"
        )
        assert span(RangeOut(low=D("0.3927"), point=D("0.524"), high=None)) == "≥ 0.393"


def ingredient(name: str, *subs: IngredientEstimateOut) -> IngredientEstimateOut:
    reference = ReferenceIngredient(pk=1, name_en=name, status="curated")
    return IngredientEstimateOut(
        reference=ReferenceOut.model_validate(reference),
        sub_ingredients=list(subs),
    )


def name_of(ingredient: IngredientEstimateOut) -> str:
    assert ingredient.reference is not None
    return ingredient.reference.model_dump()["name"]


def test_the_tree_is_walked_in_the_order_of_the_label_with_its_depth():
    tree = [
        ingredient("dates", ingredient("rice flour", ingredient("rice"))),
        ingredient("oats"),
    ]

    assert [(depth, name_of(i)) for depth, i in walk(tree)] == [
        (0, "dates"),
        (1, "rice flour"),
        (2, "rice"),
        (0, "oats"),
    ]
