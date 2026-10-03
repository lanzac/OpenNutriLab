import json
from decimal import Decimal

import pytest
from crispy_forms.bootstrap import FieldWithButtons

from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.forms import ProductForm
from opennutrilab.products.models import Macronutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductMacronutrient


@pytest.mark.django_db
class TestBuildBarcodeField:
    def test_create_mode_returns_fieldwithbuttons(self):
        form = ProductForm(instance=Product())  # no pk
        field: FieldWithButtons = form._get_barcode_field_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        assert isinstance(field, FieldWithButtons)

    def test_edit_mode_disables_the_barcode(self):
        product = Product.objects.create(
            name="Apple", barcode="1234567890123", energy_kj=100
        )
        form = ProductForm(instance=product)
        field: FieldWithButtons = form._get_barcode_field_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        assert isinstance(field, FieldWithButtons)

        # The barcode is the primary key: Django ignores it once saved.
        assert form.fields["barcode"].disabled is True


@pytest.mark.django_db
def test_macronutrient_field_initialized_with_existing_amount_g():
    # Arrange
    product = Product.objects.create(
        name="Test Product", barcode="1234567890123", energy_kj=100
    )
    macronutrient, _ = Macronutrient.objects.get_or_create(name="proteins")

    # An existing ProductMacronutrient with some amount_g
    ProductMacronutrient.objects.create(
        product=product,
        macronutrient=macronutrient,
        amount_g=12.0,
    )

    form = ProductForm(instance=product)

    # Act
    form._add_nutritional_value_fields()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    # Assert
    field_name = f"macronutrients_{macronutrient.name.lower()}"
    assert field_name in form.fields
    assert form.fields[field_name].initial == 12.0  # noqa: PLR2004


@pytest.mark.django_db
def test_macronutrient_field_not_initialized_without_existing_amount_g():
    # Arrange
    product = Product.objects.create(
        name="Test Product 2", barcode="9876543210987", energy_kj=200
    )
    macronutrient, _ = Macronutrient.objects.get_or_create(name="fat")

    # No ProductMacronutrient created
    form = ProductForm(instance=product)

    # Act
    form._add_nutritional_value_fields()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    # Assert
    field_name = f"macronutrients_{macronutrient.name.lower()}"
    assert field_name in form.fields
    assert form.fields[field_name].initial is None


@pytest.mark.django_db
def test_product_form_save_creates_product_and_macronutrient_relations():
    # --- Setup: initial data ---
    protein = Macronutrient.objects.create(name="protein_test")
    protein.name_in_form = f"macronutrients_{protein.name.lower()}"
    protein.save(update_fields=["name_in_form"])
    fat = Macronutrient.objects.create(name="fat_test")
    fat.name_in_form = f"macronutrients_{fat.name.lower()}"
    fat.save(update_fields=["name_in_form"])

    # --- Simulated form data ---
    form_data = {
        "barcode": "3229820794556",
        "name": "Test Product",
        "energy_kj": 150,
        f"{protein.name_in_form}": 10.5,
        f"{fat.name_in_form}": "",  # empty field
    }

    form = ProductForm(data=form_data)
    assert form.is_valid(), form.errors

    # --- Action ---
    product = form.save()

    # --- Assertions ---
    # 1️⃣ The Product is created successfully
    assert Product.objects.filter(name="Test Product").exists()

    # 2️⃣ The ProductMacronutrient exists for protein only
    fm_relations = ProductMacronutrient.objects.filter(product=product)
    assert fm_relations.count() == 1

    rel: ProductMacronutrient | None = fm_relations.first()
    assert rel is not None
    assert rel.macronutrient == protein
    amount_g: Decimal = rel.amount_g

    # Verify both the numeric value and the unit
    assert amount_g == Decimal("10.5")

    # 3️⃣ No relation for "fat"
    assert not ProductMacronutrient.objects.filter(
        product=product, macronutrient=fat
    ).exists()


