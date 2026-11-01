from pathlib import Path

import pytest

from opennutrilab.products.models import Nutrient
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.derived_nutrients import ensure_derivations
from opennutrilab.products.services.label_nutrients import ensure_label_only
from opennutrilab.products.services.vitamins import FORMS
from opennutrilab.products.services.vitamins import LETTERS
from opennutrilab.products.services.vitamins import vitamin_called
from opennutrilab.products.services.vitamins import vitamin_nutrient

CONSTITUENTS_FILE = Path(__file__).parents[1] / "data" / "ciqual_const_2025.xml"


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("vitamine B6", "vitamin_b6"),
        ("Vitamine D", "vitamin_d"),
        ("vitamin b12", "vitamin_b12"),
        ("vit. C", "vitamin_c"),
        ("Vit E", "vitamin_e"),
        ("vitamine PP", "vitamin_b3"),
        ("vitamine D3", "vitamin_d3"),
        ("chlorhydrate de pyridoxine", "vitamin_b6"),
        ("Cholécalciférol", "vitamin_d3"),
        ("  acide   folique ", "folic_acid"),
        ("pyridoxine hydrochloride", "vitamin_b6"),
        ("acide ascorbique", "vitamin_c"),
        ("riboflavine", "vitamin_b2"),
        # Biotin, B7 for the nomenclature and B8 for the French.
        ("biotine", "biotin"),
        ("Biotin", "biotin"),
        ("vitamine B8", "biotin"),
        ("vitamine B7", "biotin"),
        ("vitamine H", "biotin"),
        # Beta-carotene, as labels spell it.
        ("bêta-carotène", "beta_carotene"),
        ("B-carotène", "beta_carotene"),
        ("béta carotène", "beta_carotene"),
        ("\u03b2-carotène", "beta_carotene"),
        ("beta-carotene", "beta_carotene"),
        # The digits of B12 written small, as a label may.
        ("vitamine B\u2081\u2082", "vitamin_b12"),
        ("Vitamin B\u2086", "vitamin_b6"),
        ("vitamine D\u2083", "vitamin_d3"),
    ],
)
def test_a_vitamin_is_the_nutrient_it_is_called_by(name: str, code: str):
    assert vitamin_nutrient(name) == code


@pytest.mark.parametrize(
    "name",
    [
        "",
        "farine",
        "vitamine",
        "vitamine Z",
        "vitamine B10",
        "carotène",
        "vitamines",
        "vitamine B6 et D",
        "e",
        "b6",
        "fer",
        "lait enrichi en vitamine D",
    ],
)
def test_a_name_that_is_no_vitamin_of_the_list_is_none(name: str):
    assert vitamin_nutrient(name) == ""


@pytest.mark.django_db
def test_every_name_of_the_list_is_a_nutrient_of_the_catalogue():
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    ensure_derivations()
    ensure_label_only()

    missing = {*LETTERS.values(), *FORMS.values()} - set(
        Nutrient.objects.values_list("code", flat=True)
    )

    assert missing == set()


@pytest.mark.parametrize(
    ("name", "heading", "called"),
    [
        ("b6", "vitamines", "vitamine b6"),
        ("PP", "Vitamines", "vitamine pp"),
        ("d3", "vitamins", "vitamin d3"),
        ("e", "vitamin", "vitamin e"),
        ("cholécalciférol", "vitamines", "cholécalciférol"),
        ("vitamine c", "vitamines", "vitamine c"),
        ("fer", "vitamines", ""),
        ("farine", "vitamines", ""),
        ("z", "vitamines", ""),
    ],
)
def test_a_name_under_a_heading_of_vitamins_is_called_as_a_vitamin(
    name: str, heading: str, called: str
):
    assert vitamin_called(name, heading) == called
