from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.db import IntegrityError
from django.db import transaction

from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import NutrientComponent
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.derived_nutrients import DERIVATIONS
from opennutrilab.products.services.derived_nutrients import DerivationError
from opennutrilab.products.services.derived_nutrients import complete_with_derived
from opennutrilab.products.services.derived_nutrients import derived_amount
from opennutrilab.products.services.derived_nutrients import derived_nutrients
from opennutrilab.products.services.derived_nutrients import ensure_derivations

CONSTITUENTS_FILE = Path(__file__).parents[1] / "data" / "ciqual_const_2025.xml"
D = Decimal


@pytest.fixture
def catalogue(db: None) -> None:
    """The nutrients CIQUAL gives, with the derivations set up."""
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    ensure_derivations()


def derive(code: str, **amounts: str | None) -> Decimal | None:
    return derived_amount(
        Nutrient.objects.get(code=code),
        {k: None if v is None else D(v) for k, v in amounts.items()},
    )


# ----------------------------------------------------------------------------
# The formulas, against what CIQUAL 2025 publishes for real foods
# ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("retinol", "carotene", "published"),
    [
        ("0", "1", "0.083"),  # 1012 Cocktail à base de rhum
        ("0", "54", "4.5"),  # 1017 Sangria, faite maison
        ("0", "8.7", "0.73"),  # 1018 Kir
        ("206", "151", "219"),  # Madeleine, pur beurre
    ],
)
def test_vitamin_a_follows_the_convention_ciqual_publishes_it_in(
    catalogue: None, retinol: str, carotene: str, published: str
):
    """Beta-carotene counts for a twelfth: with a sixth, 1017 would be 9."""
    derived = derive("vitamin_a", retinol=retinol, beta_carotene=carotene)

    assert derived is not None
    assert abs(derived - D(published)) <= D("0.01") + D(published) * D("0.01")


def test_vitamin_a_is_also_worked_out_counting_the_carotene_for_a_sixth(
    catalogue: None,
):
    """The two readings differ, and a label's convention is not known."""
    # Madeleine, pur beurre: the twelfth is what CIQUAL publishes (219).
    twelfth = derive("vitamin_a", retinol="206", beta_carotene="151")
    sixth = derive("vitamin_a_sixth", retinol="206", beta_carotene="151")

    assert twelfth is not None
    assert sixth is not None
    assert abs(sixth - D("231.17")) <= D("0.01")
    assert sixth > twelfth
    # Without carotene they are the same thing: the retinol.
    assert derive("vitamin_a_sixth", retinol="10", beta_carotene="0") == D(10)


@pytest.mark.parametrize(
    ("intrinsic", "folic_acid", "published"),
    [
        ("11.9", "5.7", "21.6"),  # 1032 Haché à base de boeuf et soja
        ("5.0", "1.2", "7.04"),  # 1034 Saucisse de volaille type knack
        ("56.8", "2.3", "60.7"),  # 12007 Camembert au lait pasteurisé
    ],
)
def test_folates_in_dietary_equivalents_count_folic_acid_for_1_7(
    catalogue: None, intrinsic: str, folic_acid: str, published: str
):
    derived = derive(
        "vitamin_b9_dfe", intrinsic_folates=intrinsic, folic_acid=folic_acid
    )

    assert derived is not None
    assert abs(derived - D(published)) <= D("0.05")


@pytest.mark.parametrize(
    ("sodium", "published"),
    [
        ("193", "0.48"),  # 10000 Bigorneau, cuit
        ("243", "0.61"),  # 10001 Calmar, cru
        ("852", "2.13"),  # 10002 Calmar à la romaine
    ],
)
def test_salt_is_sodium_in_mg_times_two_and_a_half_in_g(
    catalogue: None, sodium: str, published: str
):
    derived = derive("salt", sodium=sodium)

    assert derived is not None
    assert abs(derived - D(published)) <= D("0.01")


def test_vitamin_k_is_k1_plus_k2(catalogue: None):
    # 10007 Crevette, cuite.
    assert derive("vitamin_k", vitamin_k1="0.2", vitamin_k2="3.44") == D("3.64")


# ----------------------------------------------------------------------------
# What is incomplete
# ----------------------------------------------------------------------------
def test_a_missing_component_makes_the_amount_incomplete_not_smaller(catalogue: None):
    assert derive("vitamin_k", vitamin_k1="0.2", vitamin_k2=None) is None
    assert derive("vitamin_k", vitamin_k1="0.2") is None


def test_a_component_that_is_zero_is_a_measurement(catalogue: None):
    assert derive("vitamin_k", vitamin_k1="0", vitamin_k2="0") == 0


def test_a_nutrient_that_is_not_derived_gives_nothing(catalogue: None):
    assert derive("fat", fat="9") is None


def test_the_ends_of_a_range_derive_from_the_ends_of_its_components(catalogue: None):
    """The factors are positive, so low gives low and high gives high."""
    low = derive("vitamin_a", retinol="10", beta_carotene="60")
    high = derive("vitamin_a", retinol="12", beta_carotene="72")
    middle = derive("vitamin_a", retinol="11", beta_carotene="66")

    assert low is not None
    assert middle is not None
    assert high is not None
    assert low < middle < high


