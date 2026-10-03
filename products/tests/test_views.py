import io
import json
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http.response import HttpResponse
from django.test import Client
from django.urls import reverse
from django.utils import translation
from PIL import Image

from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory
from products.api.openfoodfacts.schemas import OFFIngredientSchema
from products.api.openfoodfacts.schemas import OFFMacronutrientsSchema
from products.api.openfoodfacts.schemas import OFFProductSchema
from products.api.openfoodfacts.services import OFFError
from products.api.openfoodfacts.services import OFFProductNotFoundError
from products.api.schemas.inbound import IngredientInput
from products.api.schemas.inbound import ProductCreate
from products.forms import ProductForm
from products.models import Ingredient
from products.models import IngredientRef
from products.models import Product
from products.services.product_services import create_product
from products.views import ingredient_rows_from_db
from products.views import ingredient_rows_from_inputs

if TYPE_CHECKING:
    from django.http.response import HttpResponse


NUTELLA = "3017620422003"
IMAGE_URL = (
    "https://images.openfoodfacts.org/images/products/301/762/042/2003/front.jpg"
)


def off_product(**overrides: Any) -> OFFProductSchema:
    data: dict[str, Any] = {
        "barcode": NUTELLA,
        "name": "Nutella",
        "image_url": IMAGE_URL,
        "energy_kj": 2252,
        "macronutrients": OFFMacronutrientsSchema(fat=30.9, sugars=56.3),
        "ingredients": [
            OFFIngredientSchema(name="Sucre", percentage=56.3),
            OFFIngredientSchema(
                name="Lait", ingredients=[OFFIngredientSchema(name="lait écrémé")]
            ),
        ],
    }
    data.update(overrides)
    return OFFProductSchema(**data)


def submitted(form: ProductForm, **changes: Any) -> dict[str, Any]:
    """What a browser posts back for this form, hidden fields included."""
    data = {
        name: "" if form[name].value() is None else form[name].value()
        for name in form.fields
        if name != "photo"
    }
    data.update(changes)
    return data


def png_upload(name: str = "mine.png") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.fixture(autouse=True)
def _signed_in(client: Client, user: User) -> None:  # pyright: ignore[reportUnusedFunction]
    """Every product page needs a signed-in user; tests opt out explicitly."""
    client.force_login(user)


