from typing import cast
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from crispy_forms.bootstrap import FieldWithButtons
from pint import Quantity
from quantityfield.units import ureg

from products.forms import ProductForm
from products.models import Macronutrient
from products.models import Product
from products.models import ProductMacronutrient


@pytest.mark.django_db
class TestBuildBarcodeField:
    def test_create_mode_returns_fieldwithbuttons(self):
        form = ProductForm(instance=Product())  # pas de pk
        field: FieldWithButtons = form._get_barcode_field_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        assert isinstance(field, FieldWithButtons)

    def test_edit_mode_returns_readonly_field(self):
        product = Product.objects.create(name="Apple", barcode="1234567890123")
        form = ProductForm(instance=product)
        field: FieldWithButtons = form._get_barcode_field_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        # Doit être un Field simple
        assert isinstance(field, FieldWithButtons)

        # Le widget doit être readonly et avec la classe bg-light
        widget_attrs = form.fields["barcode"].widget.attrs
        assert widget_attrs["readonly"] is True


@pytest.mark.django_db
def test_macronutrient_field_initialized_with_existing_amount():
    # Arrange
    product = Product.objects.create(name="Test Product", barcode="1234567890123")
    macronutrient, _ = Macronutrient.objects.get_or_create(name="proteins")

    # Créons une entrée ProductMacronutrient avec un certain amount
    ProductMacronutrient.objects.create(
        product=product,
        macronutrient=macronutrient,
        amount=Quantity(
            value=12.0,
            units=ureg.g,
        ),
    )

    form = ProductForm(instance=product)

    # Act
    form._add_nutritional_value_fields()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    # Assert
    field_name = f"macronutrients_{macronutrient.name.lower()}"
    assert field_name in form.fields
    assert form.fields[field_name].initial == Quantity(value=12, units="g")


@pytest.mark.django_db
def test_macronutrient_field_not_initialized_without_existing_amount():
    # Arrange
    product = Product.objects.create(name="Test Product 2", barcode="9876543210987")
    macronutrient, _ = Macronutrient.objects.get_or_create(name="fat")

    # Pas de ProductMacronutrient créé
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
        "energy_0": 150,
        "energy_1": "kJ",
        f"{protein.name_in_form}_0": 10.5,
        f"{protein.name_in_form}_1": "g",
        f"{fat.name_in_form}_0": "",  # empty field
        f"{fat.name_in_form}_1": "g",
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
    # NOTE:
    # `amount` is a QuantityField (a subclass of FloatField) that automatically
    # converts the stored float value into a `pint.Quantity` instance when
    # retrieved from the database.
    amount = cast("Quantity", rel.amount)

    # Verify both the numeric value and the unit
    assert amount == Quantity(10.5, ureg.g)

    # 3️⃣ No relation for "fat"
    assert not ProductMacronutrient.objects.filter(
        product=product, macronutrient=fat
    ).exists()


@pytest.mark.django_db
def test_product_form_save_updates_existing_productmacronutrient():
    protein = Macronutrient.objects.create(name="protein_test")
    protein.name_in_form = f"macronutrients_{protein.name.lower()}"
    protein.save(update_fields=["name_in_form"])
    product = Product.objects.create(name="Update Test", barcode="3229820794556")

    ProductMacronutrient.objects.create(
        product=product, macronutrient=protein, amount=5.0
    )

    form_data = {
        "barcode": "3229820794556",
        "name": "Update Test",
        "energy_0": 150,
        "energy_1": "kJ",
        f"{protein.name_in_form}_0": 9.0,
        f"{protein.name_in_form}_1": "g",
    }

    form = ProductForm(data=form_data, instance=product)
    assert form.is_valid(), form.errors
    form.save()

    rel = ProductMacronutrient.objects.get(product=product, macronutrient=protein)
    amount = cast("Quantity", rel.amount)
    assert amount == Quantity(9.0, ureg.g)


@pytest.mark.django_db
def test_product_form_save_removes_macronutrient_if_value_missing():
    protein = Macronutrient.objects.create(name="protein_test")
    product = Product.objects.create(name="Delete Test", barcode="3229820794556")

    ProductMacronutrient.objects.create(
        product=product, macronutrient=protein, amount=5.0
    )

    form_data = {
        "barcode": "3229820794556",
        "name": "Delete Test",
        "energy_0": 150,
        "energy_1": "kJ",
        f"macronutrients_{protein.name.lower()}_0": "",  # empty value = remove relation
    }

    form = ProductForm(data=form_data, instance=product)
    assert form.is_valid(), form.errors
    form.save()

    assert not ProductMacronutrient.objects.filter(
        product=product,
        macronutrient=protein,
    ).exists()


@pytest.mark.django_db
def test_save_with_fetched_image_and_delete():
    """Test save fetches image, deletes existing file, and assigns new image."""

    path = "images/products/3242272270157.jpg"

    with (
        patch("products.forms.requests.get") as mock_requests_get,
        patch("django.core.files.storage.FileSystemStorage.exists") as mock_exists,
        patch("django.core.files.storage.FileSystemStorage.delete") as mock_delete,
        patch("django.core.files.storage.FileSystemStorage.save") as mock_save,
    ):
        # --- Mock HTTP response ---
        mock_response = Mock()
        mock_response.content = b"fake image bytes"
        mock_response.raise_for_status = Mock()
        mock_requests_get.return_value = mock_response

        # --- Mock storage ---
        mock_exists.return_value = True  # simulate file already exists
        mock_save.return_value = path

        # --- Form with minimal valid data ---
        form = ProductForm(
            data={
                "barcode": "3242272270157",
                "name": "Apple",
                "energy_0": 100,
                "energy_1": "kJ",
            }
        )
        form.extra_data = {"fetched_image_url": "https://example.com/apple.jpg"}
        form.full_clean()

        # --- Call save ---
        product: Product = form.save(commit=True)

        # --- Assertions ---
        mock_requests_get.assert_called_once_with(
            "https://example.com/apple.jpg", timeout=10
        )
        mock_exists.assert_called_once_with(path)  # check exists called
        mock_delete.assert_called_once_with(path)  # check delete called
        mock_save.assert_called_once()  # file was saved
        assert product.image.name == path
