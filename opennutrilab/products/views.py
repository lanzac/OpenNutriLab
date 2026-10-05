import logging
from decimal import Decimal
from typing import Any
from typing import cast
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import prefetch_related_objects
from django.http import HttpRequest
from django.http import HttpResponseRedirect
from django.middleware.csrf import get_token
from django.urls import reverse_lazy
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from vanilla import CreateView
from vanilla import DeleteView
from vanilla import ListView
from vanilla import UpdateView

from .api.openfoodfacts.services import OFFError
from .api.openfoodfacts.services import OFFProductNotFoundError
from .api.openfoodfacts.services import declared_nutrients_from_off
from .api.openfoodfacts.services import fetch_from_off
from .api.openfoodfacts.services import ingredient_inputs_from_label
from .api.schemas.inbound import IngredientInput
from .api.schemas.inbound import validate_off_image_url
from .api.schemas.outbound import EstimateOut
from .forms import INGREDIENTS_JSON
from .forms import ProductForm
from .forms import nutrient_field
from .models import Ingredient
from .models import IngredientTaxon
from .models import Nutrient
from .models import Product
from .models import ReferenceIngredient
from .services.estimate_report import build_estimate
from .services.label_parser import LabelWarning
from .services.product_services import plain_amount
from .services.reference_services import CIQUAL_SOURCE_PREFIX
from .services.reference_services import existing_references
from .services.reference_services import name_key
from .services.reference_services import walk_ingredients

logger = logging.getLogger(__name__)

# The CIQUAL site is a single-page app: the fragment is its route, and it
# shows an empty sheet, not an error, for a code it does not know.
CIQUAL_FOOD_URL = "https://ciqual.anses.fr/#/aliments/{code}"


class ProductListView(LoginRequiredMixin, ListView):
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
            # Only staff may delete (see ProductDeleteView); the list hides
            # the button from everyone else.
            "canDelete": self.request.user.is_staff,
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

    # super() is vanilla-views' CreateView/UpdateView, which ship no types.
    def form_valid(self, form: ProductForm) -> HttpResponseRedirect:
        response = cast(
            "HttpResponseRedirect",
            super().form_valid(form),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        )
        if form.image_fetch_failed:
            report_image_fetch_failure(self.request, barcode=form.instance.barcode)
        for warning in form.declared_value_warnings:
            messages.warning(self.request, warning)
        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = cast(
            "dict[str, Any]",
            super().get_context_data(**kwargs),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        )
        form = cast("ProductForm", context["form"])
        context["product_form_config"] = product_form_config()
        context["ingredient_rows"] = ingredient_rows_for(form)
        return context


class ProductCreateView(LoginRequiredMixin, ProductFormViewMixin, CreateView):
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


class ProductEditView(LoginRequiredMixin, ProductFormViewMixin, UpdateView):
    model = Product
    form_class = ProductForm
    success_url = reverse_lazy("list_products")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        # Only when the page is first shown: it is worked out on each request, and a
        # form posted back to be corrected has nothing new to say about the saved
        # product.
        if self.request.method == "GET":
            form = cast("ProductForm", context["form"])
            context["estimate"] = estimate_for_page(form.instance)
            context["estimate_failed"] = context["estimate"] is None
        return context

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


class ProductDeleteView(UserPassesTestMixin, DeleteView):
    model = Product
    success_url = reverse_lazy("list_products")

    def test_func(self) -> bool:
        # The catalogue is shared by every user, so removing a product is
        # reserved to staff. Anonymous visitors are sent to the login page,
        # other signed-in users get a 403.
        return self.request.user.is_staff

    # The product list POSTs here after its own confirm() prompt. A GET would
    # render a confirmation template that does not exist, so refuse it.
    http_method_names = ["post"]


# Utilities


def estimate_for_page(product: Product) -> EstimateOut | None:
    """
    The estimate of a stored product, or None when it could not be worked out.

    The page is for editing the product, and must not break because the solver
    did: only its own failure is caught, and it is logged.
    """
    try:
        return build_estimate(product)
    except RuntimeError:
        logger.exception(
            "The estimate of product %s could not be worked out", product.pk
        )
        return None


