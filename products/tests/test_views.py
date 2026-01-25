import json
from typing import TYPE_CHECKING
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.test import Client
from django.test import RequestFactory
from django.urls import reverse
from pint import Quantity

from products.base_schema import MacronutrientsSchema
from products.base_schema import ProductSchema
from products.forms import ProductForm
from products.models import IngredientRef
from products.models import Product
from products.openfoodfacts.schema import OFFIngredientSchema
from products.openfoodfacts.schema import OFFProductSchema
from products.openfoodfacts.schema import product_schema_to_form_data
from products.views import ProductCreateView  # adapte à ton module
from products.views import ProductEditView  # adapte à ton module
from products.views import prepare_product_form_data  # adapte à ton module

if TYPE_CHECKING:
    from django.http.response import HttpResponse


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
        mock_fetch_product_data.assert_called_once_with(query_barcode="123456")

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


def build_view_url(viewname: str, product: Product | None = None) -> str:
    if viewname == "create_product":
        return reverse(viewname=viewname)
    if viewname == "edit_product":
        assert product is not None
        return reverse(viewname=viewname, args=[product.pk])

    msg = f"Unsupported viewname: {viewname}"
    raise ValueError(msg)


@pytest.mark.django_db
@pytest.mark.parametrize("viewname", ["create_product", "edit_product"])
def test_product_views_context_contains_macronutrients_url(
    client: Client,
    viewname: str,
) -> None:
    product: Product | None = None
    if viewname == "edit_product":
        product = Product.objects.create(
            barcode="1234567890123",
            name="Test Product",
        )

    url: str = build_view_url(viewname, product)

    response: HttpResponse = client.get(path=url)

    assert response.status_code == 200  # noqa: PLR2004
    assert response.context is not None
    assert "macronutrients_api_url" in response.context

    expected_url: str = reverse(viewname="api-1.0.0:get_macronutrients_form_data")
    assert response.context["macronutrients_api_url"] == expected_url


@pytest.mark.django_db
def test_reference_names_loaded_in_single_query(django_assert_num_queries: Any) -> None:
    IngredientRef.objects.create(name="Sugar")
    IngredientRef.objects.create(name="Salt")

    with django_assert_num_queries(1):
        _ = {
            name.lower()
            for name in IngredientRef.objects.values_list("name", flat=True)
        }


@pytest.mark.django_db
def test_prepare_product_form_data_with_fetched_product_and_refs():
    # --- Arrange --- DB refs
    IngredientRef.objects.create(name="Sugar")
    IngredientRef.objects.create(name="Salt")

    # OFFProductSchema avec ingredients
    ingredients = [
        OFFIngredientSchema(name="Sugar"),
        OFFIngredientSchema(name="Flour"),
    ]
    fetched_product = OFFProductSchema(
        barcode="123456",
        name="Test Product",
        ingredients=ingredients,
    )

    # --- Act ---
    _initial, extra_data = prepare_product_form_data(fetched_product=fetched_product)

    # --- Assert ---
    assert "fetched_image_url" in extra_data
    assert "ingredients" in extra_data
    assert "ingredients_json" in extra_data

    payload = json.loads(extra_data["ingredients_json"])
    assert len(payload) == 2  # noqa: PLR2004
    assert payload[0]["name"] == "Sugar"
    assert payload[0]["has_reference"] is True
    assert payload[1]["name"] == "Flour"
    assert payload[1]["has_reference"] is False


def test_prepare_product_form_data_raises_without_arguments():
    # --- Act & Assert ---
    with pytest.raises(
        ValueError, match="Either product_instance or fetched_product must be provided"
    ):
        prepare_product_form_data()
