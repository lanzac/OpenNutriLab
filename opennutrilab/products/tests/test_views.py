import io
import json
import re
from decimal import Decimal
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
from pytest_django.fixtures import SettingsWrapper

from opennutrilab.products.api.openfoodfacts.schemas import OFFProductSchema
from opennutrilab.products.api.openfoodfacts.schemas import OFFSearchHitSchema
from opennutrilab.products.api.openfoodfacts.services import OFFError
from opennutrilab.products.api.openfoodfacts.services import OFFProductNotFoundError
from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.forms import ProductForm
from opennutrilab.products.forms import nutrient_field
from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import InventoryItem
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.product_services import create_product
from opennutrilab.products.views import ingredient_rows_from_db
from opennutrilab.products.views import ingredient_rows_from_inputs
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory

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
        "nutriments": {"energy_100g": 2252, "fat_100g": 30.9, "sugars_100g": 56.3},
        "ingredients_text": "Sucre 56,3 %, lait (lait écrémé)",
        "ingredients_lc": "fr",
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
        assert labels["createdAt"] == "Créé le"
        assert labels["loading"] == "Chargement…"
        # The name is interpolated client-side, so the placeholder must survive.
        assert "%(name)s" in labels["confirmDelete"]
        assert labels["myInventory"] == "Mon inventaire"
        assert labels["addToInventory"] == "Ajouter à mon inventaire"
        assert labels["barcode"] == "Code barre"
        # The line of a product, and its sheet.
        assert labels["stockInStock"] == "en stock"
        assert labels["stockNotCountedRow"] == "Stock non compté"
        assert labels["searchProducts"] == "Rechercher un produit"
        assert labels["filterUsedUp"] == "Épuisés"
        assert labels["openSheet"] == "Ouvrir la fiche complète"
        assert labels["deleteFromCatalogue"] == "Supprimer du catalogue…"
        # Figures put in client-side, so their places must survive.
        assert "%(date)s" in labels["stockCountedOn"]
        assert "%(noun)s" in labels["stockAddOne"]
        assert "%(amount)s" in labels["stockEquivalent"]
        assert "%(package)s" in labels["stockOnePackage"]
        # None is left in English: every label has a French entry of its own.
        assert all(labels.values())
        assert labels["uncategorised"] == "Non classé"
        # The groups are stored as OpenFoodFacts words them, and shown in French.
        group_names: dict[str, str] = props["groupNames"]
        assert group_names["Cereals and potatoes"] == "Céréales et pommes de terre"
        assert group_names["Fish Meat Eggs"] == "Viandes, poissons et œufs"
        assert group_names["Bread"] == "Pain"
        assert props["placeholderImage"].endswith("milk-carton-svgrepo-com.png")

        # Intl needs the negotiated language or it falls back to the browser's.
        assert props["languageCode"].startswith("fr")

    def test_context_data_carries_the_labels_of_the_scanner(self, client: Client):
        """
        The camera scanner (frontend/src/apps/products/scan/) reads every message
        it shows from the labels, translated here. A key missing from them would
        show as an empty line on a phone, so each one the scanner reads is
        checked, in French, and the figures it fills in client-side must survive.
        """
        with translation.override("fr-fr"):
            response: HttpResponse = client.get(
                reverse("list_products"), headers={"accept-language": "fr"}
            )

        labels: dict[str, str] = response.context["product_list_props"]["labels"]
        assert labels["scanProduct"] == "Scanner un produit"
        assert labels["scanClose"] == "Fermer le scanner"
        assert labels["scanTakePicture"] == "Prendre le code-barres en photo"
        for key in (
            "scanCamera",
            "scanStarting",
            "scanHint",
            "scanNeedsHttps",
            "scanCameraDenied",
            "scanCameraFailed",
            "scanReaderError",
            "scanPictureEmpty",
            "scanCreate",
        ):
            assert labels[key], key
            assert labels[key] != key
        # Put in client-side, where the name and the barcode are known.
        assert "%(name)s" in labels["scanAdded"]
        assert "%(name)s" in labels["scanAlready"]
        assert "%(barcode)s" in labels["scanUnknown"]
        # Not left in English: the catalogue has them all.
        assert "inventaire" in labels["scanAdded"]
        assert "catalogue" in labels["scanUnknown"]

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
    @patch("opennutrilab.products.views.fetch_from_off")
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

    @patch("opennutrilab.products.views.fetch_from_off")
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

    @patch("opennutrilab.products.api.openfoodfacts.services.requests.get")
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

    @patch("opennutrilab.products.views.fetch_from_off")
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
        with patch("opennutrilab.products.views.fetch_from_off") as fetch:
            response: HttpResponse = client.get(reverse("create_product"))

        fetch.assert_not_called()
        assert response.context["form"].initial == {}

    @patch("opennutrilab.products.views.fetch_from_off")
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
        # Converted to each nutrient's unit, shown without trailing zeros.
        assert form["nutrient_sugars"].value() == "56.3"
        assert form["nutrient_energy"].value() == "2252"
        assert form["off_barcode"].value() == NUTELLA
        assert form["off_image_url"].value() == IMAGE_URL
        carried = json.loads(form["off_ingredients"].value())
        assert [i["name"] for i in carried] == ["sucre", "lait"]
        assert carried[0]["percentage"] == "56.3"
        assert {i["language"] for i in carried} == {"fr"}
        rows = response.context["ingredient_rows"]
        assert [r["name"] for r in rows] == ["sucre", "lait"]
        assert rows[1]["ingredients"][0]["name"] == "lait écrémé"

    @patch("opennutrilab.products.views.fetch_from_off")
    def test_lookup_fills_the_serving_read_from_its_text(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product(
            serving_size="35,7 g (1 tranche)"
        )

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        form: ProductForm = response.context["form"]
        assert form["serving_quantity"].value() == "35.7"
        assert form["serving_unit"].value() == "g"
        assert form["serving_name"].value() == "1 tranche"
        assert list(response.context["messages"]) == []

    @patch("opennutrilab.products.views.fetch_from_off")
    def test_lookup_gives_a_drink_a_table_per_100_ml_though_openfoodfacts_says_100g(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product(
            nutrition_data_per="100g", quantity="4 x 200 ml", serving_size="200 ml"
        )

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        assert response.context["form"]["nutrition_unit"].value() == "ml"

    @patch("opennutrilab.products.views.fetch_from_off")
    def test_lookup_keeps_a_table_per_100_g_for_what_is_sold_by_weight(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product(
            nutrition_data_per="100g", quantity="400 g", serving_size="30 g"
        )

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        assert response.context["form"]["nutrition_unit"].value() == "g"

    @patch("opennutrilab.products.views.fetch_from_off")
    def test_a_serving_that_is_not_read_is_said_and_left_empty(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product(
            serving_size="40 g (40 g + 125 ml de lait)"
        )

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        form: ProductForm = response.context["form"]
        assert form["serving_quantity"].value() is None
        [notice] = [str(m) for m in response.context["messages"]]
        assert '"40 g (40 g + 125 ml de lait)"' in notice
        assert "could not be read" in notice

    @patch("opennutrilab.products.views.fetch_from_off")
    def test_a_product_openfoodfacts_has_no_serving_for_has_none(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product(serving_size=None)

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        assert response.context["form"]["serving_quantity"].value() is None
        assert list(response.context["messages"]) == []

    def test_a_product_created_is_in_the_inventory_of_whoever_created_it(
        self, client: Client, user: User
    ):
        other = UserFactory()

        with patch("opennutrilab.products.views.fetch_from_off"):
            client.post(
                reverse("create_product"),
                {"barcode": NUTELLA, "name": "Nutella", "serving_unit": "g"},
            )

        product = Product.objects.get(pk=NUTELLA)
        assert list(InventoryItem.objects.filter(product=product)) == [
            InventoryItem.objects.get(user=user, product=product)
        ]
        assert not InventoryItem.objects.filter(user=other).exists()

    @patch("opennutrilab.products.views.fetch_from_off")
    def test_lookup_fills_the_package_read_from_its_text(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product(quantity="6 x 125 g")

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        form: ProductForm = response.context["form"]
        assert form["package_quantity"].value() == "750"
        assert form["package_unit"].value() == "g"
        assert list(response.context["messages"]) == []

    @patch("opennutrilab.products.views.fetch_from_off")
    def test_a_package_that_is_not_read_is_said_and_left_empty(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product(quantity="2 pots")

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        form: ProductForm = response.context["form"]
        assert form["package_quantity"].value() is None
        [notice] = [str(m) for m in response.context["messages"]]
        assert '"2 pots"' in notice
        assert "could not be read" in notice

    @patch("opennutrilab.products.views.fetch_from_off")
    def test_a_product_openfoodfacts_has_no_quantity_for_has_no_package(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product(quantity=None)

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        assert response.context["form"]["package_quantity"].value() is None
        assert list(response.context["messages"]) == []

    @patch("opennutrilab.products.views.fetch_from_off")
    def test_a_badly_read_list_imports_no_ingredient_and_says_how_to_fix_it(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product(
            ingredients_text="Sucre, émulsifiants : lécithines [SOJA), vanilline"
        )

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        form: ProductForm = response.context["form"]
        assert form["name"].value() == "Nutella"  # the rest is still filled in
        assert json.loads(form["off_ingredients"].value()) == []
        assert response.context["ingredient_rows"] == []
        [notice] = [str(m) for m in response.context["messages"]]
        assert "looks badly read" in notice
        assert "[SOJA)" in notice
        assert f"https://world.openfoodfacts.org/product/{NUTELLA}" in notice

    @patch("opennutrilab.products.views.fetch_from_off")
    def test_percentages_over_one_hundred_are_said_but_the_list_is_kept(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product(
            ingredients_text="Farine 70%, sucre 40%, sel"
        )

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        assert [r["name"] for r in response.context["ingredient_rows"]] == [
            "farine",
            "sucre",
            "sel",
        ]
        [notice] = [str(m) for m in response.context["messages"]]
        assert "add up to more than 100" in notice

    @patch("opennutrilab.products.views.fetch_from_off")
    def test_a_product_without_a_list_says_so(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        mock_fetch_from_off.return_value = off_product(ingredients_text=None)

        response: HttpResponse = client.get(
            reverse("create_product"), {"barcode": NUTELLA}
        )

        assert response.context["ingredient_rows"] == []
        assert [str(m) for m in response.context["messages"]] == [
            "There is no ingredient list."
        ]

    @patch("opennutrilab.products.services.product_services.requests.get")
    @patch("opennutrilab.products.views.fetch_from_off")
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
        assert [str(i) for i in product.ingredients.filter(parent=None)] == [
            "sucre",
            "lait",
        ]
        assert mock_get.call_args.args == (IMAGE_URL,)
        assert product.image.name == f"images/products/{NUTELLA}.jpg"

    @patch("opennutrilab.products.services.product_services.requests.get")
    @patch("opennutrilab.products.views.fetch_from_off")
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

    @patch("opennutrilab.products.services.product_services.requests.get")
    @patch("opennutrilab.products.views.fetch_from_off")
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
            off_barcode=NUTELLA,
            off_ingredients="not json",
        )

        response: HttpResponse = client.post(reverse("create_product"), data)

        assert response.status_code == HTTPStatus.OK
        assert response.context["form"].non_field_errors()
        assert not Product.objects.filter(pk=NUTELLA).exists()


def product_with_an_estimate() -> Product:
    """A saved product whose one ingredient has a composition to estimate from."""
    product = Product.objects.create(barcode=NUTELLA, name="Nutella")
    source = Source.objects.create(
        code="ciqual-2025", name="Ciqual", attribution="Anses. Table Ciqual 2025."
    )
    food = SourceFood.objects.create(source=source, code="1")
    for code, amount in (("fat", "30"), ("carbohydrates", "55"), ("proteins", "6")):
        SourceFoodNutrient.objects.create(
            food=food,
            nutrient=Nutrient.objects.get(code=code),
            amount=Decimal(amount),
            confidence="A",
        )
    reference = ReferenceIngredient.objects.create(name_en="sugar")
    reference.source_foods.add(food)
    Ingredient.objects.create(
        product=product, reference=reference, percentage=Decimal("56.3")
    )
    return product


def script_of(page: str, element_id: str) -> Any:
    """What a |json_script blob of the page holds."""
    found = re.search(
        rf'<script id="{element_id}" type="application/json">(.*?)</script>',
        page,
        re.DOTALL,
    )
    assert found, f"no {element_id} in the page"
    return json.loads(found.group(1))


@pytest.mark.django_db
class TestProductEditView:
    @patch("opennutrilab.products.views.fetch_from_off")
    def test_the_page_no_longer_reloads_to_ask_openfoodfacts(
        self, mock_fetch_from_off: MagicMock, client: Client
    ):
        """
        What OpenFoodFacts has is asked for by the page's script (see OffLookupView)
        and set against the form: a GET of the edit page never replaces the stored
        values with it.
        """
        product = Product.objects.create(barcode=NUTELLA, name="Stored Product")
        mock_fetch_from_off.return_value = off_product()

        response: HttpResponse = client.get(
            reverse("edit_product", args=[product.pk]), {"reset": "1"}
        )

        mock_fetch_from_off.assert_not_called()
        assert response.context["form"]["name"].value() == "Stored Product"
        assert not response.context["form"]["off_barcode"].value()

    @patch("opennutrilab.products.services.product_services.requests.get")
    @patch("opennutrilab.products.views.fetch_from_off")
    def test_taking_a_lookup_keeps_a_serving_made_by_hand_when_off_has_none(
        self, mock_fetch_from_off: MagicMock, mock_get: MagicMock, client: Client
    ):
        product = Product.objects.create(
            barcode=NUTELLA,
            name="Nutella",
            serving_quantity=Decimal(15),
            serving_unit="g",
            serving_name="1 cuillère",
        )
        mock_get.return_value = ok_image_response()
        mock_fetch_from_off.return_value = off_product(serving_size=None)
        url = reverse("edit_product", args=[product.pk])
        form: ProductForm = client.get(url).context["form"]
        taken = taken_from_lookup(client, serving_size=None)
        assert "serving_quantity" not in taken

        client.post(url, submitted(form, **taken))

        product.refresh_from_db()
        assert product.serving_quantity == Decimal(15)
        assert product.serving_name == "1 cuillère"

        # One OpenFoodFacts gives replaces it, once taken.
        taken = taken_from_lookup(client, serving_size="30 g")
        client.post(url, submitted(form, **taken))

        product.refresh_from_db()
        assert product.serving_quantity == Decimal(30)
        assert product.serving_name == ""

    def test_plain_edit_leaves_the_ingredients_alone(self, client: Client):
        """Saving used to delete and recreate every ingredient, every time."""
        product = create_product(
            ProductCreate.model_validate(
                {
                    "barcode": NUTELLA,
                    "name": "Nutella",
                    "ingredients": [{"name": "Sucre"}, {"name": "Cacao"}],
                }
            )
        ).product
        ids = set(product.ingredients.values_list("id", flat=True))
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]

        with patch("opennutrilab.products.views.fetch_from_off") as fetch:
            client.post(url, submitted(form, name="Renamed"))

        fetch.assert_not_called()
        product.refresh_from_db()
        assert product.name == "Renamed"
        assert set(product.ingredients.values_list("id", flat=True)) == ids

    @patch("opennutrilab.products.services.product_services.requests.get")
    @patch("opennutrilab.products.views.fetch_from_off")
    def test_taking_a_lookup_then_saving_replaces_ingredients_and_warns_about_the_photo(
        self,
        mock_fetch_from_off: MagicMock,
        mock_get: MagicMock,
        client: Client,
    ):
        """
        The photo lives on a separate OFF host that can time out on its own:
        the product is saved anyway, with a notice to add the photo by hand.
        """
        product = Product.objects.create(barcode=NUTELLA, name="Stored Product")
        mock_fetch_from_off.return_value = off_product()
        mock_get.side_effect = requests.ConnectTimeout("timed out")
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]
        taken = taken_from_lookup(client)

        response: HttpResponse = client.post(url, submitted(form, **taken), follow=True)

        product.refresh_from_db()
        assert product.name == "Nutella"
        assert [str(i) for i in product.ingredients.filter(parent=None)] == [
            "sucre",
            "lait",
        ]
        assert not product.image
        notices = [str(m) for m in response.context["messages"]]
        assert any("could not be downloaded" in n for n in notices), notices

    def test_the_page_shows_the_estimate_of_the_saved_product(self, client: Client):
        product = product_with_an_estimate()

        with translation.override("en"):
            response: HttpResponse = client.get(
                reverse("edit_product", args=[product.pk])
            )

        assert response.status_code == HTTPStatus.OK
        page = response.content.decode()
        assert 'id="estimate"' in page
        assert "Estimate from the ingredients" in page
        # The label's figure and the estimate side by side, and the credit.
        assert ">sugar</td>" in page
        assert "56.3" in page
        assert "Anses. Table Ciqual 2025." in page
        assert response.context["estimate"].barcode == NUTELLA
        # It declares no nutrient: the warning is shown, and nothing could be
        # checked against the label, which the confidence marks with a dash.
        assert "The nutrition of the product was not used" in page
        assert re.search(r"\u00b7\s+\u2013\)", page)

    def test_the_create_page_has_no_estimate(self, client: Client):
        page = client.get(reverse("create_product")).content.decode()

        assert 'id="estimate"' not in page

    def test_a_form_posted_back_to_be_corrected_does_not_work_the_estimate_out(
        self, client: Client
    ):
        product = Product.objects.create(barcode=NUTELLA, name="Nutella")
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]

        with patch("opennutrilab.products.views.build_estimate") as build:
            response = client.post(url, submitted(form, name=""))

        assert response.status_code == HTTPStatus.OK
        build.assert_not_called()
        assert "estimate" not in response.context

    def test_a_failing_estimate_does_not_break_the_page(self, client: Client):
        product = Product.objects.create(barcode=NUTELLA, name="Nutella")

        with patch(
            "opennutrilab.products.views.build_estimate",
            side_effect=RuntimeError("The linear program failed"),
        ):
            response: HttpResponse = client.get(
                reverse("edit_product", args=[product.pk])
            )

        assert response.status_code == HTTPStatus.OK
        assert response.context["estimate"] is None
        assert "The estimate could not be worked out." in response.content.decode()

    def test_the_page_hands_the_estimate_to_the_gauges(self, client: Client):
        product = product_with_an_estimate()

        with translation.override("fr-fr"):
            response: HttpResponse = client.get(
                reverse("edit_product", args=[product.pk]),
                headers={"accept-language": "fr"},
            )

        page = response.content.decode()
        # Where the gauges go, and the tables they stand in for: the ingredients'
        # and the nutrients'.
        assert 'id="estimate-view"' in page
        assert page.count("data-estimate-table") == len(["ingredients", "nutrients"])
        panel = script_of(page, "estimate-panel")
        assert panel == json.loads(json.dumps(response.context["estimate_panel"]))
        assert [i["name"] for i in panel["ingredients"]] == ["sugar"]
        assert {n["code"] for n in panel["nutrients"]} >= {"fat", "carbohydrates"}
        # Its labels are the server's, in the language served.
        config = script_of(page, "product-form-config")["estimatePanel"]
        assert config["languageCode"].startswith("fr")
        assert config["labels"]["viewGauges"] == "Jauges"
        assert config["labels"]["agrees"] == "L'étiquette concorde"
        assert config["labels"]["legendLabel"] == "Chiffre de l'étiquette"
        assert config["labels"]["constrained"] == "Point de départ du calcul"
        assert config["labels"]["reliabilityLow"] == "Fiabilité faible"
        # Figures put in client-side, so their places must survive.
        assert "%(checked)s" in config["labels"]["summaryChecked"]
        assert "%(total)s" in config["labels"]["summaryChecked"]
        assert "%(n)s" in config["labels"]["chipChecked"]
        assert "%(name)s" in config["labels"]["detailShow"]
        assert "%(value)s" in config["labels"]["labelAt"]
        # None is left in English: every label has a French entry of its own.
        assert all(config["labels"].values())
        assert config["labels"]["ingredient"] == "Ingrédient"

    def test_the_page_names_a_preparation_in_the_table_too(self, client: Client):
        product = Product.objects.create(barcode=NUTELLA, name="Nutella")
        Ingredient.objects.create(
            product=product,
            preparation=Preparation.objects.create(name_en="praline"),
            percentage=Decimal("20"),
        )

        with translation.override("en"):
            response: HttpResponse = client.get(
                reverse("edit_product", args=[product.pk])
            )

        assert ">praline</td>" in response.content.decode()

    def test_the_create_page_and_a_failed_estimate_have_nothing_for_the_gauges(
        self, client: Client
    ):
        product = Product.objects.create(barcode=NUTELLA, name="Nutella")
        created = client.get(reverse("create_product")).content.decode()
        with patch(
            "opennutrilab.products.views.build_estimate",
            side_effect=RuntimeError("The linear program failed"),
        ):
            failed = client.get(
                reverse("edit_product", args=[product.pk])
            ).content.decode()

        for page in (created, failed):
            assert 'id="estimate-panel"' not in page
            assert 'id="estimate-view"' not in page

    def test_a_tampered_barcode_is_ignored(self, client: Client):
        """The barcode is the primary key: editing must never move a product."""
        product = Product.objects.create(barcode=NUTELLA, name="Nutella")
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]

        client.post(url, submitted(form, barcode="3229820794556", name="Renamed"))

        assert Product.objects.get(pk=NUTELLA).name == "Renamed"
        assert not Product.objects.filter(pk="3229820794556").exists()


# What a label prints, with a line break (a browser posts it as CRLF) and markup
# that must not be taken for markup.
LABEL_TEXT = "Sucre 56,3 %, <b>lait</b> (lait écrémé).\npeut contenir des traces."


def looked_up(
    client: Client,
    text: str | None = LABEL_TEXT,
    language: str = "en",
    **query: str,
):
    """The create page after an OFF lookup (what the scan and the search link to)."""
    path = query.pop("path", reverse("create_product"))
    params = {"barcode": NUTELLA, **query}
    with patch(
        "opennutrilab.products.views.fetch_from_off",
        return_value=off_product(ingredients_text=text),
    ):
        return client.get(path, params, headers={"accept-language": language})


def taken_from_lookup(
    client: Client, text: str | None = LABEL_TEXT, **off: Any
) -> dict[str, Any]:
    """
    What the page's script puts in the form after taking everything a lookup found:
    the fields OpenFoodFacts has a value for, and the hidden ones that carry the
    list and the photo.
    """
    with patch(
        "opennutrilab.products.views.fetch_from_off",
        return_value=off_product(ingredients_text=text, **off),
    ):
        found = client.get(reverse("lookup_off"), {"barcode": NUTELLA}).json()
    return {
        **{name: value for name, value in found["fields"].items() if name != "barcode"},
        "off_barcode": NUTELLA,
        "off_image_url": found["image"] or "",
        "off_ingredients": found["label"]["ingredients"],
        "off_ingredients_text": found["label"]["text"],
        "ingredients_ignored": "[]",
        "ingredients_lc": found["label"]["language"],
    }


@pytest.mark.django_db
class TestIngredientListText:
    """The label's own words are shown next to the ingredients read from them."""

    def test_a_lookup_shows_the_list_word_for_word_and_carries_it(self, client: Client):
        with translation.override("en"):
            response: HttpResponse = looked_up(client)

        page = response.content.decode()
        assert "Ingredient list, as the label prints it" in page
        assert "Loaded from OpenFoodFacts. It is saved with the product." in page
        # Escaped, and its line break kept for the browser to show.
        assert "&lt;b&gt;lait&lt;/b&gt; (lait écrémé)." in page
        assert "<b>lait</b>" not in page
        # Shown, not posted: a block of text, which is no field.
        assert 'id="ingredients-text-view"' in page
        assert (
            "<textarea"
            not in page.split('id="ingredients-text"', 1)[1].split(
                'id="ingredients-text-view"', 1
            )[0]
        )
        assert response.context["form"]["off_ingredients_text"].value() == LABEL_TEXT

    def test_saving_a_looked_up_product_keeps_the_text(self, client: Client):
        form = looked_up(client).context["form"]
        # A browser posts line breaks as CRLF.
        crlf = LABEL_TEXT.replace("\n", "\r\n")

        client.post(
            reverse("create_product"), submitted(form, off_ingredients_text=crlf)
        )

        assert Product.objects.get(pk=NUTELLA).ingredients_text == LABEL_TEXT

    def test_the_text_comes_back_when_the_form_has_to_be_corrected(
        self, client: Client
    ):
        form = looked_up(client).context["form"]

        response: HttpResponse = client.post(
            reverse("create_product"), submitted(form, name="")
        )

        assert not Product.objects.exists()
        assert "&lt;b&gt;lait&lt;/b&gt;" in response.content.decode()

    def test_a_saved_product_shows_the_text_it_was_saved_with(self, client: Client):
        product = Product.objects.create(
            barcode=NUTELLA, name="Nutella", ingredients_text=LABEL_TEXT
        )

        with translation.override("en"):
            page = client.get(
                reverse("edit_product", args=[product.pk])
            ).content.decode()

        assert "&lt;b&gt;lait&lt;/b&gt; (lait écrémé)." in page
        assert (
            "Saved with the product: the text its ingredients were read from." in page
        )

    def test_a_product_saved_without_a_text_says_so_and_how_to_get_it(
        self, client: Client
    ):
        product = Product.objects.create(barcode=NUTELLA, name="Nutella")

        with translation.override("en"):
            page = client.get(
                reverse("edit_product", args=[product.pk])
            ).content.decode()

        assert "No text was saved for this product." in page
        assert "Compare with OpenFoodFacts" in page

    def test_a_lookup_that_has_no_list_says_so(self, client: Client):
        with translation.override("en"):
            page = looked_up(client, text="").content.decode()

        assert "OpenFoodFacts has no ingredient list for this product." in page

    def test_a_new_product_not_looked_up_has_an_empty_block_to_write_the_list_in(
        self, client: Client
    ):
        with translation.override("en"):
            page = client.get(reverse("create_product")).content.decode()

        block = page.split('id="ingredients-text"', 1)[1]
        assert "No list yet." in block
        assert 'id="ingredients-text-editor"' in block
        assert 'data-action="edit"' in block

    def test_taking_the_list_of_a_lookup_replaces_the_saved_text(self, client: Client):
        product = Product.objects.create(
            barcode=NUTELLA, name="Nutella", ingredients_text="An old text"
        )
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]

        client.post(url, submitted(form, **taken_from_lookup(client)))

        product.refresh_from_db()
        assert product.ingredients_text == LABEL_TEXT

    def test_taking_only_the_photo_leaves_the_saved_list_alone(self, client: Client):
        """The page sets the photo apart from the list: neither wipes the other."""
        product = Product.objects.create(
            barcode=NUTELLA, name="Nutella", ingredients_text="Saved"
        )
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]

        with patch(
            "opennutrilab.products.services.product_services.requests.get",
            return_value=ok_image_response(),
        ):
            client.post(
                url,
                submitted(form, off_barcode=NUTELLA, off_image_url=IMAGE_URL),
            )

        product.refresh_from_db()
        assert product.ingredients_text == "Saved"
        assert product.image

    def test_a_list_typed_on_a_new_product_is_saved_with_the_ingredients_read_from_it(
        self, client: Client
    ):
        form = client.get(reverse("create_product")).context["form"]
        reading = json_post(
            client, {"text": "Sucre, sel.", "language": "fr", "ignored": []}
        ).json()

        # What the script does: keep the reading in the form, for the barcode typed.
        response = client.post(
            reverse("create_product"),
            submitted(
                form,
                barcode=NUTELLA,
                name="Mine",
                off_barcode=NUTELLA,
                off_ingredients=reading["ingredients"],
                off_ingredients_text="Sucre, sel.",
                ingredients_ignored="[]",
                ingredients_lc="fr",
            ),
        )

        assert response.status_code == HTTPStatus.FOUND
        product = Product.objects.get(pk=NUTELLA)
        assert product.ingredients_text == "Sucre, sel."
        assert product.ingredients_language == "fr"
        assert [str(i) for i in product.ingredients.filter(parent=None)] == [
            "sucre",
            "sel",
        ]

    def test_a_plain_edit_leaves_the_saved_text_alone(self, client: Client):
        product = Product.objects.create(
            barcode=NUTELLA, name="Nutella", ingredients_text="Saved"
        )
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]

        client.post(url, submitted(form, name="Renamed"))

        product.refresh_from_db()
        assert (product.name, product.ingredients_text) == ("Renamed", "Saved")

    def test_the_block_is_in_the_language_served(self, client: Client):
        page = looked_up(client, language="fr").content.decode()

        assert "Liste des ingrédients, telle que l'étiquette l'imprime" in page
        assert "Chargé depuis OpenFoodFacts." in page
        assert "Écarter la sélection" in page
        assert "Remettre la sélection" in page
        assert "Tout remettre" in page
        assert 'data-reading="Lecture…"' in page
        assert 'data-failed="Le texte n&#x27;a pas pu être relu. Réessayez."' in page


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
class TestSearchOffView:
    URL = reverse("search_off")

    @patch("opennutrilab.products.views.search_off")
    def test_lists_what_openfoodfacts_finds(
        self, mock_search: MagicMock, client: Client
    ):
        mock_search.return_value = [
            OFFSearchHitSchema.model_validate(
                {
                    "code": "3700966568466",
                    "product_name": "Colin d'Alaska pané",
                    "brands": ["Cap océan", "Marque"],
                    "quantity": "500 g",
                    "image_small_url": "https://images.openfoodfacts.org/a.jpg",
                }
            ),
            OFFSearchHitSchema.model_validate({"code": "3229820794556"}),
        ]

        response: HttpResponse = client.get(self.URL, {"q": " colin "})

        assert response.status_code == HTTPStatus.OK
        mock_search.assert_called_once_with("colin")
        assert response.json() == {
            "results": [
                {
                    "barcode": "3700966568466",
                    "name": "Colin d'Alaska pané",
                    "brands": "Cap océan, Marque",
                    "quantity": "500 g",
                    "image": "https://images.openfoodfacts.org/a.jpg",
                },
                {
                    "barcode": "3229820794556",
                    "name": "",
                    "brands": "",
                    "quantity": "",
                    "image": "",
                },
            ]
        }

    @patch("opennutrilab.products.views.search_off")
    def test_a_text_too_short_does_not_ask_openfoodfacts(
        self, mock_search: MagicMock, client: Client
    ):
        response: HttpResponse = client.get(self.URL, {"q": "co "})

        assert response.json() == {"results": []}
        mock_search.assert_not_called()

    @patch("opennutrilab.products.views.search_off")
    def test_openfoodfacts_down_is_a_bad_gateway(
        self, mock_search: MagicMock, client: Client
    ):
        mock_search.side_effect = OFFError("down")

        response: HttpResponse = client.get(self.URL, {"q": "colin"})

        assert response.status_code == HTTPStatus.BAD_GATEWAY
        assert response.json() == {"error": "unavailable"}

    def test_is_for_signed_in_users(self):
        response: HttpResponse = Client().get(self.URL, {"q": "colin"})

        assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestOpenFoodFactsLinks:
    def test_a_new_product_can_be_searched_on_openfoodfacts(self, client: Client):
        with translation.override("fr-fr"):
            response: HttpResponse = client.get(
                reverse("create_product"), headers={"accept-language": "fr"}
            )

        page = response.content.decode()
        assert 'id="off-search-input"' in page
        assert "Chercher sur OpenFoodFacts" in page
        # No link to the page of a product that is not one yet.
        assert 'id="open-off-product"' not in page
        config = response.context["product_form_config"]["offSearch"]
        assert config["url"] == reverse("search_off")
        assert config["minLength"] == 3  # noqa: PLR2004
        assert config["placeholderImage"].endswith(".png")
        assert config["labels"]["error"].startswith("OpenFoodFacts est injoignable")

    def test_a_product_can_be_seen_on_openfoodfacts(self, client: Client):
        product = Product.objects.create(barcode="3229820794556", name="Muesli")

        with translation.override("fr-fr"):
            response: HttpResponse = client.get(
                reverse("edit_product", args=[product.pk]),
                headers={"accept-language": "fr"},
            )

        page = response.content.decode()
        match = re.search(r'<a [^>]*id="open-off-product"[^>]*>', page)
        assert match, "no link to OpenFoodFacts"
        link = match.group(0)
        assert 'href="https://world.openfoodfacts.org/product/3229820794556"' in link
        # Beside the page being edited, not in place of it.
        assert 'target="_blank"' in link
        assert "noopener" in link
        assert "Voir sur OpenFoodFacts" in page
        assert 'id="off-search-input"' not in page


def fold_group(page: str, key: str) -> str:
    """The html of a group of nutrients of the form, from its head to what follows."""
    start = page.index(f'data-fold-group="{key}"')
    ends = [
        page.find(after, start + 1) for after in ("data-fold-group=", "accordion-item")
    ]
    return page[start : min([e for e in ends if e != -1], default=len(page))]


@pytest.mark.django_db
class TestNutrientGroupsOfTheForm:
    @pytest.fixture(autouse=True)
    def _vitamins(self) -> None:
        """The catalogue of a test has no vitamin on the label: two are put there."""
        for code, name in (("vitamin_c", "Vitamin C"), ("vitamin_d", "Vitamin D")):
            Nutrient.objects.create(
                code=code,
                name_en=name,
                name_fr=name,
                unit="mg",
                group="vitamin",
                on_label=True,
            )

    def test_the_nutrients_are_in_groups_that_fold(self, client: Client):
        with translation.override("fr-fr"):
            response: HttpResponse = client.get(
                reverse("create_product"), headers={"accept-language": "fr"}
            )

        page = response.content.decode()
        keys = re.findall(r'data-fold-group="(\w+)"', page)
        # The order of the meals page; a group the label has nothing in is not there.
        assert keys == ["energy", "macronutrient", "other", "vitamin"]
        assert "Macronutriment" in fold_group(page, "macronutrient")
        # A part of another nutrient is with it, not in a group of its own.
        macro = fold_group(page, "macronutrient")
        assert "dont acides gras saturés" in macro
        assert "dont sucres" in macro
        assert 'data-bs-toggle="collapse"' in macro

    def test_the_main_groups_are_open_and_the_others_open_when_filled(
        self, client: Client
    ):
        page = client.get(reverse("create_product")).content.decode()

        assert "collapse show" in fold_group(page, "macronutrient")
        assert "collapse show" not in fold_group(page, "vitamin")
        assert "0 / 2" in fold_group(page, "vitamin")

        product = Product.objects.create(barcode="3229820794556", name="Muesli")
        ProductNutrient.objects.create(
            product=product,
            nutrient=Nutrient.objects.get(code="vitamin_c"),
            amount=12,
        )
        page = client.get(reverse("edit_product", args=[product.pk])).content.decode()

        assert "collapse show" in fold_group(page, "vitamin")
        assert "1 / 2" in fold_group(page, "vitamin")

    def test_a_group_with_a_figure_to_put_right_is_open(self, client: Client):
        response: HttpResponse = client.post(
            reverse("create_product"),
            {
                "barcode": "3229820794556",
                "name": "Muesli",
                nutrient_field("vitamin_c"): "-1",
            },
        )

        page = response.content.decode()
        assert "is-invalid" in fold_group(page, "vitamin")
        assert "collapse show" in fold_group(page, "vitamin")


@pytest.mark.django_db
class TestBarcodeImage:
    def test_the_page_of_a_product_shows_its_barcode(self, client: Client):
        product = Product.objects.create(barcode="3229820794556", name="Muesli")

        page = client.get(reverse("edit_product", args=[product.pk])).content.decode()

        assert '<div id="barcode-image" data-code="3229820794556">' in page
        config = client.get(reverse("edit_product", args=[product.pk])).context[
            "product_form_config"
        ]
        assert config["barcodeImage"]["label"]

    def test_a_product_not_made_yet_has_none(self, client: Client):
        page = client.get(reverse("create_product")).content.decode()

        assert 'id="barcode-image"' not in page


@pytest.mark.django_db
class TestProductListHeader:
    def test_the_button_that_creates_a_product_is_at_the_top(self, client: Client):
        with translation.override("fr-fr"):
            response: HttpResponse = client.get(
                reverse("list_products"), headers={"accept-language": "fr"}
            )

        page = response.content.decode()
        button = page.index(reverse("create_product"))
        # Above the list, not under it where it was hard to find.
        assert button < page.index('id="product-list-root"')
        assert "Créer un produit" in page
        # "Add" is what a product of the catalogue is to the inventory.
        assert "Ajouter un nouveau produit" not in page

    def test_the_list_can_fold_all_its_groups(self, client: Client):
        with translation.override("fr-fr"):
            response: HttpResponse = client.get(
                reverse("list_products"), headers={"accept-language": "fr"}
            )

        labels = response.context["product_list_props"]["labels"]
        assert labels["foldAll"] == "Tout replier"
        assert labels["unfoldAll"] == "Tout déplier"


@pytest.mark.django_db
class TestProductDeleteView:
    @pytest.fixture(autouse=True)
    def _staff(self, client: Client) -> None:
        client.force_login(UserFactory(is_staff=True))

    def test_signed_in_non_staff_cannot_delete(self, user: User):
        """The catalogue is shared by every user."""
        product = Product.objects.create(barcode=NUTELLA, name="N")
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
        product = Product.objects.create(barcode="3229820794556", name="Apple")
        url = reverse("delete_product", kwargs={"pk": product.pk})

        response: HttpResponse = client.get(url)

        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
        assert Product.objects.filter(pk=product.pk).exists()

    def test_post_deletes_and_redirects_to_the_list(self, client: Client):
        product = Product.objects.create(barcode="3229820794556", name="Apple")
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
def test_product_form_pages_hand_config_to_the_scripts(
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
    # form-entry.js reads its configuration and translated strings from this
    # json_script blob.
    assert 'id="product-form-config"' in response.content.decode()


@pytest.mark.django_db
def test_the_chart_is_configured_from_the_catalogue(client: Client):
    """Mass nutrients of the label, linked by code, named in the page language."""
    with translation.override("fr-fr"):
        response: HttpResponse = client.get(
            reverse("create_product"), headers={"accept-language": "fr"}
        )

    chart = response.context["product_form_config"]["nutrientChart"]
    assert [(s["code"], s["parent"]) for s in chart["slices"]] == [
        ("fat", None),
        ("saturated_fat", "fat"),
        ("carbohydrates", None),
        ("sugars", "carbohydrates"),
        ("fiber", None),
        ("proteins", None),
        ("salt", None),
    ]
    assert chart["slices"][-1]["label"] == "Sel"
    assert chart["slices"][0]["field"] == "nutrient_fat"


@pytest.mark.django_db
def test_inconsistent_values_are_saved_and_reported(client: Client):
    form = client.get(reverse("create_product")).context["form"]
    data = submitted(
        form,
        barcode=NUTELLA,
        name="N",
        nutrient_carbohydrates="9.9",
        nutrient_sugars="10",
    )

    response: HttpResponse = client.post(reverse("create_product"), data, follow=True)

    assert ProductNutrient.objects.filter(product_id=NUTELLA).count() == 2  # noqa: PLR2004
    notices = [str(m) for m in response.context["messages"]]
    assert any("exceed" in n for n in notices), notices


CIQUAL_SHEET = "https://ciqual.anses.fr/#/aliments/{}"


@pytest.fixture
def ciqual(db: None) -> Source:
    return Source.objects.create(code="ciqual-2020", name="CIQUAL", version="2020")


def reference_with_foods(name: str, source: Source, *codes: str) -> ReferenceIngredient:
    reference = ReferenceIngredient.objects.create(name_en=name)
    reference.source_foods.add(
        *(SourceFood.objects.create(source=source, code=code) for code in codes)
    )
    return reference


@pytest.mark.django_db
def test_rows_from_inputs_show_off_ciqual_codes_marking_proxies():
    """Nothing is curated yet for these, so OFF's own codes are what there is."""
    items = [
        IngredientInput(name="Flocons d'avoine", off_ciqual_food_code="9311"),
        IngredientInput(name="Flocons de blé", off_ciqual_proxy_food_code="9410"),
        IngredientInput(name="Soja"),
    ]

    with translation.override("en-us"):
        rows = ingredient_rows_from_inputs(items)

    assert [(r["name"], r["ciqual"], r["reference"]) for r in rows] == [
        ("Flocons d'avoine", "9311", "New"),
        ("Flocons de blé", "9410 (proxy)", "New"),
        ("Soja", "", "New"),
    ]


@pytest.mark.django_db
def test_rows_from_inputs_show_a_vitamin_as_the_nutrient_it_is_and_not_as_new():
    """The page that previews a product says what saving it will make."""
    Nutrient.objects.create(
        code="vitamin_d",
        name_en="Vitamin D",
        name_fr="Vitamine D",
        unit=Nutrient.Unit.MICROGRAM,
        group=Nutrient.Group.VITAMIN,
    )
    items = [IngredientInput(name="Farine"), IngredientInput(name="vitamine D")]

    with translation.override("fr"):
        rows = ingredient_rows_from_inputs(items)

    assert [(r["name"], r["reference"], r["ciqual"]) for r in rows] == [
        ("Farine", "Nouvelle", ""),
        ("Vitamine D", "Nutriment", ""),
    ]


@pytest.mark.django_db
def test_rows_link_ciqual_codes_to_the_ciqual_site():
    items = [
        IngredientInput(name="Flocons d'avoine", off_ciqual_food_code="9311"),
        IngredientInput(name="Flocons de blé", off_ciqual_proxy_food_code="9410"),
        IngredientInput(name="Soja"),
        IngredientInput(name="Piège", off_ciqual_food_code="1/2#3"),
    ]

    rows = ingredient_rows_from_inputs(items)

    assert [r["ciqual_url"] for r in rows] == [
        "https://ciqual.anses.fr/#/aliments/9311",
        "https://ciqual.anses.fr/#/aliments/9410",
        None,
        "https://ciqual.anses.fr/#/aliments/1%2F2%233",
    ]


@pytest.mark.django_db
def test_rows_from_inputs_show_an_existing_reference_as_it_is(ciqual: Source):
    """Its own name, status and CIQUAL foods, not what OpenFoodFacts said."""
    oats = reference_with_foods("oat flakes", ciqual, "9311")
    oats.status = ReferenceIngredient.Status.CURATED
    oats.save()
    items = [IngredientInput(name="Oat Flakes", off_ciqual_food_code="0000")]

    with translation.override("en-us"):
        rows = ingredient_rows_from_inputs(items)

    assert [
        (r["name"], r["ciqual"], r["ciqual_url"], r["reference"]) for r in rows
    ] == [("oat flakes", "9311", CIQUAL_SHEET.format("9311"), "Curated")]


@pytest.mark.django_db
def test_rows_from_inputs_show_a_preparation_next_to_a_reference(ciqual: Source):
    """Each with its own foods, though a reference and a preparation share an id."""
    oats = reference_with_foods("oat flakes", ciqual, "9311")
    mozzarella = Preparation.objects.create(
        id=oats.pk,
        name_en="mozzarella",
        name_fr="mozzarella",
        status=Preparation.Status.CURATED,
    )
    mozzarella.source_foods.add(
        SourceFood.objects.create(source=ciqual, code="12120", name_fr="Mozzarella")
    )
    items = [
        IngredientInput(name="oat flakes"),
        IngredientInput(
            name="Mozzarella", sub_ingredients=[IngredientInput(name="Oat Flakes")]
        ),
        IngredientInput(name="Gnocchi"),
    ]

    with translation.override("en-us"):
        rows = ingredient_rows_from_inputs(items)

    assert [(r["name"], r["ciqual"], r["reference"]) for r in rows] == [
        ("oat flakes", "9311", "To review"),
        ("mozzarella", "12120", "Preparation, curated"),
        ("Gnocchi", "", "New"),
    ]
    assert [c["name"] for c in rows[1]["ingredients"]] == ["oat flakes"]


@pytest.mark.django_db
def test_rows_from_inputs_show_an_additive_by_its_code_with_its_own_foods(
    ciqual: Source,
):
    oats = reference_with_foods("oat flakes", ciqual, "9311")
    lecithin = Additive.objects.create(
        id=oats.pk, name_en="soy lecithin", code="E322", status="curated"
    )
    lecithin.source_foods.add(
        SourceFood.objects.create(source=ciqual, code="42200", name_fr="Lécithine")
    )
    items = [IngredientInput(name="oat flakes"), IngredientInput(name="E 322")]

    with translation.override("en-us"):
        rows = ingredient_rows_from_inputs(items)

    assert [(r["name"], r["ciqual"], r["reference"]) for r in rows] == [
        ("oat flakes", "9311", "To review"),
        ("soy lecithin", "42200", "Additive, curated"),
    ]


@pytest.mark.django_db
def test_rows_from_inputs_find_a_reference_through_the_english_name(
    ciqual: Source,
):
    """The same lookup as saving: a French name typed by hand is not new."""
    IngredientTaxon.objects.create(
        off_id="en:oat-flakes", name_en="oat flakes", name_fr="flocons d'avoine"
    )
    reference_with_foods("oat flakes", ciqual, "9311")

    with translation.override("en-us"):
        rows = ingredient_rows_from_inputs([IngredientInput(name="Flocons d'avoine")])

    assert [(r["name"], r["ciqual"], r["reference"]) for r in rows] == [
        ("oat flakes", "9311", "To review")
    ]


@pytest.mark.django_db
def test_rows_from_db_show_the_references_ciqual_codes(ciqual: Source):
    sugar = reference_with_foods("sugar", ciqual, "31016")
    milk = reference_with_foods("milk", ciqual, "19054", "19051")
    flavour = ReferenceIngredient.objects.create(name_en="flavour")
    # A food of another source is not a CIQUAL code.
    other = Source.objects.create(code="manual", name="Saisie manuelle")
    flavour.source_foods.add(SourceFood.objects.create(source=other, code="1"))
    product = create_product(
        ProductCreate.model_validate(
            {
                "barcode": NUTELLA,
                "name": "Nutella",
                "ingredients": [
                    {"name": "sugar"},
                    {"name": "milk"},
                    {"name": "flavour"},
                ],
            }
        )
    ).product
    assert {i.reference for i in product.ingredients.all()} == {sugar, milk, flavour}

    rows = ingredient_rows_from_db(product)

    # Several codes: shown, but no single sheet to link.
    assert [(r["name"], r["ciqual"], r["ciqual_url"]) for r in rows] == [
        ("sugar", "31016", CIQUAL_SHEET.format("31016")),
        ("milk", "19051, 19054", None),
        ("flavour", "", None),
    ]


@pytest.mark.django_db
def test_rows_from_db_rebuild_the_tree(
    ciqual: Source, django_assert_max_num_queries: Any
):
    milk = reference_with_foods("milk", ciqual, "19054")
    milk.status = ReferenceIngredient.Status.CURATED
    milk.save()
    product = create_product(
        ProductCreate.model_validate(
            {
                "barcode": NUTELLA,
                "name": "Nutella",
                "ingredients": [
                    {"name": "Sugar", "percentage": "56.3"},
                    {"name": "Milk powder", "sub_ingredients": [{"name": "milk"}]},
                ],
            }
        )
    ).product

    # The ingredients, then the foods of each kind there is (here two: the
    # references, and the preparation "Milk powder" that lists its parts).
    with translation.override("en-us"), django_assert_max_num_queries(4):
        rows = ingredient_rows_from_db(product)

    assert [r["name"] for r in rows] == ["Sugar", "Milk powder"]
    assert [r["percentage"] for r in rows] == [Decimal("56.30"), None]
    assert rows[0]["ingredients"] is None
    assert [(c["name"], c["reference"]) for c in rows[1]["ingredients"]] == [
        ("milk", "Curated")
    ]
    # What is created for a name nobody had is still to review, and an ingredient
    # whose parts the label lists is a preparation.
    assert [r["reference"] for r in rows] == ["To review", "Preparation, to review"]
    assert Ingredient.objects.filter(product=product).count() == 3  # noqa: PLR2004


@pytest.fixture
def taxonomy(db: None) -> None:
    IngredientTaxon.objects.bulk_create(
        [
            IngredientTaxon(
                off_id="en:oat-flakes", name_en="oat flakes", name_fr="flocons d'avoine"
            ),
            IngredientTaxon(off_id="en:date", name_en="date", name_fr="datte"),
            # Known, but with no French name.
            IngredientTaxon(off_id="en:soya", name_en="soya"),
        ]
    )


def test_rows_from_inputs_show_the_french_name_while_french_is_served(
    taxonomy: None, django_assert_num_queries: Any
):
    """For ingredients no reference has the name of yet."""
    items = [
        IngredientInput(name="oat flakes", off_id="en:oat-flakes"),
        IngredientInput(
            name="date",
            off_id="en:date",
            sub_ingredients=[IngredientInput(name="date", off_id="en:date")],
        ),
        IngredientInput(name="soya", off_id="en:soya"),
        # Not in the taxonomy, or typed by hand: the name there is.
        IngredientInput(name="Sel rose", off_id="fr:sel-rose"),
        IngredientInput(name="Épices"),
    ]

    # The references, the preparations and the additives by name, the taxonomy,
    # those by correspondence, then the French names.
    with translation.override("fr-fr"), django_assert_num_queries(8):
        rows = ingredient_rows_from_inputs(items)

    assert [r["name"] for r in rows] == [
        "flocons d'avoine",
        "datte",
        "soya",
        "Sel rose",
        "Épices",
    ]
    assert [c["name"] for c in rows[1]["ingredients"]] == ["datte"]


def test_rows_from_inputs_keep_the_english_name_in_other_languages(
    taxonomy: None, django_assert_num_queries: Any
):
    items = [IngredientInput(name="oat flakes", off_id="en:oat-flakes")]

    with translation.override("en-us"), django_assert_num_queries(7):
        rows = ingredient_rows_from_inputs(items)

    assert [r["name"] for r in rows] == ["oat flakes"]


def test_rows_from_db_show_the_name_in_the_language_served(
    taxonomy: None, django_assert_max_num_queries: Any
):
    """The French name was taken from the taxonomy when the reference was created."""
    product = create_product(
        ProductCreate.model_validate(
            {
                "barcode": NUTELLA,
                "name": "Muesli",
                "ingredients": [
                    {
                        "name": "date",
                        "off_id": "en:date",
                        "sub_ingredients": [
                            {"name": "oat flakes", "off_id": "en:oat-flakes"}
                        ],
                    },
                    {"name": "Épices"},
                ],
            }
        )
    ).product

    with translation.override("fr-fr"), django_assert_max_num_queries(3):
        rows = ingredient_rows_from_db(product)
    with translation.override("en-us"):
        english_rows = ingredient_rows_from_db(product)

    assert [r["name"] for r in rows] == ["datte", "Épices"]
    assert [c["name"] for c in rows[0]["ingredients"]] == ["flocons d'avoine"]
    assert [r["name"] for r in english_rows] == ["date", "Épices"]
    assert Preparation.objects.get(name_en="date").name_fr == "datte"


@pytest.mark.django_db
def test_rows_from_db_show_a_preparation_by_its_name_and_marked_as_one(ciqual: Source):
    mozzarella = Preparation.objects.create(name_en="mozzarella", name_fr="mozzarella")
    mozzarella.source_foods.add(
        SourceFood.objects.create(source=ciqual, code="12120", name_fr="Mozzarella")
    )
    product = Product.objects.create(barcode=NUTELLA, name="Pizza")
    sugar = ReferenceIngredient.objects.create(name_en="sugar")
    Ingredient.objects.create(product=product, reference=sugar)
    pizza = Ingredient.objects.create(product=product, preparation=mozzarella)
    Ingredient.objects.create(product=product, parent=pizza, reference=sugar)

    with translation.override("en"):
        rows = ingredient_rows_from_db(product)

    sweet, cheese = rows
    assert (sweet["name"], sweet["reference"]) == ("sugar", "To review")
    # Its CIQUAL code is that of the foods it draws on, and it says what it is.
    assert (cheese["name"], cheese["reference"], cheese["ciqual"]) == (
        "mozzarella",
        "Preparation, to review",
        "12120",
    )
    assert [r["name"] for r in cheese["ingredients"]] == ["sugar"]


@pytest.mark.django_db
def test_rows_from_db_show_an_additive_by_its_name_and_marked_as_one(ciqual: Source):
    lecithin = Additive.objects.create(
        name_en="soy lecithin", name_fr="lécithine de soja", code="E322"
    )
    lecithin.source_foods.add(
        SourceFood.objects.create(source=ciqual, code="42200", name_fr="Lécithine")
    )
    product = Product.objects.create(barcode=NUTELLA, name="Chocolate")
    sugar = ReferenceIngredient.objects.create(name_en="sugar")
    Ingredient.objects.create(product=product, reference=sugar)
    Ingredient.objects.create(product=product, additive=lecithin)

    with translation.override("fr"):
        rows = ingredient_rows_from_db(product)

    sweet, emulsifier = rows
    assert (sweet["name"], sweet["reference"]) == ("sugar", "À relire")
    # Its CIQUAL code is that of the foods it draws on, and it says what it is.
    assert (emulsifier["name"], emulsifier["reference"], emulsifier["ciqual"]) == (
        "lécithine de soja",
        "Additif, à relire",
        "42200",
    )


@pytest.mark.django_db
def test_rows_from_db_show_a_nutrient_by_its_name_and_marked_as_one():
    vitamin_d = Nutrient.objects.create(
        code="vitamin_d",
        name_en="Vitamin D",
        name_fr="Vitamine D",
        unit=Nutrient.Unit.MICROGRAM,
        group=Nutrient.Group.VITAMIN,
    )
    product = Product.objects.create(barcode=NUTELLA, name="Milk")
    Ingredient.objects.create(product=product, nutrient=vitamin_d)

    with translation.override("fr"):
        rows = ingredient_rows_from_db(product)

    (row,) = rows
    assert (row["name"], row["reference"], row["ciqual"], row["ciqual_url"]) == (
        "Vitamine D",
        "Nutriment",
        "",
        None,
    )


FISH_TEXT = (
    "Colin d'Alaska 72% [Theragra chalcogramma pêché dans l'Océan (FAO 67), "
    "zone de pêche], farine de blé (gluten), sel."
)
FISH_ZONE = [
    FISH_TEXT.index("[Theragra"),
    FISH_TEXT.index("pêche]") + len("pêche]"),
]


def json_post(client: Client, body: Any) -> "HttpResponse":
    return client.post(
        reverse("read_label"), json.dumps(body), content_type="application/json"
    )


def state_of(page: str) -> dict[str, Any]:
    """What the page hands the script that marks the text."""
    found = re.search(
        r'<script id="ingredients-text-state" type="application/json">(.*?)</script>',
        page,
        re.DOTALL,
    )
    assert found is not None
    return json.loads(found.group(1))


@pytest.mark.django_db
class TestReadLabelView:
    """The text read again for the page, without the places a person left out."""

    def test_it_answers_with_the_rows_the_json_the_places_and_the_warnings(
        self, client: Client
    ):
        response = json_post(client, {"text": FISH_TEXT, "language": "fr"})

        assert response.status_code == HTTPStatus.OK
        body = response.json()
        [fish, flour, salt] = body["rows"]
        assert fish["name"] == "colin d'alaska"
        assert Decimal(fish["percentage"]) == Decimal(72)
        assert next(row["name"] for row in fish["ingredients"]).startswith("theragra")
        assert [flour["name"], salt["name"]] == ["farine de blé", "sel"]
        sent = [(i["name"], i["language"]) for i in json.loads(body["ingredients"])]
        assert sent == [
            ("colin d'alaska", "fr"),
            ("farine de blé", "fr"),
            ("sel", "fr"),
        ]
        assert body["used"][0] == [0, len("Colin d'Alaska 72%")]
        assert body["warnings"] == []

    def test_what_a_person_left_out_is_not_read(self, client: Client):
        body = json_post(
            client, {"text": FISH_TEXT, "language": "fr", "ignored": [FISH_ZONE]}
        ).json()

        [fish, *_others] = body["rows"]
        assert fish["ingredients"] is None
        assert all(
            not (start < FISH_ZONE[1] and FISH_ZONE[0] < end)
            for start, end in body["used"]
        )

    def test_a_text_read_badly_gives_nothing_and_says_why(self, client: Client):
        body = json_post(client, {"text": "Farine, , sel", "language": "fr"}).json()

        assert body["rows"] == []
        assert json.loads(body["ingredients"]) == []
        assert body["used"] == []
        [warning] = body["warnings"]
        assert warning["stops"] is True
        assert warning["message"]

    def test_the_names_are_looked_up_as_the_page_will_save_them(self, client: Client):
        ReferenceIngredient.objects.create(
            name_fr="farine de blé", name_en="wheat flour", status="curated"
        )

        body = json_post(
            client, {"text": "Farine de blé, sel", "language": "fr"}
        ).json()

        [flour, salt] = body["rows"]
        assert flour["reference"] != salt["reference"]

    @pytest.mark.parametrize(
        "body",
        [
            {"text": "Sel", "ignored": [[5, 2]]},
            {"text": "Sel", "ignored": [[-1, 2]]},
            {"text": "Sel", "ignored": [[1, 2, 3]]},
            {"language": "fr"},
            "not an object",
        ],
    )
    def test_a_request_that_makes_no_sense_is_refused(self, client: Client, body: Any):
        assert json_post(client, body).status_code == HTTPStatus.BAD_REQUEST

    def test_it_needs_a_signed_in_user_and_a_post(self, client: Client):
        assert (
            client.get(reverse("read_label")).status_code
            == HTTPStatus.METHOD_NOT_ALLOWED
        )
        client.logout()

        assert json_post(client, {"text": "Sel"}).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
class TestLeavingPlacesOut:
    """What the product page keeps of the places a person left out of the list."""

    def stored(self, **fields: Any) -> Product:
        return Product.objects.create(
            barcode=NUTELLA, name="Nutella", ingredients_text=FISH_TEXT, **fields
        )

    def test_the_page_hands_the_script_the_text_what_was_read_and_what_was_left_out(
        self, client: Client
    ):
        product = self.stored(
            ingredients_ignored=[FISH_ZONE], ingredients_language="fr"
        )

        page = client.get(reverse("edit_product", args=[product.pk])).content.decode()

        state = state_of(page)
        assert state["text"] == FISH_TEXT
        assert state["ignored"] == [FISH_ZONE]
        assert state["language"] == "fr"
        assert state["barcode"] == NUTELLA
        # Read without the zone: its words are not among the places.
        assert state["used"][0] == [0, len("Colin d'Alaska 72%")]
        assert all(
            end <= FISH_ZONE[0] or start >= FISH_ZONE[1] for start, end in state["used"]
        )
        form = client.get(reverse("edit_product", args=[product.pk])).context["form"]
        assert json.loads(form["ingredients_ignored"].value()) == [FISH_ZONE]

    def test_a_lookup_starts_with_nothing_left_out_and_says_the_language(
        self, client: Client
    ):
        product = self.stored(ingredients_ignored=[FISH_ZONE])
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]
        taken = taken_from_lookup(client, text=FISH_TEXT)

        assert taken["ingredients_ignored"] == "[]"
        assert taken["ingredients_lc"] == "fr"
        client.post(url, submitted(form, **taken))

        product.refresh_from_db()
        assert product.ingredients_ignored == []
        assert product.ingredients_text == FISH_TEXT

    def test_a_correction_made_on_the_page_is_saved_with_the_ingredients_it_gave(
        self, client: Client
    ):
        product = self.stored(ingredients_language="fr")
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]
        # What the script does: read again, and keep the answer in the form.
        reading = json_post(
            client, {"text": FISH_TEXT, "language": "fr", "ignored": [FISH_ZONE]}
        ).json()

        response = client.post(
            url,
            submitted(
                form,
                off_barcode=product.pk,
                off_ingredients=reading["ingredients"],
                off_ingredients_text=FISH_TEXT,
                ingredients_ignored=json.dumps([FISH_ZONE]),
            ),
        )

        assert response.status_code == HTTPStatus.FOUND
        product.refresh_from_db()
        assert product.ingredients_ignored == [FISH_ZONE]
        assert product.ingredients_text == FISH_TEXT
        assert product.ingredients_language == "fr"
        [fish, *_] = product.ingredients.filter(parent=None).order_by("id")
        assert fish.item.name == "colin d'alaska"
        assert not product.ingredients.filter(parent=fish).exists()
        assert product.ingredients.count() == len(reading["rows"])

    def test_the_places_come_back_when_the_form_has_to_be_corrected(
        self, client: Client
    ):
        product = self.stored()
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]

        response = client.post(
            url,
            submitted(
                form,
                name="",
                off_barcode=product.pk,
                off_ingredients="[]",
                off_ingredients_text=FISH_TEXT,
                ingredients_ignored=json.dumps([FISH_ZONE]),
            ),
        )

        assert state_of(response.content.decode())["ignored"] == [FISH_ZONE]

    def test_a_plain_edit_leaves_the_places_alone(self, client: Client):
        product = self.stored(
            ingredients_ignored=[FISH_ZONE], ingredients_language="fr"
        )
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]

        client.post(url, submitted(form, name="Renamed"))

        product.refresh_from_db()
        assert product.name == "Renamed"
        assert product.ingredients_ignored == [FISH_ZONE]
        assert product.ingredients_language == "fr"

    def test_putting_everything_back_empties_the_places(self, client: Client):
        product = self.stored(ingredients_ignored=[FISH_ZONE])
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url).context["form"]
        reading = json_post(client, {"text": FISH_TEXT, "language": "fr"}).json()

        client.post(
            url,
            submitted(
                form,
                off_barcode=product.pk,
                off_ingredients=reading["ingredients"],
                off_ingredients_text=FISH_TEXT,
                ingredients_ignored="[]",
            ),
        )

        product.refresh_from_db()
        assert product.ingredients_ignored == []

    def test_saving_a_lookup_keeps_the_language_of_the_text(self, client: Client):
        form = looked_up(client, language="en").context["form"]

        client.post(reverse("create_product"), submitted(form))

        product = Product.objects.get(pk=NUTELLA)
        assert (product.ingredients_language, product.ingredients_ignored) == ("fr", [])

    def test_places_that_are_not_places_are_refused_not_saved(self, client: Client):
        form = looked_up(client).context["form"]

        response = client.post(
            reverse("create_product"), submitted(form, ingredients_ignored="[[4, 1]]")
        )

        assert not Product.objects.exists()
        assert response.status_code == HTTPStatus.OK


