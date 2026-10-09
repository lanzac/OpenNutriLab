from decimal import Decimal

import pytest

from opennutrilab.meals.services.energy import KCAL_PER_MJ
from opennutrilab.meals.services.energy import Person
from opennutrilab.meals.services.energy import basal_metabolisms
from opennutrilab.meals.services.energy import energy_need

D = Decimal
ORDER = ("schofield", "mifflin", "harris_benedict", "muller", "henry")

# ANSES' report 2012-SA-0103 (2016), table 26, page 89: the basal metabolism in
# kcal/day by each equation, for the median height of the age band and a BMI of 22,
# as (sex, band, height, weight, (Schofield, Mifflin, Harris & Benedict, Müller,
# Henry)).
TABLE_26 = [
    ("male", (18, 29), "178", "69.7", (1742, 1696, 1753, 1708, 1659)),
    ("male", (30, 39), "178", "69.7", (1673, 1642, 1679, 1670, 1579)),
    ("male", (40, 49), "176", "68.1", (1655, 1564, 1580, 1617, 1557)),
    ("male", (50, 59), "174", "66.6", (1637, 1487, 1481, 1565, 1535)),
    ("female", (18, 29), "163", "58.5", (1353, 1324, 1403, 1340, 1319)),
    ("female", (30, 39), "163", "58.5", (1321, 1270, 1352, 1302, 1261)),
    ("female", (40, 49), "163", "58.5", (1321, 1220, 1305, 1267, 1261)),
    ("female", (50, 59), "161", "57", (1309, 1144, 1241, 1217, 1248)),
]


@pytest.mark.parametrize(("sex", "band", "height", "weight", "published"), TABLE_26)
def test_the_five_equations_give_what_anses_published(
    sex: str,
    band: tuple[int, int],
    height: str,
    weight: str,
    published: tuple[int, ...],
):
    # The report does not say the age it took in a band: the middle is within
    # half a year of it.
    person = Person(sex, (band[0] + band[1] + 1) // 2, D(weight), D(height))

    found = basal_metabolisms(person)

    for name, expected in zip(ORDER, published, strict=True):
        gap = abs(found[name] - expected) / expected
        assert gap < D("0.0035"), (name, found[name], expected)


def test_henry_in_men_of_sixty_and_more_is_the_one_that_parts_from_the_table():
    """The report must have used another of Henry's bands there (see the module)."""
    found = basal_metabolisms(Person("male", 65, D("65.1"), D(172)))

    assert abs(found["schofield"] - 1350) / 1350 < D("0.0035")
    assert D("0.01") < (1411 - found["henry"]) / 1411 < D("0.02")


def test_a_band_starts_at_its_lower_age():
    younger = basal_metabolisms(Person("male", 29, D(70), D(178)))["schofield"]
    older = basal_metabolisms(Person("male", 30, D(70), D(178)))["schofield"]

    assert round(younger / KCAL_PER_MJ, 3) == D("7.306")  # 0.063 x 70 + 2.896
    assert round(older / KCAL_PER_MJ, 3) == D("7.013")  # 0.048 x 70 + 3.653


def test_the_need_is_the_mean_of_the_five_times_the_activity_level():
    person = Person("male", 31, D(61), D(180))
    metabolisms = basal_metabolisms(person)

    need = energy_need(person, D("1.7"))

    assert need == sum(metabolisms.values(), D(0)) / 5 * D("1.7")
    # The user's own profile, the first case the plan names.
    assert round(need) == 2651  # noqa: PLR2004
