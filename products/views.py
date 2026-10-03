import logging
from typing import Any

from django.contrib import messages
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.urls import reverse_lazy
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from vanilla import CreateView
from vanilla import DeleteView
from vanilla import ListView
from vanilla import UpdateView

from .api.openfoodfacts.schemas import product_schema_to_form_data
from .api.openfoodfacts.services import OFFError
from .api.openfoodfacts.services import OFFProductNotFoundError
from .api.openfoodfacts.services import fetch_from_off
from .api.openfoodfacts.services import to_ingredient_inputs
from .api.schemas.inbound import IngredientInput
from .api.schemas.inbound import validate_off_image_url
from .forms import INGREDIENTS_JSON
from .forms import ProductForm
from .models import Ingredient
from .models import Product
from .services.product_services import references_by_lowercase_name

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


class ProductFormViewMixin:
    """What the create and edit pages share."""

    request: HttpRequest

    def form_valid(self, form: ProductForm):  # pyright: ignore[reportIncompatibleMethodOverride]
        response = super().form_valid(form)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        if form.image_fetch_failed:
            report_image_fetch_failure(self.request, barcode=form.instance.barcode)
        return response  # pyright: ignore[reportUnknownVariableType]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        form: ProductForm = context["form"]
        context["product_form_labels"] = product_form_labels()
        context["ingredient_rows"] = ingredient_rows_for(form)
        return context


class ProductCreateView(ProductFormViewMixin, CreateView):
    model = Product
    form_class = ProductForm
    success_url = reverse_lazy("list_products")

    def get_form(
        self,
        data=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        files=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        **kwargs: Any,
    ) -> ProductForm:
        initial: dict[str, Any] = {}
        # Only on GET: the POST that saves carries what this lookup returned
        # in hidden fields, so OpenFoodFacts is asked once per page, not again
        # at save time.
        barcode: str | None = self.request.GET.get("barcode")
        if self.request.method == "GET" and barcode:
            initial = initial_from_off(self.request, barcode) or {"barcode": barcode}
        return ProductForm(data=data, files=files, initial=initial, **kwargs)


class ProductEditView(ProductFormViewMixin, UpdateView):
    model = Product
    form_class = ProductForm
    success_url = reverse_lazy("list_products")

    def get_form(
        self,
        data=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        files=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        **kwargs: Any,  # https://adamj.eu/tech/2021/05/11/python-type-hints-args-and-kwargs/
    ) -> ProductForm:
        initial: dict[str, Any] = {}
        product: Product = kwargs["instance"]
        if self.request.method == "GET" and self.request.GET.get("reset") == "1":
            # On failure the form keeps the stored values; the notice says why.
            initial = initial_from_off(self.request, product.barcode) or {}
            # The barcode is the stored primary key, whatever OFF spelled it as.
            initial.pop("barcode", None)
            if initial:
                initial["off_barcode"] = product.barcode
        return ProductForm(data=data, files=files, initial=initial, **kwargs)


class ProductDeleteView(DeleteView):
    model = Product
    success_url = reverse_lazy("list_products")
    # The product list POSTs here after its own confirm() prompt. A GET would
    # render a confirmation template that does not exist, so refuse it.
    http_method_names = ["post"]


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


def report_off_failure(request: HttpRequest, barcode: str, error: OFFError) -> None:
    """
    Log a failed OpenFoodFacts lookup and tell the user what to do next.

    The exception message carries the upstream detail, which is useful in the
    log but too noisy for a page banner, so only the cause is shown.
    """
    logger.warning("OpenFoodFacts lookup failed for %s: %s", barcode, error)

    if isinstance(error, OFFProductNotFoundError):
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


def initial_from_off(request: HttpRequest, barcode: str) -> dict[str, Any] | None:
    """
    Form initial data from an OpenFoodFacts lookup, or None if it failed.

    Besides the visible fields, it fills the hidden off_* fields that carry the
    photo URL and the ingredient tree to the POST that saves them.
    """
    try:
        fetched = fetch_from_off(query_barcode=barcode)
    except OFFError as e:
        report_off_failure(request, barcode=barcode, error=e)
        return None

    initial: dict[str, Any] = product_schema_to_form_data(fetched).dict()
    image_url = initial.pop("image_url", None)
    try:
        initial["off_image_url"] = validate_off_image_url(image_url)
    except ValueError:
        # A photo hosted somewhere the services refuse to download from.
        initial["off_image_url"] = None
    initial["off_barcode"] = fetched.barcode
    initial["off_ingredients"] = INGREDIENTS_JSON.dump_json(
        to_ingredient_inputs(fetched.ingredients)
    ).decode()
    return initial


def ingredient_rows_for(form: ProductForm) -> list[dict[str, Any]]:
    """
    Rows for the ingredients tree (frontend/.../ingredients-table.js).

    The OpenFoodFacts tree this page would save if there is one, otherwise
    what is stored for the product.
    """
    from_off = form.off_ingredients_for_display()
    if from_off is not None:
        return ingredient_rows_from_inputs(
            from_off, set(references_by_lowercase_name(from_off))
        )
    if form.is_edit:
        return ingredient_rows_from_db(form.instance)
    return []


def ingredient_rows_from_inputs(
    items: list[IngredientInput], reference_names: set[str]
) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "percentage": item.percentage,
            "has_reference": item.name.strip().lower() in reference_names,
            "ingredients": (
                ingredient_rows_from_inputs(item.sub_ingredients, reference_names)
                or None
            ),
        }
        for item in items
    ]


def ingredient_rows_from_db(product: Product) -> list[dict[str, Any]]:
    """The stored ingredient tree, in one query."""
    ingredients = list(Ingredient.objects.filter(product=product).order_by("id"))
    rows: dict[int, dict[str, Any]] = {
        ingredient.id: {
            "name": ingredient.name,
            "percentage": ingredient.percentage,
            "has_reference": ingredient.has_reference,
            "ingredients": None,
        }
        for ingredient in ingredients
    }
    roots: list[dict[str, Any]] = []
    for ingredient in ingredients:
        row = rows[ingredient.id]
        if ingredient.parent_id is None:
            roots.append(row)
        else:
            parent = rows[ingredient.parent_id]
            parent["ingredients"] = [*(parent["ingredients"] or []), row]
    return roots