@pytest.mark.django_db
class TestOffLookupView:
    """What the page asks OpenFoodFacts for, to set against the form."""

    def ask(self, client: Client, barcode: str = NUTELLA, **product: Any):
        with patch(
            "opennutrilab.products.views.fetch_from_off",
            return_value=off_product(**product),
        ):
            return client.get(reverse("lookup_off"), {"barcode": barcode})

    def test_it_gives_the_fields_the_photo_and_the_list_apart(self, client: Client):
        response = self.ask(client, serving_size="30 g", quantity="400 g")

        assert response.status_code == HTTPStatus.OK
        found = response.json()
        assert found["fields"]["name"] == "Nutella"
        assert found["fields"]["nutrient_energy"] == "2252"
        assert found["fields"]["serving_quantity"] == "30"
        assert found["fields"]["package_quantity"] == "400"
        # Hidden bookkeeping is not a field to choose.
        assert not [n for n in found["fields"] if n.startswith("off_")]
        assert "ingredients_lc" not in found["fields"]
        assert found["image"] == IMAGE_URL
        label = found["label"]
        assert label["barcode"] == NUTELLA
        assert label["text"] == "Sucre 56,3 %, lait (lait écrémé)"
        assert label["language"] == "fr"
        assert [row["name"] for row in label["rows"]][:2] == ["sucre", "lait"]
        assert json.loads(label["ingredients"])[0]["name"] == "sucre"
        assert label["used"][0] == [0, len("Sucre 56,3 %")]
        assert found["notices"] == []

    def test_it_gives_no_serving_when_openfoodfacts_has_none(self, client: Client):
        found = self.ask(client, serving_size=None).json()

        assert "serving_quantity" not in found["fields"]
        assert "package_quantity" not in found["fields"]

    def test_what_could_not_be_read_comes_as_notices(self, client: Client):
        found = self.ask(client, serving_size="a spoonful").json()

        assert any("serving" in notice for notice in found["notices"]), found

    def test_a_list_that_looks_badly_read_is_told_and_gives_no_ingredient(
        self, client: Client
    ):
        found = self.ask(client, ingredients_text="Sucre [lait").json()

        assert found["label"]["rows"] == []
        assert found["label"]["text"] == "Sucre [lait"
        assert any("looks badly read" in notice for notice in found["notices"])

    def test_a_product_openfoodfacts_does_not_have_is_a_404_with_the_reason(
        self, client: Client
    ):
        with patch(
            "opennutrilab.products.views.fetch_from_off",
            side_effect=OFFProductNotFoundError("not found"),
        ):
            response = client.get(reverse("lookup_off"), {"barcode": NUTELLA})

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert "was not found in OpenFoodFacts" in response.json()["error"]

    def test_an_openfoodfacts_that_cannot_be_reached_is_a_502(self, client: Client):
        with patch(
            "opennutrilab.products.views.fetch_from_off",
            side_effect=OFFError("down"),
        ):
            response = client.get(reverse("lookup_off"), {"barcode": NUTELLA})

        assert response.status_code == HTTPStatus.BAD_GATEWAY
        assert "could not be reached" in response.json()["error"]

    def test_it_needs_a_barcode(self, client: Client):
        assert client.get(reverse("lookup_off")).status_code == HTTPStatus.BAD_REQUEST
        assert (
            client.get(reverse("lookup_off"), {"barcode": " "}).status_code
            == HTTPStatus.BAD_REQUEST
        )

    def test_it_needs_a_signed_in_user(self, client: Client):
        client.logout()

        response = client.get(reverse("lookup_off"), {"barcode": NUTELLA})

        assert response.status_code == HTTPStatus.FORBIDDEN


