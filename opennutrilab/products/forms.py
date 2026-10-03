from typing import TYPE_CHECKING
from typing import Any

from crispy_bootstrap5.bootstrap5 import BS5Accordion
from crispy_bootstrap5.bootstrap5 import FloatingField
from crispy_forms.bootstrap import AppendedText

# https://django-crispy-forms.readthedocs.io/en/latest/layouts.html
from crispy_forms.bootstrap import FieldWithButtons
from crispy_forms.bootstrap import FormActions
from crispy_forms.bootstrap import StrictButton
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML
from crispy_forms.layout import Column
from crispy_forms.layout import Field
from crispy_forms.layout import Layout
from crispy_forms.layout import Row
from crispy_forms.layout import Submit
from django import forms
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from pydantic import TypeAdapter
from pydantic import ValidationError

from opennutrilab.crispy_bootstrap_extended.layouts import AccordionGroupExtended
from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.api.schemas.inbound import ProductUpdate
from opennutrilab.products.services import product_services
from opennutrilab.products.services.product_services import plain_amount

from .models import Nutrient
from .models import Product
from .models import ProductNutrient

if TYPE_CHECKING:
    from decimal import Decimal

    from django.utils.safestring import SafeText

# How the ingredient tree travels in the off_ingredients hidden field.
INGREDIENTS_JSON = TypeAdapter(list[IngredientInput])


def nutrient_field(code: str) -> str:
    """The form field holding the declared amount of nutrient `code`."""
    return f"nutrient_{code}"