def ok_image_response() -> MagicMock:
    response = MagicMock()
    response.content = b"jpeg-bytes"
    response.headers = {"Content-Type": "image/jpeg"}
    return response


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

        props: dict[str, Any] = response.context["product_list_props"]
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
        rows themselves now come from /api/v1/products/.
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
    @patch("products.views.fetch_from_off")
    def test_unknown_barcode_keeps_the_form_usable(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        """
        A barcode OpenFoodFacts does not know is not a server fault: the page
        comes back with the barcode filled in and a notice telling the user to
        enter the rest by hand.
        """
        mock_fetch_from_off.side_effect = OFFProductNotFoundError("Product not found.")

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": "322982079455"}
        )

        assert response.status_code == 200  # noqa: PLR2004
        assert response.context["form"].initial == {"barcode": "322982079455"}
        notices = [str(m) for m in response.context["messages"]]
        assert any("was not found in OpenFoodFacts" in n for n in notices), notices

    @patch("products.views.fetch_from_off")
    def test_off_failure_notice_is_translated(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        """
        The notices were added without running makemessages, so French users
        got them in English. Guards against a notice missing from the .po.
        """
        mock_fetch_from_off.side_effect = OFFProductNotFoundError("Product not found.")

        with translation.override("fr-fr"):
            response: HttpResponse = client.get(
                reverse("create_product"),
                {"barcode": "322982079455"},
                headers={"accept-language": "fr"},
            )

        notices = [str(m) for m in response.context["messages"]]
        assert any("est introuvable dans OpenFoodFacts" in n for n in notices), notices

    @patch("products.api.openfoodfacts.services.requests.get")
    def test_off_answering_another_barcode_keeps_the_form_usable(
        self, mock_get: MagicMock, client: Client
    ):
        """
        OFF answering with a different product used to raise a ValueError that
        the view does not catch, so the page was a 500. It now reads as an
        unknown barcode. Only the HTTP call is mocked: the real fetch_from_off
        runs, which is where the error type is decided.
        """
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "status": "success",
            "result": {"id": "product_found", "name": "Product found"},
            "product": {"code": "7613032637620", "product_name": "Other"},
        }

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": "3229820794556"}
        )

        assert response.status_code == 200  # noqa: PLR2004
        assert response.context["form"].initial == {"barcode": "3229820794556"}
        notices = [str(m) for m in response.context["messages"]]
        assert any("was not found in OpenFoodFacts" in n for n in notices), notices

    @patch("products.views.fetch_from_off")
    def test_unreachable_api_keeps_the_form_usable(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        """An upstream outage is reported differently from a missing product."""
        mock_fetch_from_off.side_effect = OFFError("External API unreachable")

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": "322982079455"}
        )

        assert response.status_code == 200  # noqa: PLR2004
        notices = [str(m) for m in response.context["messages"]]
        assert any("could not be reached" in n for n in notices), notices

    def test_get_form_without_barcode(self, client: Client):
        with patch("products.views.fetch_from_off") as fetch:
            response: HttpResponse = client.get(reverse("create_product"))

        fetch.assert_not_called()
        assert response.context["form"].initial == {}

    @patch("products.views.fetch_from_off")
    def test_lookup_fills_the_form_and_the_hidden_fields(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product()

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        form: ProductForm = response.context["form"]
        mock_fetch_from_off.assert_called_once_with(query_barcode=NUTELLA)
        assert form["name"].value() == "Nutella"
        assert form["macronutrients_sugars"].value() == 56.3  # noqa: PLR2004
        assert form["off_barcode"].value() == NUTELLA
        assert form["off_image_url"].value() == IMAGE_URL
        carried = json.loads(form["off_ingredients"].value())
        assert [i["name"] for i in carried] == ["Sucre", "Lait"]
        rows = response.context["ingredient_rows"]
        assert [r["name"] for r in rows] == ["Sucre", "Lait"]
        assert rows[1]["ingredients"][0]["name"] == "lait écrémé"

    @patch("products.services.product_services.requests.get")
    @patch("products.views.fetch_from_off")
    def test_save_stores_what_the_lookup_showed_without_asking_off_again(
        self, mock_fetch_from_off: MagicMock, mock_get: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product()
        mock_get.return_value = ok_image_response()
        url = f"{reverse('create_product')}?barcode={NUTELLA}"
        form = client.get(url).context["form"]
        mock_fetch_from_off.reset_mock()

        # The form posts back to the same URL, query string included.
        response: HttpResponse = client.post(url, submitted(form))

        assert response.status_code == HTTPStatus.FOUND
        mock_fetch_from_off.assert_not_called()
        product = Product.objects.get(pk=NUTELLA)
        assert product.name == "Nutella"
        assert list(
            product.ingredients.filter(parent=None).values_list("name", flat=True)
        ) == ["Sucre", "Lait"]
        assert mock_get.call_args.args == (IMAGE_URL,)
        assert product.image.name == f"images/products/{NUTELLA}.jpg"

    @patch("products.services.product_services.requests.get")
    @patch("products.views.fetch_from_off")
    def test_changing_the_barcode_after_the_lookup_drops_what_it_returned(
        self, mock_fetch_from_off: MagicMock, mock_get: MagicMock, client: Client
    ):
        """Otherwise one product's ingredients and photo end up on another."""
        mock_fetch_from_off.return_value = off_product()
        url = f"{reverse('create_product')}?barcode={NUTELLA}"
        form = client.get(url).context["form"]

        client.post(url, submitted(form, barcode="3229820794556"))

        product = Product.objects.get(pk="3229820794556")
        assert product.name == "Nutella"  # what the user typed is kept
        assert not product.ingredients.exists()
        assert not product.image
        mock_get.assert_not_called()

    @patch("products.services.product_services.requests.get")
    @patch("products.views.fetch_from_off")
    def test_an_uploaded_photo_wins_over_the_fetched_one(
        self, mock_fetch_from_off: MagicMock, mock_get: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product()
        url = f"{reverse('create_product')}?barcode={NUTELLA}"
        form = client.get(url).context["form"]

        client.post(url, {**submitted(form), "photo": png_upload()})

        mock_get.assert_not_called()
        product = Product.objects.get(pk=NUTELLA)
        assert product.image.name == f"images/products/{NUTELLA}.png"

    def test_tampered_ingredients_are_reported_not_saved(self, client: Client):
        form = client.get(reverse("create_product")).context["form"]
        data = submitted(
            form,
            barcode=NUTELLA,
            name="Nutella",
            energy_kj=1,
            off_barcode=NUTELLA,
            off_ingredients="not json",
        )

        response: HttpResponse = client.post(reverse("create_product"), data)

        assert response.status_code == HTTPStatus.OK
        assert response.context["form"].non_field_errors()
        assert not Product.objects.filter(pk=NUTELLA).exists()


@pytest.mark.django_db
class TestProductEditView:
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
        mock_fetch_from_off.side_effect = OFFProductNotFoundError("Product not found.")

        response: HttpResponse = client.get(
            reverse("edit_product", args=[product.pk]), {"reset": "1"}
        )

        assert response.status_code == 200  # noqa: PLR2004
        assert response.context["form"].instance.name == "Stored Product"
        notices = [str(m) for m in response.context["messages"]]
        assert any("was not found in OpenFoodFacts" in n for n in notices), notices

    def test_plain_edit_leaves_the_ingredients_alone(self, client: Client):
        """Saving used to delete and recreate every ingredient, every time."""
        product = create_product(
            ProductCreate.model_validate(
                {
                    "barcode": NUTELLA,
                    "name": "Nutella",
                    "nutritional_values": {"energy_kj": 1},
                    "ingredients": [{"name": "Sucre"}, {"name": "Cacao"}],
                }
            )
        ).product
        ids = set(product.ingredients.values_list("id", flat=True))
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]

        with patch("products.views.fetch_from_off") as fetch:
            client.post(url, submitted(form, name="Renamed"))

        fetch.assert_not_called()
        product.refresh_from_db()
        assert product.name == "Renamed"
        assert set(product.ingredients.values_list("id", flat=True)) == ids

    @patch("products.services.product_services.requests.get")
    @patch("products.views.fetch_from_off")
    def test_reset_then_save_replaces_ingredients_and_warns_about_the_photo(
        self,
        mock_fetch_from_off: MagicMock,
        mock_get: MagicMock,
        client: Client,
    ):
        """
        The photo lives on a separate OFF host that can time out on its own:
        the product is saved anyway, with a notice to add the photo by hand.
        """
        product = Product.objects.create(
            barcode=NUTELLA, name="Stored Product", energy_kj=10
        )
        mock_fetch_from_off.return_value = off_product()
        mock_get.side_effect = requests.ConnectTimeout("timed out")
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url, {"reset": "1"}).context["form"]
        assert form["off_barcode"].value() == NUTELLA

        response: HttpResponse = client.post(url, submitted(form), follow=True)

        product.refresh_from_db()
        assert product.name == "Nutella"
        assert list(
            product.ingredients.filter(parent=None).values_list("name", flat=True)
        ) == ["Sucre", "Lait"]
        assert not product.image
        notices = [str(m) for m in response.context["messages"]]
        assert any("could not be downloaded" in n for n in notices), notices

    def test_a_tampered_barcode_is_ignored(self, client: Client):
        """The barcode is the primary key: editing must never move a product."""
        product = Product.objects.create(barcode=NUTELLA, name="Nutella", energy_kj=1)
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]

        client.post(url, submitted(form, barcode="3229820794556", name="Renamed"))

        assert Product.objects.get(pk=NUTELLA).name == "Renamed"
        assert not Product.objects.filter(pk="3229820794556").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", ["list_products", "create_product"])
