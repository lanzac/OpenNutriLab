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

from opennutrilab.products.api.openfoodfacts.schemas import OFFProductSchema
from opennutrilab.products.api.openfoodfacts.services import OFFError
from opennutrilab.products.api.openfoodfacts.services import OFFProductNotFoundError
from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.forms import ProductForm
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import IngredientTaxon
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


@pytest.mark.django_db
class TestProductEditView:
    @patch("opennutrilab.products.views.fetch_from_off")
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
        product = Product.objects.create(barcode=NUTELLA, name="Stored Product")
        mock_fetch_from_off.return_value = off_product()
        mock_get.side_effect = requests.ConnectTimeout("timed out")
        url = reverse("edit_product", args=[product.pk])
        form = client.get(url, {"reset": "1"}).context["form"]
        assert form["off_barcode"].value() == NUTELLA

        response: HttpResponse = client.post(url, submitted(form), follow=True)

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
    """The create page (or the edit one, with reset=1) after an OFF lookup."""
    path = query.pop("path", reverse("create_product"))
    params = {"barcode": NUTELLA, **query}
    with patch(
        "opennutrilab.products.views.fetch_from_off",
        return_value=off_product(ingredients_text=text),
    ):
        return client.get(path, params, headers={"accept-language": language})


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
        # Read only, and without a name: shown, not posted.
        assert re.search(r"<textarea[^>]*\sreadonly", page)
        assert 'name="ingredients' not in page.split("<textarea", 1)[1].split(">", 1)[0]
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
        assert "Reset data" in page

    def test_a_lookup_that_has_no_list_says_so(self, client: Client):
        with translation.override("en"):
            page = looked_up(client, text="").content.decode()

        assert "OpenFoodFacts has no ingredient list for this product." in page

    def test_a_new_product_not_looked_up_has_no_block(self, client: Client):
        page = client.get(reverse("create_product")).content.decode()

        assert 'id="ingredients-text"' not in page

    def test_reset_shows_the_current_text_and_saving_replaces_the_saved_one(
        self, client: Client
    ):
        product = Product.objects.create(
            barcode=NUTELLA, name="Nutella", ingredients_text="An old text"
        )
        url = reverse("edit_product", args=[product.pk])

        response = looked_up(client, path=url, reset="1")

        page = response.content.decode()
        assert "An old text" not in page
        assert "&lt;b&gt;lait&lt;/b&gt;" in page
        client.post(url, submitted(response.context["form"]))
        product.refresh_from_db()
        assert product.ingredients_text == LABEL_TEXT

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

    with translation.override("en-us"), django_assert_max_num_queries(3):
        rows = ingredient_rows_from_db(product)

    assert [r["name"] for r in rows] == ["Sugar", "Milk powder"]
    assert [r["percentage"] for r in rows] == [Decimal("56.30"), None]
    assert rows[0]["ingredients"] is None
    assert [(c["name"], c["reference"]) for c in rows[1]["ingredients"]] == [
        ("milk", "Curated")
    ]
    # A reference created for a name nobody had is still to review.
    assert [r["reference"] for r in rows] == ["To review", "To review"]
    assert Ingredient.objects.filter(product=product).count() == 3  # noqa: PLR2004


@pytest.fixture
def taxonomy(db) -> None:
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
    taxonomy, django_assert_num_queries: Any
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

    # The references and the preparations by name, the taxonomy, the references
    # and the preparations by correspondence, then the French names.
    with translation.override("fr-fr"), django_assert_num_queries(6):
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
    taxonomy, django_assert_num_queries: Any
):
    items = [IngredientInput(name="oat flakes", off_id="en:oat-flakes")]

    with translation.override("en-us"), django_assert_num_queries(5):
        rows = ingredient_rows_from_inputs(items)

    assert [r["name"] for r in rows] == ["oat flakes"]


def test_rows_from_db_show_the_name_in_the_language_served(
    taxonomy, django_assert_max_num_queries: Any
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
    assert ReferenceIngredient.objects.get(name_en="date").name_fr == "datte"


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
