from typing import cast

import pytest
from crispy_forms.bootstrap import FieldWithButtons
from crispy_forms.layout import Field
from pint import Quantity
from quantityfield.units import ureg

from foods.forms import FoodForm
from foods.models import Food
from foods.models import FoodMacronutrient
from foods.models import Macronutrient


@pytest.mark.django_db
class TestBuildBarcodeField:
    def test_create_mode_returns_fieldwithbuttons(self):
        form = FoodForm(instance=Food())  # pas de pk
        field: FieldWithButtons | Field = form._get_barcode_field_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        assert isinstance(field, FieldWithButtons)

    def test_edit_mode_returns_readonly_field(self):
        food = Food.objects.create(name="Apple", barcode="1234567890123")
        form = FoodForm(instance=food)
        field: FieldWithButtons | Field = form._get_barcode_field_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        # Doit être un Field simple
        assert isinstance(field, Field)

        # Le widget doit être readonly et avec la classe bg-light
        widget_attrs = form.fields["barcode"].widget.attrs
        assert widget_attrs["readonly"] is True


@pytest.mark.django_db
def test_macronutrient_field_initialized_with_existing_amount():
    # Arrange
    food = Food.objects.create(name="Test Food", barcode="1234567890123")
    macronutrient, _ = Macronutrient.objects.get_or_create(name="proteins")

    # Créons une entrée FoodMacronutrient avec un certain amount
    FoodMacronutrient.objects.create(
        food=food,
        macronutrient=macronutrient,
        amount=Quantity(
            value=12.0,
            units=ureg.g,
        ),
    )

    form = FoodForm(instance=food)

    # Act
    form._add_nutritional_value_fields()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    # Assert
    field_name = f"macronutrients_{macronutrient.name.lower()}"
    assert field_name in form.fields
    assert form.fields[field_name].initial == Quantity(value=12, units="g")


@pytest.mark.django_db
def test_macronutrient_field_not_initialized_without_existing_amount():
    # Arrange
    food = Food.objects.create(name="Test Food 2", barcode="9876543210987")
    macronutrient, _ = Macronutrient.objects.get_or_create(name="fat")

    # Pas de FoodMacronutrient créé
    form = FoodForm(instance=food)

    # Act
    form._add_nutritional_value_fields()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    # Assert
    field_name = f"macronutrients_{macronutrient.name.lower()}"
    assert field_name in form.fields
    assert form.fields[field_name].initial is None


@pytest.mark.django_db
def test_food_form_save_creates_food_and_macronutrient_relations():
    # --- Setup: initial data ---
    protein = Macronutrient.objects.create(name="protein_test")
    fat = Macronutrient.objects.create(name="fat_test")

    # --- Simulated form data ---
    form_data = {
        "barcode": "3229820794556",
        "name": "Test Food",
        "energy_0": 150,
        "energy_1": "kJ",
        f"macronutrients_{protein.name.lower()}_0": 10.5,
        f"macronutrients_{protein.name.lower()}_1": "g",
        f"macronutrients_{fat.name.lower()}_0": "",  # empty field
        f"macronutrients_{fat.name.lower()}_1": "g",
    }

    form = FoodForm(data=form_data)
    assert form.is_valid(), form.errors

    # --- Action ---
    food = form.save()

    # --- Assertions ---
    # 1️⃣ The Food is created successfully
    assert Food.objects.filter(name="Test Food").exists()

    # 2️⃣ The FoodMacronutrient exists for protein only
    fm_relations = FoodMacronutrient.objects.filter(food=food)
    assert fm_relations.count() == 1

    rel: FoodMacronutrient | None = fm_relations.first()
    assert rel is not None
    assert rel.macronutrient == protein
    # NOTE:
    # `amount` is a QuantityField (a subclass of FloatField) that automatically
    # converts the stored float value into a `pint.Quantity` instance when
    # retrieved from the database.
    amount = cast("Quantity", rel.amount)

    # Verify both the numeric value and the unit
    assert amount == Quantity(10.5, ureg.g)

    # 3️⃣ No relation for "fat"
    assert not FoodMacronutrient.objects.filter(food=food, macronutrient=fat).exists()
