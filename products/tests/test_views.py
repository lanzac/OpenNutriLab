import json
from typing import TYPE_CHECKING
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.http.response import HttpResponse
from django.test import Client
from django.test import RequestFactory
from django.urls import reverse
from pint import Quantity
from quantityfield.units import ureg

from products.api.openfoodfacts.schemas import OFFIngredientSchema
from products.api.openfoodfacts.schemas import OFFMacronutrientsSchema
from products.api.openfoodfacts.schemas import OFFProductSchema
from products.api.openfoodfacts.schemas import product_schema_to_form_data
from products.forms import ProductForm
from products.models import IngredientRef
from products.models import Product
from products.views import PRODUCT_LIST_FIELDS
from products.views import ProductCreateView  # adapte à ton module
from products.views import ProductEditView  # adapte à ton module
from products.views import prepare_product_form_data  # adapte à ton module

if TYPE_CHECKING:
    from django.http.response import HttpResponse


@pytest.mark.django_db
class TestProductListView:
    def test_context_data_contains_product_list_json(self, client: Client):
        """
        Test that ProductListView adds 'product_list_json' to the context
        with the specific fields requested for the JS table.
        """
        # --- Setup: Create test data ---
        Product.objects.create(
            barcode="1111111111111",
            name="Apple",
            group_level_1="Fruits",
            group_level_2="Fresh",
            description="A beautiful apple",
            energy=Quantity(100, ureg.kJ),
        )
        Product.objects.create(
            barcode="2222222222222",
            name="Bread",
            group_level_1="Bakery",
            group_level_2="White bread",
            description="Traditional baguette",
            energy=Quantity(100, ureg.kJ),
        )

        # --- Action: Call the view via its URL ---
        url: str = reverse("list_products")
        response: HttpResponse = client.get(url)

        # --- Assertions ---
        assert response.status_code == 200  # noqa: PLR2004

        # Verify the custom key is present
        assert "product_list_json" in response.context

        json_data = response.context["product_list_json"]

        # Verify it is a list and contains the correct number of elements
        assert isinstance(json_data, list)
        assert len(json_data) == 2  # noqa: PLR2004  # pyright: ignore[reportUnknownArgumentType]

        # Verify fields of the first item
        # We expect .values() to return a dict
        item = json_data[0]  # pyright: ignore[reportUnknownVariableType]

        expected_fields = set(PRODUCT_LIST_FIELDS)

        # Verify that dictionary keys correspond exactly to requested fields
        # Note: .values() does not return ID if not explicitly requested
        assert set(item.keys()) == expected_fields  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]

        # Verify that NOT requested fields (like 'description' or 'barcode') are absent
        assert "description" not in item
        assert "barcode" not in item

        # Verify content (sort by name to ensure order)
        sorted_data = sorted(json_data, key=lambda x: x["name"])  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType, reportUnknownLambdaType]

        assert sorted_data[0]["name"] == "Apple"
        assert sorted_data[0]["group_level_1"] == "Fruits"

        assert sorted_data[1]["name"] == "Bread"
        assert sorted_data[1]["group_level_1"] == "Bakery"

    def test_context_data_empty_list(self, client: Client):
        """Test behavior when there are no products."""
        url: str = reverse("list_products")
        response: HttpResponse = client.get(url)

        assert response.status_code == 200  # noqa: PLR2004
        assert "product_list_json" in response.context
        assert response.context["product_list_json"] == []


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

    @patch("products.views.fetch_from_off")
    def test_get_form_with_barcode(self, mock_fetch_product_data: MagicMock):
        """The form should be pre-filled when a barcode is provided."""

        # --- Create a realistic ProductSchema instance ---
        mock_product_schema: OFFProductSchema = OFFProductSchema(
            barcode="123456",
            name="Apple",
            image_url="https://example.com/apple.jpg",
            macronutrients=OFFMacronutrientsSchema(
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
            "group_level_1": "",
            "group_level_2": "",
        }
        assert form.initial == expected_form

    @pytest.mark.django_db
    @patch("products.views.fetch_from_off")
    def test_get_form_with_reset(self, mock_fetch_product_data: MagicMock):
        product = Product.objects.create(
            barcode="1234567890123",
            name="Test Product",
            description="obsolete description",
            energy=Quantity(10.0, "kJ"),
        )

        # --------------------------------------------------------------------
        # --- Create a realistic ProductSchema instance ---
        mock_product_schema: OFFProductSchema = OFFProductSchema(
            barcode="1234567890123",
            name="Test",
            image_url="https://example.com/apple.jpg",
            macronutrients=OFFMacronutrientsSchema(
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
            energy=Quantity(100, ureg.kJ),
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


@pytest.mark.django_db
def test_prepare_product_form_data_raises_without_arguments():
    # --- Act & Assert ---
    with pytest.raises(
        ValueError, match="Either product_instance or fetched_product must be provided"
    ):
        prepare_product_form_data()