# ----------------------------------------------------------------------------
# Completing a source's amounts
# ----------------------------------------------------------------------------
def test_a_derived_nutrient_the_source_lacks_is_added(catalogue: None):
    completed = complete_with_derived(
        {"retinol": D("206"), "beta_carotene": D("151"), "vitamin_a": None}
    )

    vitamin_a = completed["vitamin_a"]
    assert vitamin_a is not None
    assert round(vitamin_a, 1) == D("218.6")
    assert completed["retinol"] == D("206")


def test_an_amount_the_source_gave_is_never_replaced(catalogue: None):
    completed = complete_with_derived(
        {"retinol": D("100"), "beta_carotene": D("0"), "vitamin_a": D("5")}
    )

    assert completed["vitamin_a"] == D("5")


def test_a_derived_nutrient_that_cannot_be_computed_is_left_out(catalogue: None):
    completed = complete_with_derived({"vitamin_k1": D("0.2")})

    assert "vitamin_k" not in completed


def test_completing_many_reads_the_catalogue_once(
    catalogue: None, django_assert_num_queries: Any
):
    derived = derived_nutrients()

    with django_assert_num_queries(0):
        for _ in range(5):
            complete_with_derived({"sodium": D("100")}, derived)


# ----------------------------------------------------------------------------
# Setting the derivations up
# ----------------------------------------------------------------------------
def test_the_derivations_are_in_the_catalogue(catalogue: None):
    assert {n.code for n in derived_nutrients()} == set(DERIVATIONS)
    terms = {
        (c.derived_id, c.component_id): c.factor
        for c in NutrientComponent.objects.all()
    }
    assert terms[("vitamin_a", "beta_carotene")] == D("0.083333")
    assert terms[("salt", "sodium")] == D("0.0025")
    assert len(terms) == sum(len(t) for t in DERIVATIONS.values())


def test_vitamin_k_is_created_with_k1_and_k2_as_its_parts(catalogue: None):
    vitamin_k = Nutrient.objects.get(code="vitamin_k")
    k1 = Nutrient.objects.get(code="vitamin_k1")

    assert (vitamin_k.unit, vitamin_k.group) == ("µg", "vitamin")
    assert (vitamin_k.name_en, vitamin_k.name_fr) == ("Vitamin K", "Vitamine K")
    assert vitamin_k.ciqual_code is None
    assert k1.parent_id == "vitamin_k"
    assert Nutrient.objects.get(code="vitamin_k2").parent_id == "vitamin_k"
    assert vitamin_k.display_order < k1.display_order


def test_vitamin_a_with_a_sixth_is_created_and_listed_after_vitamin_a(catalogue: None):
    sixth = Nutrient.objects.get(code="vitamin_a_sixth")
    vitamin_a = Nutrient.objects.get(code="vitamin_a")

    assert (sixth.unit, sixth.group) == ("µg", "vitamin")
    assert sixth.ciqual_code is None
    assert sixth.parent_id is None
    # Retinol, which follows vitamin A in the table, keeps its place after both.
    retinol = Nutrient.objects.get(code="retinol")
    assert vitamin_a.display_order < sixth.display_order < retinol.display_order


def test_setting_them_up_again_changes_nothing(catalogue: None):
    before = (Nutrient.objects.count(), NutrientComponent.objects.count())

    assert ensure_derivations() == len(DERIVATIONS)

    assert (Nutrient.objects.count(), NutrientComponent.objects.count()) == before


def test_a_factor_changed_by_hand_is_put_back_and_a_term_added_is_kept(
    catalogue: None,
):
    NutrientComponent.objects.filter(derived_id="salt").update(factor=D("0.5"))
    NutrientComponent.objects.create(
        derived_id="salt", component=Nutrient.objects.get(code="chloride"), factor=D(1)
    )

    ensure_derivations()

    terms = dict(
        NutrientComponent.objects.filter(derived_id="salt").values_list(
            "component_id", "factor"
        )
    )
    assert terms == {"sodium": D("0.0025"), "chloride": D(1)}


def test_a_derived_nutrient_that_does_not_exist_is_refused(db: None):
    with pytest.raises(DerivationError, match="vitamin_a is derived"):
        ensure_derivations()


def test_a_component_that_does_not_exist_is_refused(db: None):
    Nutrient.objects.create(
        code="vitamin_a",
        name_en="Vitamin A",
        name_fr="Vitamine A",
        unit="µg",
        group="vitamin",
    )

    with pytest.raises(DerivationError, match="derived from retinol"):
        ensure_derivations()


@pytest.mark.parametrize("factor", ["0", "-1"])
def test_a_factor_must_be_positive(catalogue: None, factor: str):
    with transaction.atomic(), pytest.raises(IntegrityError):
        NutrientComponent.objects.create(
            derived_id="vitamin_k",
            component=Nutrient.objects.get(code="vitamin_c"),
            factor=D(factor),
        )
