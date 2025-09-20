import pytest
from django.db import IntegrityError
from django.db import transaction

from foods.models import Macronutrient
from foods.models import Vitamin


# ----------------------------------------------------------------------------
# Macronutrient model tests --------------------------------------------------
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_macronutrient_str_without_description():
    m = Macronutrient.objects.create(name="protein")
    assert str(m) == "Protein"


@pytest.mark.django_db
def test_macronutrient_str_with_description():
    m = Macronutrient.objects.create(name="protein", description="g/100g")
    assert str(m) == "Protein (g/100g)"


@pytest.mark.django_db
def test_macronutrient_str_with_underscores():
    m = Macronutrient.objects.create(name="total_fat")
    assert str(m) == "Total Fat"


@pytest.mark.django_db
def test_macronutrient_str_with_multiple_underscores():
    m = Macronutrient.objects.create(name="omega_3_fatty_acid")
    assert str(m) == "Omega 3 Fatty Acid"


@pytest.mark.django_db
def test_macronutrient_primary_key_case_insensitive_uniqueness():
    # Initial creation
    Macronutrient.objects.create(name="protein")

    # Test exact duplicate
    with transaction.atomic(), pytest.raises(IntegrityError):
        Macronutrient.objects.create(name="protein")

    # Test case-insensitive duplicate
    with transaction.atomic(), pytest.raises(IntegrityError):
        Macronutrient.objects.create(name="Protein")


# ----------------------------------------------------------------------------
# Vitamin model tests --------------------------------------------------------
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_vitamin_str_without_common_name():
    m = Vitamin.objects.create(
        name="thiamine",
        atc_code="A11DA01",
        chembl_id="CHEMBL1547",
    )
    assert str(m) == "Thiamine"


@pytest.mark.django_db
def test_vitamin_str_with_common_name():
    m = Vitamin.objects.create(
        name="thiamine",
        common_name="Vitamin B1",
        atc_code="A11DA01",
        chembl_id="CHEMBL1547",
    )
    assert str(m) == "Thiamine (Vitamin B1)"


@pytest.mark.django_db
def test_vitamin_name_case_insensitive_uniqueness():
    Vitamin.objects.create(
        name="thiamine",
        atc_code="A11DA01",
        chembl_id="CHEMBL1547",
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        Vitamin.objects.create(
            name="Thiamine",  # same name, different case
            atc_code="A11DA02",
            chembl_id="CHEMBL1548",
        )


@pytest.mark.django_db
def test_vitamin_atc_code_case_insensitive_uniqueness():
    Vitamin.objects.create(
        name="thiamine",
        atc_code="A11DA01",
        chembl_id="CHEMBL1547",
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        Vitamin.objects.create(
            name="riboflavine",
            atc_code="a11da01",  # same ATC code, lowercase
            chembl_id="CHEMBL1548",
        )


@pytest.mark.django_db
def test_vitamin_chembl_id_case_insensitive_uniqueness():
    Vitamin.objects.create(
        name="thiamine",
        atc_code="A11DA01",
        chembl_id="CHEMBL1547",
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        Vitamin.objects.create(
            name="riboflavine",
            atc_code="A11DA02",
            chembl_id="chembl1547",  # same ChEMBL, lowercase
        )


@pytest.mark.django_db
def test_vitamin_default_unit_in_form_applied():
    from foods.models import DEFAULT_VITAMIN_UNIT  # noqa: PLC0415

    vitamin = Vitamin.objects.create(
        name="thiamine",
        atc_code="A11DA01",
        chembl_id="CHEMBL1547",
    )
    assert vitamin.default_unit_in_form == DEFAULT_VITAMIN_UNIT


@pytest.mark.django_db
def test_vitamin_default_unit_in_form_with_custom_choice():
    # choose a different unit from the choices
    from foods.models import VITAMIN_UNIT_CHOICES  # noqa: PLC0415

    custom_unit = VITAMIN_UNIT_CHOICES[0][0]
    vitamin = Vitamin.objects.create(
        name="riboflavine",
        atc_code="A11DA02",
        chembl_id="CHEMBL1548",
        default_unit_in_form=custom_unit,
    )
    assert vitamin.default_unit_in_form == custom_unit


@pytest.mark.django_db
def test_vitamin_name_max_length():
    long_name = "A" * 100
    vitamin = Vitamin.objects.create(
        name=long_name,
        atc_code="A11DA03",
        chembl_id="CHEMBL1549",
    )
    assert vitamin.name == long_name


@pytest.mark.django_db
def test_vitamin_common_name_optional():
    vitamin = Vitamin.objects.create(
        name="niacine",
        atc_code="A11DA04",
        chembl_id="CHEMBL1550",
    )
    assert vitamin.common_name == ""  # blank=True → empty string by default
