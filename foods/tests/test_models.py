import pytest
from django.db import IntegrityError

from foods.models import Macronutrient


@pytest.mark.django_db
def test_str_without_description():
    m = Macronutrient.objects.create(name="protein")
    assert str(m) == "Protein"


@pytest.mark.django_db
def test_str_with_description():
    m = Macronutrient.objects.create(name="protein", description="g/100g")
    assert str(m) == "Protein (g/100g)"


@pytest.mark.django_db
def test_str_with_underscores():
    m = Macronutrient.objects.create(name="total_fat")
    assert str(m) == "Total Fat"


@pytest.mark.django_db
def test_str_with_multiple_underscores():
    m = Macronutrient.objects.create(name="omega_3_fatty_acid")
    assert str(m) == "Omega 3 Fatty Acid"


@pytest.mark.django_db
def test_primary_key_uniqueness():
    Macronutrient.objects.create(name="protein")
    with pytest.raises(IntegrityError):
        Macronutrient.objects.create(name="protein")