class ProductForm(forms.ModelForm):
    """
    The product create/edit page. It only validates and describes the change:
    products.services.product_services writes it, as it does for the API.
    """

    # What a lookup on OpenFoodFacts returned when the page was loaded, carried
    # to the POST that saves it, so the save stores what the user was shown
    # rather than asking OpenFoodFacts again. Applied only while off_barcode
    # still matches the barcode being saved.
    off_barcode = forms.CharField(required=False, widget=forms.HiddenInput)
    off_image_url = forms.CharField(required=False, widget=forms.HiddenInput)
    off_ingredients = forms.CharField(required=False, widget=forms.HiddenInput)
    # A photo chosen by hand; it wins over the OpenFoodFacts one. Deliberately
    # not the model's image field, so ModelForm never assigns product.image
    # itself: the services store the file.
    photo = forms.ImageField(
        required=False,
        label=_("Photo"),
        widget=forms.FileInput(attrs={"accept": "image/*"}),
    )

    class Meta:
        model = Product
        # Plus one field per nutrient of the label declaration, from the
        # catalogue (see _add_nutrient_fields).
        fields: list[str] = [
            "barcode",
            "name",
            "description",
            "group_level_1",
            "group_level_2",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "group_level_1": forms.HiddenInput(),
            "group_level_2": forms.HiddenInput(),
        }
        labels: dict[str, str] = {
            "barcode": _("Barcode"),
            "name": _("Name"),
            "description": _("Description"),
        }

    def __init__(
        self,
        *args,  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType]
        **kwargs,  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType]
    ):
        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownArgumentType]

        # Not `instance.pk is not None`: the primary key is a CharField, so a
        # new Product's pk is "" rather than None, and ModelForm fills it in
        # while cleaning anyway.
        self.is_edit: bool = not self.instance._state.adding  # noqa: SLF001
        self.image_fetch_failed = False
        self.declared_value_warnings: list[str] = []
        self.label_nutrients = list(Nutrient.objects.filter(on_label=True))

        # Configure Graph container template
        macronutrients_graph_container_template: SafeText = render_to_string(
            template_name="products/components/graph_container.html",
            context={
                "loader_id": "macronutrients_graph_loader",
                "graph_id": "macronutrients_graph",
                "loader_text": _("Loading macronutrients graph..."),
            },
        )

        ingredients_table_container_template: SafeText = render_to_string(
            template_name="products/components/graph_container.html",
            context={
                "loader_id": "ingredients_graph_loader",
                "graph_id": "ingredients_table",
                "loader_text": _("Loading ingredients table..."),
            },
        )

        # --------------------------------------------------------------------
        # FormHelper configuration
        # --------------------------------------------------------------------
        # django-crispy-forms implements a class called FormHelper that defines the form
        # rendering behavior.
        # https://django-crispy-forms.readthedocs.io/en/latest/crispy_tag_forms.html#crispy-tag-forms
        self.helper = FormHelper()
        self.helper.form_id = "product-form"
        # --------------------------------------------------------------------

        # --------------------------------------------------------------------
        # Fields configuration
        # --------------------------------------------------------------------
        # 🔹Barcode
        self.fields["barcode"].help_text = _(
            "Enter the 13-digit EAN code from the packaging."
        )
        barcode_field: FieldWithButtons = self._get_barcode_field_layout()

        # 🔹 Nutritional values
        self._add_nutrient_fields()

        # 🔹 Get the "nutritional values" layouts (that include fields) that will
        # be send to the form.
        nutritional_values_fields_layout: list[Field] = (
            self._get_nutritional_values_layout()
        )

        # --------------------------------------------------------------------

        # --------------------------------------------------------------------
        # FormHelper layout configuration
        # --------------------------------------------------------------------
        self.helper.layout = Layout(
            Row(barcode_field),
            Row(
                Column(
                    Field("name", css_class="col-md-8"),
                    FloatingField(
                        "description",
                        style="height: 100px",
                        css_class="col-md-8",
                    ),
                    css_class="col-md-8",
                ),
                Column(
                    HTML("{% include 'products/components/image_preview.html' %}"),
                    Field("photo"),
                    css_class="col-md-4 d-flex flex-column align-items-center justify-content-center",  # noqa: E501
                ),
                Field("group_level_1", value="Unknown"),
                Field("group_level_2", value="Unknown"),
                Field("off_barcode"),
                Field("off_image_url"),
                Field("off_ingredients"),
            ),
            BS5Accordion(
                AccordionGroupExtended(
                    _("Nutritional values (per 100g)"),
                    *nutritional_values_fields_layout,
                    extra_data=macronutrients_graph_container_template,
                ),
                always_open=True,
                css_class="mt-3",  # Add margin top
            ),
            BS5Accordion(
                AccordionGroupExtended(
                    _("Ingredients"),
                    Layout(),
                    template="crispy_bootstrap_extend/accordion-group-extended-vertical.html",
                    extra_data=ingredients_table_container_template,
                ),
                always_open=True,
                css_class="mt-3",  # Add margin top
            ),
            FormActions(
                Submit(name=_("save"), value=_("Save"), css_class="btn-primary"),
                HTML(
                    f'<a class="btn btn-secondary ms-2" '
                    f'href="{reverse("list_products")}">' + _("Cancel") + "</a>",
                ),
                css_class="mt-3",  # Add margin top
            ),
        )
        # --------------------------------------------------------------------

    def _get_barcode_field_layout(self) -> FieldWithButtons:
        if not self.is_edit:
            return FieldWithButtons(
                Field("barcode"),
                StrictButton(
                    content="🔍" + _("Fetch data"),
                    css_class="btn btn-outline-secondary",
                    type="button",
                    id="fetch-product-data",
                ),
            )
        # The barcode is the primary key. Disabled rather than readonly:
        # Django then ignores whatever a tampered POST sends for it and keeps
        # the stored value.
        self.fields["barcode"].disabled = True
        return FieldWithButtons(
            Field("barcode"),
            StrictButton(
                content="🔴 " + _("Reset data"),
                css_class="btn btn-outline-secondary",
                type="button",
                id="reset-product-data",
            ),
        )

    def _add_nutrient_fields(self) -> None:
        """One field per nutrient of the label declaration, from the catalogue."""
        stored: dict[str, Decimal] = {}
        if self.is_edit:
            stored = dict(
                ProductNutrient.objects.filter(product=self.instance).values_list(
                    "nutrient_id", "amount"
                )
            )
        for nutrient in self.label_nutrients:
            amount = stored.get(nutrient.code)
            self.fields[nutrient_field(nutrient.code)] = forms.DecimalField(
                label=nutrient.name,
                required=False,
                min_value=0,
                max_digits=12,
                decimal_places=4,
                initial=None if amount is None else plain_amount(amount),
            )

    def _get_nutritional_values_layout(self) -> list[Field]:
        """Return crispy-forms layout for the declared nutrients, with units."""
        return [
            AppendedText(nutrient_field(n.code), n.unit, css_class="plot-input")
            for n in self.label_nutrients
        ]

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean()
        if self.errors:
            return cleaned
        try:
            self.write_data: ProductCreate | ProductUpdate = self._write_data(cleaned)
        except ValidationError as e:
            # Only reachable through the hidden fields, i.e. a tampered POST
            # or a lookup result the schemas reject.
            raise forms.ValidationError(
                _(
                    "The data fetched from OpenFoodFacts could not be used. "
                    "Please fetch it again."
                )
            ) from e
        return cleaned

    def _write_data(self, cleaned: dict[str, Any]) -> ProductCreate | ProductUpdate:
        barcode = self.instance.barcode if self.is_edit else cleaned["barcode"]
        off_barcode = cleaned.get("off_barcode")
        from_off = bool(off_barcode) and off_barcode == barcode
        raw_ingredients = cleaned.get("off_ingredients") if from_off else None
        ingredients = (
            INGREDIENTS_JSON.validate_json(raw_ingredients) if raw_ingredients else None
        )

        payload: dict[str, Any] = {
            "name": cleaned["name"],
            "description": cleaned.get("description") or "",
            "group_level_1": cleaned.get("group_level_1") or "",
            "group_level_2": cleaned.get("group_level_2") or "",
            "image_url": (cleaned.get("off_image_url") or None) if from_off else None,
        }
        # An empty field means "unknown" and clears the value; 0 is stored as a
        # measurement.
        nutrients = {
            n.code: cleaned.get(nutrient_field(n.code)) for n in self.label_nutrients
        }
        if self.is_edit:
            payload["nutrients"] = nutrients
            # None leaves the stored ingredients alone: they are replaced only
            # when this page was loaded from OpenFoodFacts ("Reset data").
            payload["ingredients"] = ingredients
            return ProductUpdate.model_validate(payload)
        payload["barcode"] = barcode
        payload["nutrients"] = {c: v for c, v in nutrients.items() if v is not None}
        payload["ingredients"] = ingredients or []
        return ProductCreate.model_validate(payload)

    def save(self, commit: bool = True) -> Product:  # noqa: FBT001, FBT002
        if not commit:
            msg = "ProductForm writes through the product services; it cannot defer."
            raise ValueError(msg)
        photo = self.cleaned_data.get("photo")
        if isinstance(self.write_data, ProductUpdate):
            result = product_services.update_product(
                self.instance, self.write_data, image=photo
            )
        else:
            result = product_services.create_product(self.write_data, image=photo)
        self.instance = result.product
        self.image_fetch_failed = result.image_fetch_failed
        self.declared_value_warnings = product_services.declared_value_warnings(
            {
                n.code: value
                for n in self.label_nutrients
                if (value := self.cleaned_data.get(nutrient_field(n.code))) is not None
            }
        )
        return result.product

    # ------------------------------------------------------------------------
    # What the page shows besides the fields
    # ------------------------------------------------------------------------
    @property
    def preview_image_url(self) -> str | None:
        """The OpenFoodFacts photo this page will save, if any."""
        return self["off_image_url"].value() or None

    def off_ingredients_for_display(self) -> list[IngredientInput] | None:
        """The OpenFoodFacts ingredient tree this page will save, if any."""
        raw = self["off_ingredients"].value()
        if not raw:
            return None
        try:
            return INGREDIENTS_JSON.validate_json(raw)
        except ValidationError:
            return None