@pytest.mark.django_db
def test_product_form_save_updates_existing_productmacronutrient():
    protein = Macronutrient.objects.create(name="protein_test")
    protein.name_in_form = f"macronutrients_{protein.name.lower()}"
    protein.save(update_fields=["name_in_form"])
    product = Product.objects.create(
        name="Update Test", barcode="3229820794556", energy_kj=150
    )

    ProductMacronutrient.objects.create(
        product=product, macronutrient=protein, amount_g=5.0
    )

    form_data = {
        "barcode": "3229820794556",
        "name": "Update Test",
        "energy_kj": 150,
        f"{protein.name_in_form}": 9.0,
    }

    form = ProductForm(data=form_data, instance=product)
    assert form.is_valid(), form.errors
    form.save()

    rel = ProductMacronutrient.objects.get(product=product, macronutrient=protein)
    amount_g: Decimal = rel.amount_g
    assert amount_g == Decimal("9.0")


@pytest.mark.django_db
def test_product_form_save_removes_macronutrient_if_value_missing():
    protein = Macronutrient.objects.get(name="proteins")
    product = Product.objects.create(
        name="Delete Test", barcode="3229820794556", energy_kj=150
    )

    ProductMacronutrient.objects.create(
        product=product, macronutrient=protein, amount_g=5.0
    )

    form_data = {
        "barcode": "3229820794556",
        "name": "Delete Test",
        "energy_kj": 150,
        protein.name_in_form: "",  # empty value = remove relation
    }

    form = ProductForm(data=form_data, instance=product)
    assert form.is_valid(), form.errors
    form.save()

    assert not ProductMacronutrient.objects.filter(
        product=product,
        macronutrient=protein,
    ).exists()


@pytest.mark.django_db
def test_product_form_save_keeps_a_zero_amount():
    # 0 g is a measured value ("no sugar"), unlike an empty field ("unknown"),
    # so it has to be stored rather than treated as missing.
    sugars = Macronutrient.objects.get(name="sugars")
    product = Product.objects.create(
        name="Zero Test", barcode="3229820794556", energy_kj=150
    )
    ProductMacronutrient.objects.create(
        product=product, macronutrient=sugars, amount_g=5.0
    )

    form_data = {
        "barcode": "3229820794556",
        "name": "Zero Test",
        "energy_kj": 150,
        sugars.name_in_form: "0",
    }

    form = ProductForm(data=form_data, instance=product)
    assert form.is_valid(), form.errors
    form.save()

    stored = ProductMacronutrient.objects.get(product=product, macronutrient=sugars)
    assert stored.amount_g == Decimal(0)


@pytest.mark.django_db
def test_off_fields_only_apply_to_the_barcode_they_were_fetched_for():
    off_ingredients = json.dumps([{"name": "Sucre"}])
    base = {"name": "Nutella", "energy_kj": 100, "off_ingredients": off_ingredients}

    matching = ProductForm(
        data={**base, "barcode": "3017620422003", "off_barcode": "3017620422003"}
    )
    other = ProductForm(
        data={**base, "barcode": "3229820794556", "off_barcode": "3017620422003"}
    )

    assert matching.is_valid(), matching.errors
    assert other.is_valid(), other.errors
    assert isinstance(matching.write_data, ProductCreate)
    assert isinstance(other.write_data, ProductCreate)
    assert [i.name for i in matching.write_data.ingredients] == ["Sucre"]
    assert other.write_data.ingredients == []


@pytest.mark.django_db
def test_save_cannot_defer_the_write():
    """The services write the product; there is no unsaved instance to hand back."""
    form = ProductForm(data={"barcode": "3017620422003", "name": "N", "energy_kj": 1})
    assert form.is_valid(), form.errors

    with pytest.raises(ValueError, match="cannot defer"):
        form.save(commit=False)

    assert not Product.objects.exists()
