from decimal import Decimal

import pytest

from opennutrilab.products.services.label_tolerance import label_reading

D = Decimal


def tolerated(code: str, group: str, amount: str) -> tuple[Decimal, Decimal]:
    return label_reading(code, group, D(amount)).tolerated


def test_the_example_of_the_guidance_is_reproduced():
    # 8.5 g of sugars is 8.45 to 8.55 once rounded, and 6.45 to 10.55 less or more
    # the 2 g of the guidance (which writes 8.54 for the upper end).
    reading = label_reading("sugars", "macronutrient", D("8.5"))

    assert reading.rounded == (D("8.45"), D("8.55"))
    assert reading.tolerated == (D("6.45"), D("10.55"))


@pytest.mark.parametrize(
    ("amount", "width"),
    [
        ("5", D(2)),  # below 10 g: 2 g
        ("10", D(2)),  # 10 g is "10-40 g": a fifth of it
        ("20", D(4)),
        ("40", D(8)),  # up to 40 g included
        ("41", D(8)),  # above 40 g: 8 g
    ],
)
def test_a_macronutrient_is_allowed_2_g_below_10_a_fifth_to_40_and_8_g_above(
    amount: str, width: Decimal
):
    # Around the ends of the rounding, as the guidance does.
    reading = label_reading("proteins", "macronutrient", D(amount))

    assert reading.tolerated[1] - reading.rounded[1] == width
    assert reading.rounded[0] - reading.tolerated[0] == width


def test_fat_is_allowed_1_5_g_below_10_g():
    low, high = tolerated("fat", "macronutrient", "9.4")

    assert (low, high) == (D("9.35") - D("1.5"), D("9.45") + D("1.5"))


@pytest.mark.parametrize(
    ("code", "amount", "width"),
    [
        ("saturated_fat", "3.9", D("0.8")),
        ("saturated_fat", "4", D("0.8")),  # a fifth of 4 g, 0.8 g, from 4 g up
        ("saturated_fat", "13", D("2.6")),
        ("monounsaturated_fat", "13", D("2.6")),
        ("polyunsaturated_fat", "2", D("0.8")),
    ],
)
def test_the_fatty_acids_are_allowed_0_8_g_below_4_g_and_a_fifth_above(
    code: str, amount: str, width: Decimal
):
    reading = label_reading(code, "fatty_acid", D(amount))

    assert reading.tolerated[1] - reading.rounded[1] == width
    assert reading.rounded[0] - reading.tolerated[0] == width


def test_salt_and_sodium_have_their_own_limits():
    # Salt: 0.375 g below 1.25 g, a fifth above. Sodium: 0.15 g below 0.5 g
    # (the catalogue gives it in mg), a fifth above.
    salt = label_reading("salt", "other", D("1"))
    assert salt.tolerated[1] - salt.rounded[1] == D("0.375")
    big_salt = label_reading("salt", "other", D("2"))
    assert big_salt.tolerated[1] - big_salt.rounded[1] == D("0.4")
    sodium = label_reading("sodium", "mineral", D("200"))
    assert sodium.tolerated[1] - sodium.rounded[1] == D(150)
    big_sodium = label_reading("sodium", "mineral", D("1000"))
    assert big_sodium.tolerated[1] - big_sodium.rounded[1] == D(200)


def test_vitamins_and_minerals_are_allowed_a_share_of_the_figure():
    vitamin = label_reading("vitamin_c", "vitamin", D("80"))
    mineral = label_reading("iron", "mineral", D("10"))

    assert vitamin.rounded[0] - vitamin.tolerated[0] == D("28.00")  # 35 %
    assert vitamin.tolerated[1] - vitamin.rounded[1] == D("40.0")  # 50 %
    assert mineral.rounded[0] - mineral.tolerated[0] == D("3.5")  # 35 %
    assert mineral.tolerated[1] - mineral.rounded[1] == D("4.5")  # 45 %


def test_energy_and_what_the_guidance_does_not_name_are_only_rounded():
    energy = label_reading("energy", "energy", D("3382"))
    other = label_reading("cholesterol", "other", D("12"))

    assert energy.tolerated == energy.rounded == (D("3381.5"), D("3382.5"))
    assert other.tolerated == other.rounded


@pytest.mark.parametrize(
    ("code", "group", "stands_for"),
    [
        ("proteins", "macronutrient", D("0.5")),
        ("fat", "macronutrient", D("0.5")),
        ("saturated_fat", "fatty_acid", D("0.1")),
        ("salt", "other", D("0.0125")),
        ("sodium", "mineral", D(5)),
        ("energy", "energy", D(0)),
        ("vitamin_c", "vitamin", D(0)),
    ],
)
def test_a_zero_stands_for_the_least_amount_the_guidelines_round_to_nothing(
    code: str, group: str, stands_for: Decimal
):
    reading = label_reading(code, group, D(0))

    assert reading.rounded == (D(0), stands_for)
    assert reading.tolerated[0] == 0
    assert reading.tolerated[1] >= stands_for


def test_the_low_end_never_goes_below_nothing():
    assert tolerated("proteins", "macronutrient", "1")[0] == 0
