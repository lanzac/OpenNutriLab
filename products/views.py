import json
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any

from django.contrib import messages
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.urls import reverse_lazy
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from ninja.errors import HttpError
from vanilla import CreateView
from vanilla import DeleteView
from vanilla import ListView
from vanilla import UpdateView

from .api.openfoodfacts.schemas import OFFProductSchema
from .api.openfoodfacts.schemas import ProductFormSchema
from .api.openfoodfacts.schemas import product_schema_to_form_data
from .api.openfoodfacts.services import build_ingredient_json_from_schema
from .api.openfoodfacts.services import fetch_from_off
from .api.openfoodfacts.services import get_schema_from_ingredients
from .forms import ProductForm
from .models import IngredientRef
from .models import Product

if TYPE_CHECKING:
    from products.api.openfoodfacts.schemas import OFFIngredientSchema

logger = logging.getLogger(__name__)


class ProductListView(ListView):
    model = Product

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

        # Everything the React list needs from the server, handed over as one
        # |json_script blob (see frontend/src/apps/products/list-entry.jsx).
        #
        # csrfToken cannot be read from the cookie: CSRF_COOKIE_HTTPONLY is on,
        # so document.cookie never exposes it. The delete form is a plain POST
        # to Django, so it needs the token the way {% csrf_token %} used to
        # provide it before this page moved to React.
        #
        # languageCode drives Intl date formatting client-side, which otherwise
        # follows the browser's locale rather than the one Django is serving.
        #
        # Labels are translated here rather than in JS so that the .po
        # catalogue stays the single source of truth while the migration is in
        # progress.
        # TODO(migration/vite-react): drop this in favour of a JS-side
        # catalogue once Django no longer renders the page shell.
        context["product_list_props"] = {
            "csrfToken": get_token(self.request),
            "languageCode": get_language(),
            "labels": {
                "productName": _("Product name"),
                "createdAt": _("Created at"),
                "actions": _("Actions"),
                "edit": _("Edit"),
                "delete": _("Delete"),
                "editAndDelete": _("Edit and Delete product"),
                "loading": _("Loading…"),
                "loadError": _("Failed to load products."),
                # %(name)s is interpolated client-side with the product name.
                "confirmDelete": _('Delete "%(name)s"?'),
            },
        }
        return context


