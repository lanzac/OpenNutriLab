import json
from typing import TYPE_CHECKING
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from django.http.response import HttpResponse
from django.test import Client
from django.test import RequestFactory
from django.urls import reverse
from django.utils import translation
from ninja.errors import HttpError

from products.api.openfoodfacts.schemas import OFFIngredientSchema
from products.api.openfoodfacts.schemas import OFFMacronutrientsSchema
from products.api.openfoodfacts.schemas import OFFProductSchema
from products.api.openfoodfacts.schemas import product_schema_to_form_data
from products.forms import ProductForm
from products.models import IngredientRef
from products.models import Product
from products.views import ProductCreateView  # adapte à ton module
from products.views import ProductEditView  # adapte à ton module
from products.views import prepare_product_form_data  # adapte à ton module

if TYPE_CHECKING:
    from django.http.response import HttpResponse


@pytest.mark.django_db
class TestProductListView:
    def test_context_data_contains_translated_labels(self, client: Client):
        """
        The React inventory table gets its user-facing strings from the
        context (see frontend/src/apps/products/ProductListApp.jsx), so the
        .po catalogue stays the single source of truth. Guards against the
        labels drifting back to hardcoded English in the JSX.
        """
        url: str = reverse("list_products")

        with translation.override("fr-fr"):
            response: HttpResponse = client.get(url, headers={"accept-language": "fr"})

        assert response.status_code == 200  # noqa: PLR2004

        props: dict[str, object] = response.context["product_list_props"]
        labels: dict[str, str] = props["labels"]
        assert labels["productName"] == "Nom du produit"
        assert labels["createdAt"] == "Créé le"
        assert labels["edit"] == "Éditer"
        assert labels["delete"] == "Supprimer"
        assert labels["loading"] == "Chargement…"
        # The name is interpolated client-side, so the placeholder must survive.
        assert "%(name)s" in labels["confirmDelete"]

        # Intl needs the negotiated language or it falls back to the browser's.
        assert props["languageCode"].startswith("fr")

    def test_context_data_carries_the_csrf_token(self, client: Client):
        """
        CSRF_COOKIE_HTTPONLY keeps the token out of document.cookie, so the
        React delete form cannot read it client-side and has to be handed it.
        Without this, every delete POST is rejected with a 403.
        """
        url: str = reverse("list_products")
        response: HttpResponse = client.get(url)

        token = response.context["product_list_props"]["csrfToken"]
        assert token
        assert token in response.content.decode()

    def test_renders_the_react_mount_point(self, client: Client):
        """
        The React table replaces the server-rendered one, so what the template
        owes it is a mount point and the labels blob. Products exist here only
        to prove the page still renders once the queryset is non-empty - the
        rows themselves now come from /api-ninja/products/.
        """
        Product.objects.create(
            barcode="1111111111111",
            name="Apple",
            group_level_1="Fruits",
            group_level_2="Fresh",
            description="A beautiful apple",
            energy_kj=100,
        )

        url: str = reverse("list_products")
        response: HttpResponse = client.get(url)
        html: str = response.content.decode()

        assert response.status_code == 200  # noqa: PLR2004
        assert 'id="product-list-root"' in html
        assert 'id="product-list-props"' in html
        # @vitejs/plugin-react aborts with "can't detect preamble" unless the
        # React Refresh runtime is injected ahead of the entry point, and React
        # then never mounts at all. Invisible to jsdom, which does not run the
        # plugin's browser-side check.
        assert "@react-refresh" in html
        assert html.index("@react-refresh") < html.index("list-entry.jsx")
        # The table is no longer server-rendered.
        assert "Apple" not in html


@pytest.mark.django_db
class TestProductCreateView:
    def setup_method(self):
        self.factory = RequestFactory()

    @patch("products.views.fetch_from_off")
    def test_unknown_barcode_keeps_the_form_usable(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        """
        A barcode OpenFoodFacts does not know used to 500: fetch_from_off
        raises django-ninja's HttpError, which only becomes a response inside
        an API route. The page must instead come back with the barcode filled
        in and a notice telling the user to enter the rest by hand.
        """
        mock_fetch_from_off.side_effect = HttpError(404, "Product not found.")

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": "322982079455"}
        )

        assert response.status_code == 200  # noqa: PLR2004
        assert response.context["form"].initial == {"barcode": "322982079455"}
        notices = [str(m) for m in response.context["messages"]]
        assert any("was not found in OpenFoodFacts" in n for n in notices), notices

    @patch("products.views.fetch_from_off")
    def test_unreachable_api_keeps_the_form_usable(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        """An upstream outage is reported differently from a missing product."""
        mock_fetch_from_off.side_effect = HttpError(503, "External API unreachable")

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": "322982079455"}
        )

        assert response.status_code == 200  # noqa: PLR2004
        notices = [str(m) for m in response.context["messages"]]
        assert any("could not be reached" in n for n in notices), notices

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

    @patch("products.views.fetch_from_off")
    def test_failed_reset_falls_back_to_stored_values(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        """
        `?reset=1` on a product OFF has since dropped must not 500. The form
        keeps the values already in the database and says why nothing changed.
        """
        product = Product.objects.create(
            barcode="1234567890123",
            name="Stored Product",
            energy_kj=10,
        )
        mock_fetch_from_off.side_effect = HttpError(404, "Product not found.")

        response: HttpResponse = client.get(
            reverse("edit_product", args=[product.pk]), {"reset": "1"}
        )

        assert response.status_code == 200  # noqa: PLR2004
        assert response.context["form"].instance.name == "Stored Product"
        notices = [str(m) for m in response.context["messages"]]
        assert any("was not found in OpenFoodFacts" in n for n in notices), notices

    @patch("products.forms.requests.get")
    @patch("products.views.fetch_from_off")
    def test_save_after_reset_warns_when_image_host_is_unreachable(
        self,
        mock_fetch_from_off: MagicMock,
        mock_forms_requests_get: MagicMock,
        client: Client,
    ):
        """
        The image lives on a separate OFF host from the product API and can
        time out on its own (e.g. a stricter egress allowlist than the API's).
        This used to crash the save with an unhandled ConnectTimeout; it must
        instead save the product and tell the user to add the photo by hand.
        """
        product = Product.objects.create(
            barcode="3229820794556",
            name="Stored Product",
            energy_kj=10,
        )
        mock_fetch_from_off.return_value = OFFProductSchema(
            barcode="3229820794556",
            name="Stored Product",
            image_url="https://images.openfoodfacts.org/apple.jpg",
        )
        mock_forms_requests_get.side_effect = requests.ConnectTimeout("timed out")

        response: HttpResponse = client.post(
            f"{reverse('edit_product', args=[product.pk])}?reset=1",
            {
                "barcode": "3229820794556",
                "name": "Stored Product",
                "energy_kj": 10,
            },
            follow=True,
        )

        assert response.status_code == 200  # noqa: PLR2004
        product.refresh_from_db()
        assert not product.image
        notices = [str(m) for m in response.context["messages"]]
        assert any("could not be downloaded" in n for n in notices), notices

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
            energy_kj=10.0,
        )

        view = ProductEditView()
        view.request = self.factory.get(f"/products/edit/{product.barcode}/")
        form = view.get_form(instance=product)  # pyright: ignore[reportUnknownMemberType]

        assert isinstance(form, ProductForm)

        expected_form = {
            "barcode": "1234567890123",
            "description": "obsolete description",
            "energy_kj": 10.0,
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
            energy_kj=10.0,
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
            energy_kj=100,
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
