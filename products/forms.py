from typing import TYPE_CHECKING
from typing import Any

from crispy_bootstrap5.bootstrap5 import BS5Accordion
from crispy_bootstrap5.bootstrap5 import FloatingField

# https://django-crispy-forms.readthedocs.io/en/latest/layouts.html
from crispy_forms.bootstrap import FieldWithButtons
from crispy_forms.bootstrap import FormActions
from crispy_forms.bootstrap import PrependedText
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
from products.api.schemas.inbound import IngredientInput
from products.api.schemas.inbound import ProductCreate
from products.api.schemas.inbound import ProductUpdate
from products.services import product_services

from .models import Macronutrient
from .models import Product
from .models import ProductMacronutrient

if TYPE_CHECKING:
    from decimal import Decimal

    from django.utils.safestring import SafeText

# How the ingredient tree travels in the off_ingredients hidden field.
INGREDIENTS_JSON = TypeAdapter(list[IngredientInput])


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
        # Nutritional values defined in this form: energy_kj here, plus one
        # field per Macronutrient row, added in __init__.
        fields: list[str] = [
            "barcode",
            "name",
            "description",
            "energy_kj",
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
            "energy_kj": _("Energy"),
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
        self._macronutrients = list(Macronutrient.objects.all())

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
        self._add_nutritional_value_fields()  # Add dynamic fields (macronutrients)

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

    def _add_nutritional_value_fields(self) -> None:
        """Add energy_kj + macronutrient fields to self.fields."""
        # Energy field is already in the form, so no need to clone here

        _("Fat")
        _("of which Saturates")
        _("Carbohydrates")
        _("of which Sugars")
        _("Fiber")
        _("Proteins")

        stored: dict[str, Decimal] = {}
        if self.is_edit:
            stored = dict(
                ProductMacronutrient.objects.filter(product=self.instance).values_list(
                    "macronutrient_id", "amount_g"
                )
            )

        for macronutrient in self._macronutrients:
            form_field: forms.Field = ProductMacronutrient._meta.get_field(  # noqa: SLF001
                field_name="amount_g",
            ).formfield(
                required=False,
            )
            form_field.label = _(str(macronutrient))
            form_field.initial = stored.get(macronutrient.name)
            self.fields[macronutrient.name_in_form] = form_field

    def _get_nutritional_values_layout(self) -> list[Field]:
        """Return crispy-forms layout for energy_kj + macronutrients."""
        layout_fields: list[Field] = [
            PrependedText(field="energy_kj", text="", css_class="plot-input")
        ]
        layout_fields += [
            PrependedText(field=m.name_in_form, text="", css_class="plot-input")
            for m in self._macronutrients
        ]
        return layout_fields

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
            "nutritional_values": {
                "energy_kj": cleaned["energy_kj"],
                # The complete set: an empty field drops that macronutrient,
                # and 0 is stored as a measurement.
                "macronutrients": [
                    {"name": m.name, "amount_g": cleaned[m.name_in_form]}
                    for m in self._macronutrients
                    if cleaned.get(m.name_in_form) is not None
                ],
            },
        }
        if self.is_edit:
            # None leaves the stored ingredients alone: they are replaced only
            # when this page was loaded from OpenFoodFacts ("Reset data").
            payload["ingredients"] = ingredients
            return ProductUpdate.model_validate(payload)
        payload["barcode"] = barcode
        payload["ingredients"] = ingredients or []
        return ProductCreate.model_validate(payload)

    def save(self, commit: bool = True) -> Product:  # noqa: FBT001, FBT002
        if not commit:
            msg = "ProductForm writes through the product services; it cannot defer."
            raise ValueError(msg)
        photo = self.cleaned_data.get("photo")
        if self.is_edit:
            result = product_services.update_product(
                self.instance, self.write_data, image=photo
            )
        else:
            result = product_services.create_product(self.write_data, image=photo)
        self.instance = result.product
        self.image_fetch_failed = result.image_fetch_failed
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
