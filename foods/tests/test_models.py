import pytest
from django.db import IntegrityError
from django.db import transaction

from foods.models import Food
from foods.models import FoodMacronutrient
from foods.models import FoodVitamin
from foods.models import Macronutrient
from foods.models import Vitamin


# ----------------------------------------------------------------------------
# Macronutrient model tests --------------------------------------------------
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_macronutrient_reference_data():
    expected_names = {
        "fat",
        "saturated_fat",
        "carbohydrates",
        "sugars",
        "fiber",
        "proteins",
    }
    existing_names = set(Macronutrient.objects.values_list("name", flat=True))
    missing = expected_names - existing_names
    assert not missing, f"Missing macronutrients in DB: {missing}"


@pytest.mark.django_db
@pytest.mark.parametrize(
    argnames=("name", "description", "expected"),
    argvalues=[
        # Basic name without underscore or description
        ("simplemacro", "", "Simplemacro"),
        # Name with single underscore
        ("macro_withoneunderscore", "", "Macro Withoneunderscore"),
        # Name with multiple underscores
        ("macro_with_multiple_underscores", "", "Macro With Multiple Underscores"),
        # Name with description only
        ("macrowithdescription", "g/100g", "Macrowithdescription (g/100g)"),
        # Combination underscores and description
        (
            "macro_with_underscores_and_description",
            "mg",
            "Macro With Underscores And Description (mg)",
        ),
        # Name with description text
        ("simplemacro", "per serving", "Simplemacro (per serving)"),
    ],
)
def test_macronutrient_str(name: str, description: str, expected: str):
    """
    Test __str__ formatting for Macronutrient:
    - replaces underscores with spaces
    - applies title casing
    - appends description if present
    """
    m = Macronutrient.objects.create(
        name=name,
        description=description or "",
    )
    assert str(m) == expected


@pytest.mark.django_db
def test_macronutrient_primary_key_case_insensitive_uniqueness():
    # Initial creation
    Macronutrient.objects.create(name="macrotest")

    # Test exact duplicate
    with transaction.atomic(), pytest.raises(IntegrityError):
        Macronutrient.objects.create(name="Macrotest")

    # Test case-insensitive duplicate
    with transaction.atomic(), pytest.raises(IntegrityError):
        Macronutrient.objects.create(name="Macrotest")


# ----------------------------------------------------------------------------
# Vitamin model tests --------------------------------------------------------
# ----------------------------------------------------------------------------
@pytest.mark.django_db
@pytest.mark.parametrize(
    argnames=("name", "common_name", "expected"),
    argvalues=[
        # Without common_name
        ("vitatest", "", "Vitatest"),
        # With common_name
        ("vitatest", "Vitamin B1", "Vitatest (Vitamin B1)"),
    ],
)
def test_vitamin_str(name: str, common_name: str, expected: str):
    """
    Test __str__ formatting for Vitamin:
    - shows name
    - appends common_name in parentheses if present
    """
    m = Vitamin.objects.create(
        name=name,
        common_name=common_name or "",
        atc_code="A11DA01",
        chembl_id="CHEMBL1547",
    )
    assert str(m) == expected


@pytest.mark.django_db
def test_vitamin_name_case_insensitive_uniqueness():
    Vitamin.objects.create(
        name="vitatest",
        atc_code="A11DA01",
        chembl_id="CHEMBL1547",
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        Vitamin.objects.create(
            name="Vitatest",  # same name, different case
            atc_code="A11DA02",
            chembl_id="CHEMBL1548",
        )


@pytest.mark.django_db
def test_vitamin_atc_code_case_insensitive_uniqueness():
    Vitamin.objects.create(
        name="vitatest",
        atc_code="A11DA01",
        chembl_id="CHEMBL1547",
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        Vitamin.objects.create(
            name="othervitatest",
            atc_code="a11da01",  # same ATC code, lowercase
            chembl_id="CHEMBL1548",
        )


@pytest.mark.django_db
def test_vitamin_chembl_id_case_insensitive_uniqueness():
    Vitamin.objects.create(
        name="vitatest",
        atc_code="A11DA01",
        chembl_id="CHEMBL1547",
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        Vitamin.objects.create(
            name="othervitatest",
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


# ----------------------------------------------------------------------------
# Food model tests -----------------------------------------------------------
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_food_str() -> None:
    from foods.models import Food  # noqa: PLC0415

    food = Food.objects.create(barcode="3229820794556", name="muesli protéines")
    assert str(food) == "Muesli Protéines"


# ----------------------------------------------------------------------------
# FoodVitamin model tests ----------------------------------------------------
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_foodvitamin_str_representation() -> None:
    food = Food.objects.create(name="Apple")
    vitamin = Vitamin.objects.create(
        name="Ascorbic acid",
        common_name="Vitamin C",
        atc_code="A11GA01",
        chembl_id="CHEMBL196",
    )
    fv = FoodVitamin.objects.create(food=food, vitamin=vitamin)

    assert str(fv) == "Apple Ascorbic Acid (Vitamin C) amount"


# ----------------------------------------------------------------------------
# FoodMacronutrient model tests ----------------------------------------------
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_foodmacronutrient_str_representation() -> None:
    food = Food.objects.create(name="BananaTest")
    macro = Macronutrient.objects.create(name="ProteinsTest")
    fm = FoodMacronutrient.objects.create(food=food, macronutrient=macro)

    assert str(fm) == "BananaTest ProteinsTest amount"
