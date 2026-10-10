import logging
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any
from typing import cast
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import prefetch_related_objects
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.views import View
from pydantic import ValidationError
from vanilla import CreateView
from vanilla import DeleteView
from vanilla import ListView
from vanilla import UpdateView

from .api.openfoodfacts.services import OFFError
from .api.openfoodfacts.services import OFFProductNotFoundError
from .api.openfoodfacts.services import declared_nutrients_from_off
from .api.openfoodfacts.services import fetch_from_off
from .api.openfoodfacts.services import ingredient_inputs_from_label
from .api.openfoodfacts.services import nutrition_unit_from_off
from .api.openfoodfacts.services import read_inputs_from_label
from .api.schemas.inbound import IngredientInput
from .api.schemas.inbound import ReadLabelIn
from .api.schemas.inbound import validate_off_image_url
from .api.schemas.outbound import EstimateOut
from .forms import INGREDIENTS_JSON
from .forms import ProductForm
from .forms import label_wording
from .forms import nutrient_field
from .models import Additive
from .models import Ingredient
from .models import IngredientTaxon
from .models import Nutrient
from .models import Preparation
from .models import Product
from .models import ReferenceIngredient
from .pnns import pnns_group_names
from .services.estimate_panel import estimate_panel
from .services.estimate_report import build_estimate
from .services.inventory import add_to_inventory
from .services.label_parser import LabelWarning
from .services.packages import read_package
from .services.product_services import plain_amount
from .services.reference_services import CIQUAL_SOURCE_PREFIX
from .services.reference_services import Item
from .services.reference_services import existing_references
from .services.reference_services import name_key
from .services.reference_services import walk_ingredients
from .services.servings import read_serving

