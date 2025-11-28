from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.test import RequestFactory
from pint import Quantity

from products.base_schema import MacronutrientsSchema
from products.base_schema import ProductSchema
from products.forms import ProductForm
from products.models import Product
from products.openfoodfacts.schema import product_schema_to_form_data
from products.views import ProductCreateView  # adapte à ton module
from products.views import ProductEditView  # adapte à ton module


@pytest.mark.django_db
class TestProductCreateView:
    def setup_method(self):
        self.factory = RequestFactory()

    def test_get_form_without_barcode(self):
        """Le formulaire doit être vide si aucun code-barres n'est fourni."""
        request = self.factory.get("/products/new/")
        view = ProductCreateView()
        view.request = request

        form = view.get_form()  # pyright: ignore[reportUnknownMemberType]

        assert isinstance(form, ProductForm), (
            "Le formulaire retourné n'est pas une instance de ProductForm"
        )
        assert form.initial == {}, (
            f"Le formulaire initial n'est pas vide : {form.initial}"
        )

    @patch("products.views.fetch_product")
    def test_get_form_with_barcode(self, mock_fetch_product_data: MagicMock):
        """The form should be pre-filled when a barcode is provided."""

        # --- Create a realistic ProductSchema instance ---
        mock_product_schema: ProductSchema[MacronutrientsSchema, Any] = ProductSchema(
            barcode="123456",
            name="Apple",
            image_url="https://example.com/apple.jpg",
            macronutrients=MacronutrientsSchema(
                fat=3.0,
                proteins=1.5,
            ),
        )

        # fetch_product_data() should return this schema instance
        mock_fetch_product_data.return_value = mock_product_schema

        # --- Create the request and assign it to the view ---
        request = self.factory.get("/products/create/?barcode=123456")
        view = ProductCreateView()
        view.request = request

        # --- Call the method under test ---
        form = view.get_form()  # pyright: ignore[reportUnknownMemberType]

        # --- Assertions ---
        mock_fetch_product_data.assert_called_once_with("123456")

        expected_initial = product_schema_to_form_data(mock_product_schema).dict()
        assert form.initial == expected_initial, (
            f"Expected initial={expected_initial}, got {form.initial}"
        )

        assert (
            form.extra_data.get("fetched_image_url") == "https://example.com/apple.jpg"
        )

        # Optional: ensure the form type is correct
        assert isinstance(form, ProductForm)


@pytest.mark.django_db
class TestProductEditView:
    def setup_method(self):
        self.factory = RequestFactory()

    def test_get_form_raises_without_instance(self):
        view = ProductEditView()
        view.request = self.factory.get("/fake-url/")
        # `match` performs a substring/regex search, so it passes as long as the text
        # is contained in the exception message.
        with pytest.raises(ValueError, match="Product instance is required"):
            view.get_form()  # pyright: ignore[reportUnknownMemberType]

    # @patch("products.views.fetch_product_data")
    # def test_get_form
    def test_get_form_without_reset(self):
        product = Product.objects.create(
            barcode="1234567890123",
            name="Test Product",
            description="obsolete description",
            energy=Quantity(10.0, "kJ"),
        )

        view = ProductEditView()
        view.request = self.factory.get(f"/products/edit/{product.barcode}/")
        form = view.get_form(instance=product)  # pyright: ignore[reportUnknownMemberType]

        assert isinstance(form, ProductForm)

        expected_form = {
            "barcode": "1234567890123",
            "description": "obsolete description",
            "energy": Quantity(10.0, "kilojoule"),
            "image": None,
            "name": "Test Product",
        }
        assert form.initial == expected_form

    @pytest.mark.django_db
    @patch("products.views.fetch_product")
    def test_get_form_with_reset(self, mock_fetch_product_data: MagicMock):
        product = Product.objects.create(
            barcode="1234567890123",
            name="Test Product",
            description="obsolete description",
            energy=Quantity(10.0, "kJ"),
        )

        # --------------------------------------------------------------------
        # --- Create a realistic ProductSchema instance ---
        mock_product_schema: ProductSchema[MacronutrientsSchema, Any] = ProductSchema(
            barcode="1234567890123",
            name="Test",
            image_url="https://example.com/apple.jpg",
            macronutrients=MacronutrientsSchema(
                fat=3.0,
                proteins=1.5,
            ),
        )

        # fetch_product_data() should return this schema instance
        mock_fetch_product_data.return_value = mock_product_schema

        view = ProductEditView()
        view.request = RequestFactory().get(
            f"/products/edit/{product.barcode}/?reset=1"
        )

        form = view.get_form(instance=product)  # pyright: ignore[reportUnknownMemberType]

        # --------------------------------------------------------------------
        expected_initial = product_schema_to_form_data(mock_product_schema).dict()
        expected_initial["image"] = None
        assert form.initial == expected_initial, (
            f"Expected initial={expected_initial}, got {form.initial}"
        )

        assert isinstance(form.extra_data, dict), (
            f"Expected dict, got {type(form.extra_data)}"
        )
        assert (
            form.extra_data.get("fetched_image_url") == "https://example.com/apple.jpg"
        )

        # Optional: ensure the form type is correct
        assert isinstance(form, ProductForm)
