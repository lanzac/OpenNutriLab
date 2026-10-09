"""
The energy a person needs in a day: basal metabolism times activity level.

ANSES takes no single equation for the basal metabolism: following EFSA, which
found none of five better than the others, it works out each and takes their
mean (report 2012-SA-0103 of 2016, pages 88 to 90). So does this. The five, as
the report names them, with weight W in kg, height H in cm and age A in years:

- Schofield 1985 (weight only, by age band, in MJ/day);
- Mifflin 1990: 10 W + 6.25 H - 5 A + 5 for a man, - 161 for a woman (kcal);
- Harris and Benedict 1919 (kcal);
- Müller 2004: 0.047 W + 1.009 for a man - 0.01452 A + 3.21 (MJ/day);
- Henry 2005 (weight only, by age band, in MJ/day).

Checked against the report's own table 26, which works them out for the median
height of each age band and a BMI of 22: within 0.35 % for every equation and band,
but for Henry's in men of 60 to 69 (1.5 % under): the report must have used another
of Henry's bands there.

The need is the mean times the physical activity level (PAL). ANSES' own
optimisation allows 5 % around it (page 90), which is the range kept here.
"""

from decimal import Decimal
from typing import NamedTuple

KJ_PER_KCAL = Decimal("4.184")
KCAL_PER_MJ = Decimal(1000) / KJ_PER_KCAL
# How far from the need a day may be (see the module).
ENERGY_MARGIN = Decimal("0.05")
# The equations as the report names them.
EQUATIONS = {
    "schofield": "Schofield 1985",
    "mifflin": "Mifflin 1990",
    "harris_benedict": "Harris & Benedict 1919",
    "muller": "Müller 2004",
    "henry": "Henry 2005",
}

# (below this age, slope per kg, constant), in MJ/day.
_SCHOFIELD = {
    "male": [(30, "0.063", "2.896"), (60, "0.048", "3.653"), (None, "0.049", "2.459")],
    "female": [
        (30, "0.062", "2.036"),
        (60, "0.034", "3.538"),
        (None, "0.038", "2.755"),
    ],
}
_HENRY = {
    "male": [(30, "0.0669", "2.28"), (60, "0.0592", "2.48"), (None, "0.0563", "2.15")],
    "female": [
        (30, "0.0546", "2.33"),
        (60, "0.0407", "2.90"),
        (None, "0.0424", "2.38"),
    ],
}


class Person(NamedTuple):
    sex: str  # "male" or "female"
    age: int
    weight: Decimal  # kg
    height: Decimal  # cm


def basal_metabolisms(person: Person) -> dict[str, Decimal]:
    """The basal metabolism by each of the five equations, in kcal/day."""
    w, h, a = person.weight, person.height, Decimal(person.age)
    male = person.sex == "male"
    return {
        "schofield": _by_band(_SCHOFIELD, person) * KCAL_PER_MJ,
        "mifflin": 10 * w + Decimal("6.25") * h - 5 * a + (5 if male else -161),
        "harris_benedict": (
            Decimal("66.4730")
            + Decimal("13.7516") * w
            + Decimal("5.0033") * h
            - Decimal("6.7550") * a
            if male
            else Decimal("655.0955")
            + Decimal("9.5634") * w
            + Decimal("1.8496") * h
            - Decimal("4.6756") * a
        ),
        "muller": (
            Decimal("0.047") * w
            + (Decimal("1.009") if male else 0)
            - Decimal("0.01452") * a
            + Decimal("3.21")
        )
        * KCAL_PER_MJ,
        "henry": _by_band(_HENRY, person) * KCAL_PER_MJ,
    }


def energy_need(person: Person, activity_level: Decimal) -> Decimal:
    """The energy needed in a day, in kcal: the mean of the five, times the PAL."""
    metabolisms = basal_metabolisms(person)
    return sum(metabolisms.values(), Decimal(0)) / len(metabolisms) * activity_level


def _by_band(
    bands: dict[str, list[tuple[int | None, str, str]]], person: Person
) -> Decimal:
    for below, slope, constant in bands[person.sex]:
        if below is None or person.age < below:
            return Decimal(slope) * person.weight + Decimal(constant)
    msg = "The last band has no upper age."
    raise AssertionError(msg)