def test_product_pages_send_anonymous_visitors_to_sign_in(url_name: str):
    url = reverse(url_name)

    response: HttpResponse = Client().get(url)

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == f"{reverse('account_login')}?next={url}"


@pytest.mark.django_db
def test_the_list_offers_delete_to_staff_only(client: Client):
    url = reverse("list_products")
    assert client.get(url).context["product_list_props"]["canDelete"] is False

    client.force_login(UserFactory(is_staff=True))
    assert client.get(url).context["product_list_props"]["canDelete"] is True


@pytest.mark.django_db
class TestProductDeleteView:
    @pytest.fixture(autouse=True)
    def _staff(self, client: Client) -> None:
        client.force_login(UserFactory(is_staff=True))

    def test_signed_in_non_staff_cannot_delete(self, user: User):
        """The catalogue is shared by every user."""
        product = Product.objects.create(barcode=NUTELLA, name="N", energy_kj=1)
        client = Client()
        client.force_login(user)

        response: HttpResponse = client.post(reverse("delete_product", args=[NUTELLA]))

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert Product.objects.filter(pk=product.pk).exists()

    def test_get_is_not_allowed(self, client: Client):
        """
        Deleting is a POST from the product list, which asks for confirmation
        client-side; there is no confirmation page to GET. Rendering one used
        to crash with TemplateDoesNotExist.
        """
        product = Product.objects.create(
            barcode="3229820794556", name="Apple", energy_kj=100
        )
        url = reverse("delete_product", kwargs={"pk": product.pk})

        response: HttpResponse = client.get(url)

        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
        assert Product.objects.filter(pk=product.pk).exists()

    def test_post_deletes_and_redirects_to_the_list(self, client: Client):
        product = Product.objects.create(
            barcode="3229820794556", name="Apple", energy_kj=100
        )
        url = reverse("delete_product", kwargs={"pk": product.pk})

        response: HttpResponse = client.post(url)

        assert response.status_code == HTTPStatus.FOUND
        assert response["Location"] == reverse("list_products")
        assert not Product.objects.filter(pk=product.pk).exists()


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
def test_product_form_pages_hand_labels_to_the_scripts(
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
    # form-entry.js reads its translated strings from this json_script blob
    # and has no other configuration to receive from the server.
    assert 'id="product-form-labels"' in response.content.decode()


@pytest.mark.django_db
def test_rows_from_inputs_mark_references_regardless_of_case():
    """Same matching as the services use to link them (see their tests)."""
    items = [IngredientInput(name="Sucre"), IngredientInput(name="Farine")]

    rows = ingredient_rows_from_inputs(items, reference_names={"sucre"})

    assert [(r["name"], r["has_reference"]) for r in rows] == [
        ("Sucre", True),
        ("Farine", False),
    ]


@pytest.mark.django_db
def test_rows_from_db_rebuild_the_tree(django_assert_num_queries: Any):
    IngredientRef.objects.create(name="lait")
    product = create_product(
        ProductCreate.model_validate(
            {
                "barcode": NUTELLA,
                "name": "Nutella",
                "nutritional_values": {"energy_kj": 1},
                "ingredients": [
                    {"name": "Sucre", "percentage": "56.3"},
                    {"name": "Lait en poudre", "sub_ingredients": [{"name": "Lait"}]},
                ],
            }
        )
    ).product

    with django_assert_num_queries(1):
        rows = ingredient_rows_from_db(product)

    assert [r["name"] for r in rows] == ["Sucre", "Lait en poudre"]
    assert rows[0]["ingredients"] is None
    assert [(c["name"], c["has_reference"]) for c in rows[1]["ingredients"]] == [
        ("Lait", True)
    ]
    assert Ingredient.objects.filter(product=product).count() == 3  # noqa: PLR2004