SEND = {"barcode": NUTELLA, "text": "Sucre, lait.", "language": "fr"}


@pytest.mark.django_db
class TestSendLabelView:
    """A corrected list sent to OpenFoodFacts, by staff only."""

    @pytest.fixture(autouse=True)
    def _account(self, settings: SettingsWrapper) -> None:  # pyright: ignore[reportUnusedFunction]
        settings.OFF_USER_ID = "opennutrilab"
        settings.OFF_PASSWORD = "secret"  # noqa: S105

    def send(self, client: Client, body: Any = SEND):
        return client.post(
            reverse("send_label"), json.dumps(body), content_type="application/json"
        )

    @pytest.fixture(autouse=True)
    def _staff(self, client: Client) -> None:  # pyright: ignore[reportUnusedFunction]
        client.force_login(UserFactory(is_staff=True))

    def test_staff_send_the_list_and_are_told_it_was_taken(self, client: Client):
        with patch(
            "opennutrilab.products.views.send_ingredients_text_to_off",
            return_value=True,
        ) as send:
            response = self.send(client)

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"sent": True}
        send.assert_called_once_with(NUTELLA, "Sucre, lait.", "fr")

    def test_it_says_when_openfoodfacts_already_had_the_list(self, client: Client):
        with patch(
            "opennutrilab.products.views.send_ingredients_text_to_off",
            return_value=False,
        ):
            assert self.send(client).json() == {"sent": False}

    def test_other_users_cannot_send(self, client: Client, user: User):
        client.force_login(user)

        with patch("opennutrilab.products.views.send_ingredients_text_to_off") as send:
            response = self.send(client)

        assert response.status_code == HTTPStatus.FORBIDDEN
        send.assert_not_called()

    def test_a_visitor_cannot_send(self, client: Client):
        client.logout()

        with patch("opennutrilab.products.views.send_ingredients_text_to_off") as send:
            response = self.send(client)

        assert response.status_code == HTTPStatus.FORBIDDEN
        send.assert_not_called()

    def test_without_an_account_there_is_nothing_to_send_with(
        self, client: Client, settings: SettingsWrapper
    ):
        settings.OFF_USER_ID = ""
        settings.OFF_PASSWORD = ""
        with patch("opennutrilab.products.views.send_ingredients_text_to_off") as send:
            response = self.send(client)

        assert response.status_code == HTTPStatus.NOT_FOUND
        send.assert_not_called()

    @pytest.mark.parametrize(
        "body",
        [
            {**SEND, "barcode": "../x"},
            {**SEND, "text": ""},
            {**SEND, "language": "f"},
            {"text": "x"},
        ],
    )
    def test_a_request_that_makes_no_sense_is_refused(self, client: Client, body: Any):
        with patch("opennutrilab.products.views.send_ingredients_text_to_off") as send:
            response = self.send(client, body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        send.assert_not_called()

    def test_a_product_openfoodfacts_does_not_have_is_told(self, client: Client):
        with patch(
            "opennutrilab.products.views.send_ingredients_text_to_off",
            side_effect=OFFProductNotFoundError("not found"),
        ):
            response = self.send(client)

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert NUTELLA in response.json()["error"]

    def test_a_refusal_of_openfoodfacts_is_a_502_that_does_not_leak_its_detail(
        self, client: Client
    ):
        with patch(
            "opennutrilab.products.views.send_ingredients_text_to_off",
            side_effect=OFFError("password rejected for opennutrilab"),
        ):
            response = self.send(client)

        assert response.status_code == HTTPStatus.BAD_GATEWAY
        assert "password" not in response.json()["error"]


@pytest.mark.django_db
class TestSendingIsOfferedToStaffWithAnAccountOnly:
    def config(self, client: Client) -> dict[str, Any]:
        response = client.get(reverse("create_product"))
        return response.context["product_form_config"]["ingredientsText"]

    @pytest.fixture(autouse=True)
    def _account(self, settings: SettingsWrapper) -> None:  # pyright: ignore[reportUnusedFunction]
        settings.OFF_USER_ID = "opennutrilab"
        settings.OFF_PASSWORD = "secret"  # noqa: S105

    def test_staff_with_an_account(self, client: Client):
        client.force_login(UserFactory(is_staff=True))

        assert self.config(client)["canSend"] is True

    def test_not_other_users(self, client: Client):
        assert self.config(client)["canSend"] is False

    def test_not_without_an_account(self, client: Client, settings: SettingsWrapper):
        settings.OFF_USER_ID = ""
        settings.OFF_PASSWORD = ""
        client.force_login(UserFactory(is_staff=True))

        assert self.config(client)["canSend"] is False