def product_form_config() -> dict[str, Any]:
    """
    What the vanilla-JS parts of the product form need from the server.

    Handed to the page as one |json_script blob (see product_form.html),
    consumed by frontend/src/apps/products/form-entry.js and passed down to
    the ingredients table, the nutrient chart and the barcode actions. Text
    is translated here, so the .po catalogue stays the single source of truth
    instead of growing a parallel JS-side one.
    """
    return {
        "ingredientsTable": {
            "name": _("Name"),
            "percentage": _("Percentage"),
            "ciqual": _("CIQUAL code"),
            "reference": _("Reference status"),
        },
        "nutrientChart": {
            # One slice per declared mass nutrient, straight from the
            # catalogue: parents and children are linked by code, so the
            # chart's structure does not depend on the displayed language.
            "slices": [
                {
                    "code": n.code,
                    "field": nutrient_field(n.code),
                    "parent": n.parent_id,
                    "label": n.name,
                }
                for n in Nutrient.objects.filter(on_label=True, unit=Nutrient.Unit.GRAM)
            ],
            # The chart's own remainder slice, with no nutrient behind it.
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


def report_label_warnings(
    request: HttpRequest, barcode: str, warnings: list[LabelWarning]
) -> None:
    """
    Tell the user what looks wrong in the ingredient list OpenFoodFacts has.

    When the text looks badly read nothing was imported, and the one thing to
    do is correct it on OpenFoodFacts and load the product again.
    """
    stopping = [w for w in warnings if w.stops_reading]
    if stopping:
        messages.warning(
            request,
            _(
                "The ingredient list OpenFoodFacts has for barcode %(barcode)s "
                "looks badly read, so no ingredient was imported: %(problems)s "
                "Correct the text on OpenFoodFacts "
                "(https://world.openfoodfacts.org/product/%(barcode)s), "
                "then load the product again."
            )
            % {
                "barcode": barcode,
                "problems": " ".join(f"{w.message()}." for w in stopping),
            },
        )
    for warning in warnings:
        if not warning.stops_reading:
            messages.warning(request, warning.message())


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

    initial: dict[str, Any] = {
        "barcode": fetched.barcode,
        "name": fetched.name,
        "description": fetched.description or "",
        "group_level_1": fetched.group_level_1 or "",
        "group_level_2": fetched.group_level_2 or "",
    }
    # Values from the label, converted to each nutrient's unit.
    for code, amount in declared_nutrients_from_off(fetched.nutriments).items():
        initial[nutrient_field(code)] = plain_amount(amount)
    try:
        initial["off_image_url"] = validate_off_image_url(fetched.image_url)
    except ValueError:
        # A photo hosted somewhere the services refuse to download from.
        initial["off_image_url"] = None
    initial["off_barcode"] = fetched.barcode
    # The ingredients are read from the label's text, and nothing else.
    ingredients, warnings = ingredient_inputs_from_label(
        fetched.ingredients_text, fetched.ingredients_lc
    )
    report_label_warnings(request, fetched.barcode, warnings)
    initial["off_ingredients"] = INGREDIENTS_JSON.dump_json(ingredients).decode()
    initial["off_ingredients_text"] = fetched.ingredients_text or ""
    return initial


def ingredient_rows_for(form: ProductForm) -> list[dict[str, Any]]:
    """
    Rows for the ingredients tree (frontend/.../ingredients-table.js).

    The OpenFoodFacts tree this page would save if there is one, otherwise
    what is stored for the product.
    """
    from_off = form.off_ingredients_for_display()
    if from_off is not None:
        return ingredient_rows_from_inputs(from_off)
    if form.is_edit:
        return ingredient_rows_from_db(form.instance)
    return []


def _ciqual_label(food_code: str, proxy_food_code: str) -> str:
    """OpenFoodFacts' CIQUAL code for an ingredient, marking a proxy as such."""
    if food_code:
        return food_code
    return f"{proxy_food_code} (proxy)" if proxy_food_code else ""


def _ciqual_url(food_code: str, proxy_food_code: str) -> str | None:
    """The CIQUAL site's sheet for the code _ciqual_label shows, if there is one."""
    code = food_code or proxy_food_code
    return CIQUAL_FOOD_URL.format(code=quote(code, safe="")) if code else None


def _reference_ciqual(reference: ReferenceIngredient) -> tuple[str, str | None]:
    """
    The CIQUAL codes of the foods a reference draws on, and where to check them.

    The sheet is linked only when there is one code: with several, a single
    link would pass for the others. Needs source_foods__source prefetched.
    """
    codes = sorted(
        food.code
        for food in reference.source_foods.all()
        if food.source.code.startswith(CIQUAL_SOURCE_PREFIX)
    )
    url = _ciqual_url(codes[0], "") if len(codes) == 1 else None
    return ", ".join(codes), url


def _row(
    name: str,
    percentage: Decimal | None,
    ciqual: tuple[str, str | None],
    status: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "percentage": percentage,
        "ciqual": ciqual[0],
        "ciqual_url": ciqual[1],
        "reference": status,
        "ingredients": None,
    }


def _status_label(reference: ReferenceIngredient) -> str:
    return str(ReferenceIngredient.Status(reference.status).label)


def ingredient_rows_from_inputs(items: list[IngredientInput]) -> list[dict[str, Any]]:
    """
    Rows for an OpenFoodFacts tree that is not saved yet.

    An ingredient whose name a reference already has is shown as that
    reference. Any other will get a new one when the product is saved: it is
    shown by its name (in French when the taxonomy has one while French is
    served), with OpenFoodFacts' CIQUAL code, and marked new.
    """
    flat = list(walk_ingredients(items))
    references = existing_references(flat)
    prefetch_related_objects(list(references.values()), "source_foods__source")
    display_names = IngredientTaxon.display_names(item.off_id for item in flat)
    return _rows_from_inputs(items, references, display_names)


def _rows_from_inputs(
    items: list[IngredientInput],
    references: dict[str, ReferenceIngredient],
    display_names: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        reference = references.get(name_key(item.name))
        if reference is None:
            row = _row(
                display_names.get(item.off_id, item.name),
                item.percentage,
                (
                    _ciqual_label(
                        item.off_ciqual_food_code, item.off_ciqual_proxy_food_code
                    ),
                    _ciqual_url(
                        item.off_ciqual_food_code, item.off_ciqual_proxy_food_code
                    ),
                ),
                _("New"),
            )
        else:
            row = _row(
                reference.name,
                item.percentage,
                _reference_ciqual(reference),
                _status_label(reference),
            )
        row["ingredients"] = (
            _rows_from_inputs(item.sub_ingredients, references, display_names) or None
        )
        rows.append(row)
    return rows


def ingredient_rows_from_db(product: Product) -> list[dict[str, Any]]:
    """The stored ingredient tree, in a few queries however many there are."""
    ingredients = list(
        Ingredient.objects.filter(product=product)
        .select_related("reference")
        .prefetch_related("reference__source_foods__source")
        .order_by("id")
    )
    rows = {
        ingredient.id: _row(
            ingredient.reference.name,
            ingredient.percentage,
            _reference_ciqual(ingredient.reference),
            _status_label(ingredient.reference),
        )
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
