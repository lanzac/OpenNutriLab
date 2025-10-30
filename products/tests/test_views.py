from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.test import RequestFactory

from products.forms import ProductForm
from products.schema import MacronutrientsSchema
from products.schema import ProductSchema
from products.schema import product_schema_to_form_data
from products.views import ProductCreateView  # adapte à ton module


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

    @patch("products.views.fetch_product_data")
    def test_get_form_with_barcode(self, mock_fetch_product_data: MagicMock):
        """The form should be pre-filled when a barcode is provided."""

        # --- Create a realistic ProductSchema instance ---
        mock_product_schema = ProductSchema(
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

        expected_extra = {"fetched_image_url": "https://example.com/apple.jpg"}
        assert form.extra_data == expected_extra, (
            f"Expected extra_data={expected_extra}, got {form.extra_data}"
        )

        # Optional: ensure the form type is correct
        assert isinstance(form, ProductForm)