class ProductCreateView(CreateView):
    model = Product
    form_class = ProductForm
    success_url = reverse_lazy("list_products")

    def get_form(
        self,
        data=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        files=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        extra_data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> form_class:
        barcode: str | None = self.request.GET.get("barcode")
        initial: dict[str, Any] = {}
        if barcode:
            try:
                fetched_product: OFFProductSchema = fetch_from_off(
                    query_barcode=barcode
                )
            except HttpError as e:
                # A barcode OpenFoodFacts does not know is an ordinary outcome
                # here, not a server fault. Left uncaught this would be a 500:
                # fetch_from_off speaks django-ninja's HttpError, which only
                # becomes a response inside an API route. Keep the form usable
                # with the barcode filled in so it can be entered by hand.
                report_off_failure(self.request, barcode=barcode, error=e)
                initial = {"barcode": barcode}
            else:
                initial, extra_data = prepare_product_form_data(
                    fetched_product=fetched_product, extra_data=extra_data
                )

        return self.form_class(
            data=data,
            files=files,
            initial=initial,
            extra_data=extra_data,
            **kwargs,
        )

    def form_valid(self, form: form_class):
        response = super().form_valid(form)
        if getattr(form, "image_fetch_failed", False):
            report_image_fetch_failure(
                self.request, barcode=form.cleaned_data["barcode"]
            )
        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        context["macronutrients_api_url"] = reverse_lazy(
            "api-1.0.0:get_macronutrients_form_data"
        )
        context["product_form_labels"] = product_form_labels()
        return context


class ProductEditView(UpdateView):
    model = Product
    form_class = ProductForm
    success_url = reverse_lazy("list_products")

    def get_form(
        self,
        data=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        files=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        extra_data: dict[str, Any] | None = None,
        **kwargs: Any,  # https://adamj.eu/tech/2021/05/11/python-type-hints-args-and-kwargs/
    ) -> form_class:
        reset: bool = self.request.GET.get("reset") == "1"
        product_instance: Product | None = kwargs.get("instance")
        if product_instance is None:
            msg = "Product instance is required to edit a product."
            raise ValueError(msg)

        fetched_product: OFFProductSchema | None = None
        if reset:
            try:
                fetched_product = fetch_from_off(query_barcode=product_instance.barcode)
            except HttpError as e:
                # Same trap as ProductCreateView. Leaving fetched_product as
                # None falls back to the values already stored for this
                # product, so a failed reset shows the form unchanged.
                report_off_failure(
                    self.request, barcode=product_instance.barcode, error=e
                )

        initial, extra_data = prepare_product_form_data(
            product_instance=product_instance,
            fetched_product=fetched_product,
            extra_data=extra_data,
        )

        return self.form_class(
            data=data,
            files=files,
            initial=initial,
            extra_data=extra_data,
            **kwargs,
        )

    def form_valid(self, form: form_class):
        response = super().form_valid(form)
        if getattr(form, "image_fetch_failed", False):
            report_image_fetch_failure(
                self.request, barcode=form.cleaned_data["barcode"]
            )
        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        context["macronutrients_api_url"] = reverse_lazy(
            "api-1.0.0:get_macronutrients_form_data"
        )
        context["product_form_labels"] = product_form_labels()
        return context


class ProductDeleteView(DeleteView):
    model = Product
    success_url = reverse_lazy("list_products")


# Utilities


def product_form_labels() -> dict[str, Any]:
    """
    Translated strings for the vanilla-JS parts of the product form.

    Handed to the page as one |json_script blob (see product_form.html),
    consumed by frontend/src/apps/products/form-entry.js and passed down to
    the ingredients table, the macronutrients chart and the barcode actions.
    Same reasoning as ProductListView.product_list_props: translating here
    keeps the .po catalogue the single source of truth instead of growing a
    parallel JS-side one.

    Several keys reuse the exact English text already translated elsewhere
    on this page (the "Fat" / "of which Saturates" family from
    ProductForm._add_nutritional_value_fields, "Name" from ProductForm.Meta.
    labels): gettext matches by literal string, so no new .po entries are
    needed for those, and the chart's wording for saturated fat and sugars
    stays consistent with the input fields right next to it.
    """
    return {
        "ingredientsTable": {
            "name": _("Name"),
            "percentage": _("Percentage"),
            "recognized": _("Recognized"),
        },
        # Keyed like Macronutrient.name (see the migration that seeds it:
        # products/migrations/0006_alter_macronutrient_labels_and_more.py),
        # not like the display label, so the chart's structure survives
        # translation. "others" has no corresponding row: it is the chart's
        # own synthetic remainder slice.
        "macronutrientsGraph": {
            "fat": _("Fat"),
            "saturatedFat": _("of which Saturates"),
            "carbohydrates": _("Carbohydrates"),
            "sugars": _("of which Sugars"),
            "fiber": _("Fiber"),
            "proteins": _("Proteins"),
            "others": _("Others"),
        },
        "barcodeActions": {
            "enterBarcode": _("Please enter a barcode."),
        },
    }


def report_off_failure(request: HttpRequest, barcode: str, error: HttpError) -> None:
    """
    Log a failed OpenFoodFacts lookup and tell the user what to do next.

    The exception message carries the upstream detail, which is useful in the
    log but too noisy for a page banner, so only the cause is shown.
    """
    logger.warning(
        "OpenFoodFacts lookup failed for %s: %s %s",
        barcode,
        error.status_code,
        error.message,
    )

    if error.status_code == HTTPStatus.NOT_FOUND:
        text = _(
            "Barcode %(barcode)s was not found in OpenFoodFacts. "
            "Please fill in the details by hand."
        )
    else:
        text = _(
            "OpenFoodFacts could not be reached for barcode %(barcode)s. "
            "Please try again, or fill in the details by hand."
        )
    messages.warning(request, text % {"barcode": barcode})


def report_image_fetch_failure(request: HttpRequest, barcode: str) -> None:
    """
    Tell the user the product was saved but its OpenFoodFacts image was not.

    ProductForm.save() already logs the download error itself; this only
    needs to stop the user from assuming the save failed, and point them at
    a manual upload.
    """
    text = _(
        "Product %(barcode)s was saved, but its photo could not be "
        "downloaded from OpenFoodFacts. Please try again, or upload one by hand."
    )
    messages.warning(request, text % {"barcode": barcode})


def prepare_product_form_data(
    product_instance: Product | None = None,
    fetched_product: OFFProductSchema | None = None,
    extra_data: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Prepare `initial` and `extra_data` for Product form.

    :param product_instance: Product from DB (for Edit)
    :param fetched_product: OFFProductSchema from API (for Create or Edit reset)
    :param reset: whether to force fetch_product even on Edit
    :param extra_data: existing extra_data dict
    :return: tuple(initial, extra_data)
    """
    initial: dict[str, Any] = {}
    extra_data = extra_data or {}

    reference_names = {
        name.lower() for name in IngredientRef.objects.values_list("name", flat=True)
    }

    # Use fetched_product if provided (Create or Edit reset)
    if fetched_product is not None:
        # convert to form schema
        product_form: ProductFormSchema = product_schema_to_form_data(fetched_product)
        initial.update(product_form.dict())
        extra_data["fetched_image_url"] = product_form.image_url

        # Ingredients from fetched_product
        extra_data["ingredients"] = fetched_product.ingredients
        if fetched_product.ingredients:
            extra_data["ingredients_json"] = json.dumps(
                [
                    build_ingredient_json_from_schema(ingredient, reference_names)
                    for ingredient in fetched_product.ingredients
                ]
            )
    elif product_instance is not None:
        # Edit normal (no reset) → ingredients from DB
        ingredients: list[OFFIngredientSchema] = get_schema_from_ingredients(
            product_instance
        )
        extra_data["ingredients"] = ingredients
        extra_data["ingredients_json"] = json.dumps(
            [
                build_ingredient_json_from_schema(ingredient, reference_names)
                for ingredient in ingredients
            ]
        )
    else:
        msg = "Either product_instance or fetched_product must be provided"
        raise ValueError(msg)

    return initial, extra_data