if TYPE_CHECKING:
    from opennutrilab.users.models import User

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
            # The picture of a product that has no photo, the one the product
            # page shows too (see products/components/image_preview.html).
            "placeholderImage": static("images/milk-carton-svgrepo-com.png"),
            # The words OpenFoodFacts files the products under, in this language.
            "groupNames": pnns_group_names(),
            "labels": {
                "image": _("Photo"),
                "barcode": _("Barcode"),
                "uncategorised": _("Uncategorised"),
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
                "totalQuantity": _("Total quantity"),
                "myInventory": _("My inventory"),
                "allProducts": _("All products"),
                "addToInventory": _("Add to my inventory"),
                "removeFromInventory": _("Take out of my inventory"),
                "inventoryEmpty": _(
                    "Your inventory is empty. Show all products to add some."
                ),
                "inventoryError": _("Your inventory could not be changed."),
                # Scanning a product with the camera. %(name)s and %(barcode)s
                # are interpolated client-side.
                "scanProduct": _("Scan a product"),
                "scanClose": _("Close the scanner"),
                "scanCamera": _("Camera"),
                "scanStarting": _("Starting the camera…"),
                "scanHint": _(
                    "Hold the barcode of the product in front of the camera."
                ),
                "scanTakePicture": _("Take a picture of the barcode"),
                "scanNeedsHttps": _(
                    "The camera can only be used live on a secure page (https). "
                    "Take a picture of the barcode instead."
                ),
                "scanCameraDenied": _(
                    "The camera is blocked. Allow it for this site in the "
                    "settings of the browser, or take a picture of the barcode."
                ),
                "scanCameraFailed": _(
                    "The camera could not be started. "
                    "Take a picture of the barcode instead."
                ),
                "scanReaderError": _("The barcode reader could not be loaded."),
                "scanPictureEmpty": _(
                    "No barcode was found in the picture. "
                    "Try again, closer, with the bars in focus."
                ),
                "scanAdded": _('"%(name)s" was added to your inventory.'),
                "scanAlready": _('"%(name)s" is already in your inventory.'),
                "scanUnknown": _("%(barcode)s is not in the catalogue yet."),
                "scanCreate": _("Create the product"),
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

    def form_valid(self, form: ProductForm) -> HttpResponseRedirect:
        response = super().form_valid(form)
        # Whoever adds a product has it at hand.
        add_to_inventory(cast("User", self.request.user), form.instance)
        return response

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
            if context["estimate"] is not None:
                context["estimate_panel"] = estimate_panel(context["estimate"])
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


class ReadLabelView(LoginRequiredMixin, View):
    """
    A label's text read again for the product page, without the places a person
    marked as no ingredients (see frontend/.../form/ingredients-text.js).

    Nothing is stored: the page keeps what this answers until the product is saved.
    The answer is what the page needs to show the reading: the ingredients as rows
    for its table and as the JSON its form posts, where in the text they were read
    from, and what looks wrong in the text.
    """

    raise_exception = True
    http_method_names = ["post"]

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            data = ReadLabelIn.model_validate_json(request.body)
        except ValidationError:
            return JsonResponse({"error": "invalid"}, status=400)
        inputs, warnings, used = read_inputs_from_label(
            data.text, data.language, data.ignored
        )
        return JsonResponse(
            {
                "rows": ingredient_rows_from_inputs(inputs),
                "ingredients": INGREDIENTS_JSON.dump_json(inputs).decode(),
                "used": used,
                "warnings": [
                    {"message": w.message(), "stops": w.stops_reading} for w in warnings
                ],
            }
        )


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
                    "label": label_wording(n),
                }
                for n in Nutrient.objects.filter(on_label=True, unit=Nutrient.Unit.GRAM)
            ],
            # The chart's own remainder slice, with no nutrient behind it.
            "others": _("Others"),
        },
        "barcodeActions": {
            "enterBarcode": _("Please enter a barcode."),
        },
        "estimatePanel": {
            # Intl formats the figures in the language served.
            "languageCode": get_language(),
            "labels": {
                "view": _("Display"),
                "viewGauges": _("Gauges"),
                "viewTable": _("Table"),
                "collapseAll": _("Fold all"),
                "expandAll": _("Unfold all"),
                "legendEstimate": _("Estimate and its range"),
                "legendLabel": _("Label (value and rounding)"),
                "legendTolerance": _("Tolerance of the label (European Commission)"),
                "legendOpen": _("Dashed: no upper end is known."),
                "ingredients": _("Ingredients"),
                "added": _("amount added"),
                "nutrients": _("Nutrients per 100 g"),
                "nutrientsMl": _("Nutrients per 100 ml"),
                "per": _("Amounts per"),
                "unitG": _("100 g"),
                "unitMl": _("100 ml"),
                # %(low)s and %(high)s are put in client-side.
                "density": _("Density used to convert: %(low)s to %(high)s g/ml"),
                "label": _("Label"),
                "estimate": _("Estimate"),
                "coverage": _("Coverage"),
                "coverageNote": _(
                    "The share of the product whose ingredients give a value."
                ),
                "confidence": _("Confidence"),
                "agrees": _("Agrees"),
                "declaredBelow": _("Label below"),
                "declaredAbove": _("Label above"),
                "constrained": _("Used for the estimate"),
                "tolerated": _("Within tolerance"),
                "toleratedNote": _(
                    "The label differs from the estimate by more than its rounding, "
                    "but within the tolerance the European Commission allows on a "
                    "label."
                ),
                "notEstimated": _("Not estimated"),
                "declaredBelowNote": _(
                    "The label declares less than the ingredients bring at the least."
                ),
                "declaredAboveNote": _(
                    "The label declares more than the ingredients can bring at "
                    "the most."
                ),
                "constrainedNote": _(
                    "The label's figure was one of the rules the percentages were "
                    "worked out with, so it agrees by construction and confirms "
                    "nothing."
                ),
                # %(agree)s and %(compared)s are put in client-side.
                "groupAgree": _("%(agree)s of %(compared)s agree with the label"),
                "notCompared": _("Not compared with the label"),
            },
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


def report_unread_package(request: HttpRequest, barcode: str, text: str) -> None:
    """Tell the user the quantity OpenFoodFacts gives could not be read."""
    messages.warning(
        request,
        _(
            'OpenFoodFacts gives the quantity of barcode %(barcode)s as "%(text)s", '
            "which could not be read. Enter what the package holds by hand."
        )
        % {"barcode": barcode, "text": text.strip()},
    )


def report_unread_serving(request: HttpRequest, barcode: str, text: str) -> None:
    """Tell the user the serving OpenFoodFacts gives could not be read."""
    messages.warning(
        request,
        _(
            'OpenFoodFacts gives the serving of barcode %(barcode)s as "%(text)s", '
            "which could not be read. Enter it by hand to count this product in "
            "servings."
        )
        % {"barcode": barcode, "text": text.strip()},
    )


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
    # Values from the label, converted to each nutrient's unit, and what the table
    # is given per: kept as it is printed, per 100 ml for a liquid that says so.
    for code, amount in declared_nutrients_from_off(fetched.nutriments).items():
        initial[nutrient_field(code)] = plain_amount(amount)
    initial["nutrition_unit"] = nutrition_unit_from_off(fetched.nutrition_data_per)
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
    # Nothing is ignored in a text that is new.
    initial["ingredients_ignored"] = "[]"
    initial["ingredients_lc"] = (fetched.ingredients_lc or "").strip().lower()[:10]
    # From its text too. With none, or one that is not read, the form keeps what
    # it had: nothing on a new product, the stored serving on a reset.
    serving = read_serving(fetched.serving_size)
    if serving is not None:
        initial["serving_quantity"] = plain_amount(serving.quantity)
        initial["serving_unit"] = serving.unit
        initial["serving_name"] = serving.name
    elif (fetched.serving_size or "").strip():
        report_unread_serving(request, fetched.barcode, fetched.serving_size or "")
    package = read_package(fetched.quantity)
    if package is not None:
        initial["package_quantity"] = plain_amount(package.quantity)
        initial["package_unit"] = package.unit
    elif (fetched.quantity or "").strip():
        report_unread_package(request, fetched.barcode, fetched.quantity or "")
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


def _reference_ciqual(
    reference: ReferenceIngredient | Preparation | Additive | Nutrient,
) -> tuple[str, str | None]:
    """
    The CIQUAL codes of the foods a reference draws on, and where to check them.

    The sheet is linked only when there is one code: with several, a single
    link would pass for the others. Needs source_foods__source prefetched. A
    nutrient draws on no food.
    """
    if isinstance(reference, Nutrient):
        return "", None
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


def _status_label(item: ReferenceIngredient | Preparation | Additive | Nutrient) -> str:
    """Whether it is curated, and what it is when it is not a reference."""
    if isinstance(item, Nutrient):
        return str(_("Nutrient"))
    label = str(ReferenceIngredient.Status(item.status).label)
    if isinstance(item, Preparation):
        return _("Preparation, %(status)s") % {"status": label.lower()}
    if isinstance(item, Additive):
        return _("Additive, %(status)s") % {"status": label.lower()}
    return label


def ingredient_rows_from_inputs(items: list[IngredientInput]) -> list[dict[str, Any]]:
    """
    Rows for an OpenFoodFacts tree that is not saved yet.

    An ingredient whose name a reference or a preparation already has is shown
    as that one. Any other will get a new reference when the product is saved:
    it is shown by its name (in French when the taxonomy has one while French is
    served), with OpenFoodFacts' CIQUAL code, and marked new.
    """
    flat = list(walk_ingredients(items))
    known = existing_references(flat)
    # One kind at a time: a reference and a preparation can share an id.
    found = list(known.values())
    for kind in (ReferenceIngredient, Preparation, Additive):
        prefetch_related_objects(
            [i for i in found if type(i) is kind], "source_foods__source"
        )
    display_names = IngredientTaxon.display_names(item.off_id for item in flat)
    return _rows_from_inputs(items, known, display_names)


def _rows_from_inputs(
    items: list[IngredientInput],
    known: dict[str, Item],
    display_names: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        found = known.get(name_key(item.name))
        if found is None:
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
                found.name,
                item.percentage,
                _reference_ciqual(found),
                _status_label(found),
            )
        row["ingredients"] = (
            _rows_from_inputs(item.sub_ingredients, known, display_names) or None
        )
        rows.append(row)
    return rows


def ingredient_rows_from_db(product: Product) -> list[dict[str, Any]]:
    """The stored ingredient tree, in a few queries however many there are."""
    ingredients = list(
        Ingredient.objects.filter(product=product)
        .select_related("reference", "preparation", "additive", "nutrient")
        .prefetch_related(
            "reference__source_foods__source",
            "preparation__source_foods__source",
            "additive__source_foods__source",
        )
        .order_by("id")
    )
    rows = {
        ingredient.id: _row(
            ingredient.item.name,
            ingredient.percentage,
            _reference_ciqual(ingredient.item),
            _status_label(ingredient.item),
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
