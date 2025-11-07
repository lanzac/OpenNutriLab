import io
from typing import TYPE_CHECKING

import requests
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
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from quantityfield.fields import QuantityFormField

from opennutrilab.crispy_bootstrap_extended.layouts import AccordionGroupExtended

from .models import Macronutrient
from .models import Product
from .models import ProductMacronutrient

if TYPE_CHECKING:
    from django.forms.widgets import Widget
    from django.utils.safestring import SafeText
    from pint import Quantity


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        # Fields from the Product model, extended with those from the Macronutrient
        # model. Nutritional values defined in this form : energy + macronutrients
        fields: list[str] = ["barcode", "name", "image", "description", "energy"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        labels: dict[str, str] = {
            "barcode": _("Barcode"),
            "name": _("Name"),
            "description": _("Description"),
            "energy": _("Energy"),
        }

    def __init__(
        self,
        *args,  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType]
        extra_data: dict[str, str | None] | None = None,
        **kwargs,  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType]
    ):
        # register extra_data variable before calling the super() method
        # https://djangoandy.com/2023/08/23/passing-custom-variables-into-django-forms/
        self.extra_data: dict[str, str | None] | None = extra_data or {}
        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownArgumentType]

        # TODO : TEST if image preview is correctly initialized when data is fetched
        # The next line is important for that !!
        self.fetched_image_url: str | None = (
            self.extra_data.get("fetched_image_url") if self.extra_data else None
        )

        # Configure Graph container template
        graph_container_template: SafeText = render_to_string(
            template_name="products/components/graph_container.html",
            context={
                "loader_id": "macronutrients_graph_loader",
                "graph_id": "macronutrients_graph",
                "loader_text": _("Loading macronutrients graph..."),
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
        barcode_field: FieldWithButtons | Field = self._get_barcode_field_layout()

        # 🔹 Nutritional values
        self._add_nutritional_value_fields()  # Add dynamic fields (macronutrients)

        # 🔹 Get the "nutritional values" layouts (that include fields) that will
        # be send to the form.
        nutritional_values_fields_layout: list[Field] = (
            self._get_nutritional_values_layout()
        )

        # 🔹 Configure widgets attrs for all QuantityFormField fields
        # It is important to call this method after having added the dynamic fields.
        self._configure_field_widgets_attrs()

        # --------------------------------------------------------------------

        # --------------------------------------------------------------------
        # FormHelper layout configuration
        # --------------------------------------------------------------------
        self.helper.layout = Layout(
            Row(
                Column(
                    Row(
                        Column(barcode_field, css_class="col-md-6"),
                        Column(Field("name"), css_class="col-md-6"),
                    ),
                    FloatingField(
                        "description",
                        style="height: 100px",
                        css_class="col-md-8",
                    ),
                    css_class="col-md-8",
                ),
                Column(
                    HTML("{% include 'products/components/image_preview.html' %}"),
                    css_class="col-md-4 d-flex align-items-center justify-content-center",  # noqa: E501
                ),
            ),
            BS5Accordion(
                AccordionGroupExtended(
                    _("Nutritional values (per 100g)"),
                    *nutritional_values_fields_layout,
                    extra_data=graph_container_template,
                ),
                always_open=True,
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

    def _get_barcode_field_layout(self) -> FieldWithButtons | Field:
        if not self.instance.pk:
            return FieldWithButtons(
                Field("barcode"),
                StrictButton(
                    content="🔍" + _("Fetch data"),
                    css_class="btn btn-outline-secondary",
                    type="button",
                    id="fetch-product-data",
                ),
            )
        self.fields["barcode"].widget.attrs.update(
            {
                "readonly": True,
                "class": "bg-body-secondary",
            },
        )
        return Field("barcode")

    def _add_nutritional_value_fields(self) -> None:
        """Add energy + macronutrient fields to self.fields."""
        # Energy field is already in the form, so no need to clone here

        _("Fat")
        _("of which Saturates")
        _("Carbohydrates")
        _("of which Sugars")
        _("Fiber")
        _("Proteins")

        for macronutrient in Macronutrient.objects.all():
            field_name = f"macronutrients_{macronutrient.name.lower()}"
            form_field: QuantityFormField = ProductMacronutrient._meta.get_field(  # noqa: SLF001
                field_name="amount",
            ).formfield(
                required=False,
            )
            form_field.label = _(str(macronutrient))

            if self.instance and self.instance.pk:
                amount_value: Quantity | None = (
                    ProductMacronutrient.objects.filter(
                        product=self.instance,
                        macronutrient=macronutrient,
                    )
                    .values_list("amount", flat=True)
                    .first()
                )
                if amount_value is not None:
                    form_field.initial = amount_value

            self.fields[field_name] = form_field

    def _get_nutritional_values_layout(self) -> list[Field]:
        """Return crispy-forms layout for energy + macronutrients."""
        layout_fields: list[Field] = [
            PrependedText(field="energy", text="", css_class="plot-input")
        ]
        layout_fields += [
            PrependedText(
                field=f"macronutrients_{m.name.lower()}",
                text="",
                css_class="plot-input",
            )
            for m in Macronutrient.objects.all()
        ]
        return layout_fields

    def _configure_field_widgets_attrs(self) -> None:
        for field in self.fields.values():
            if isinstance(field, QuantityFormField):
                widget: type[Widget] | Widget = field.widget
                # Important here to not assign class attribute to the widget attrs that
                # would not allow to set custom "css_class" in the layout.
                widget.attrs["step"] = "0.01"
                widget.attrs["placeholder"] = _("No data found")

                if isinstance(widget, forms.MultiWidget):
                    for subwidget in widget.widgets:
                        if isinstance(subwidget, forms.NumberInput):
                            subwidget.attrs.update(
                                {
                                    "type": "number",
                                    "min": "0.00",
                                },
                            )

    def save(self, commit: bool = True):  # noqa: FBT001, FBT002
        # 1️⃣ Save Product object without committing
        product = super().save(commit=False)

        # 2️⃣ Assign fetched image if needed
        fetched_image_url = getattr(self, "extra_data", {}).get("fetched_image_url")
        if fetched_image_url and not self.cleaned_data.get("image"):
            resp = requests.get(fetched_image_url, timeout=10)
            resp.raise_for_status()
            filename = f"{self.cleaned_data['barcode']}.jpg"
            path = f"images/products/{filename}"
            if default_storage.exists(path):
                default_storage.delete(path)

            product.image = InMemoryUploadedFile(
                io.BytesIO(resp.content),
                field_name="image",
                name=filename,
                content_type="image/jpeg",
                size=len(resp.content),
                charset=None,
            )

        # 3️⃣ Handle macronutrients
        for macronutrient in Macronutrient.objects.all():
            field_name = f"macronutrients_{macronutrient.name.lower()}"
            value: Quantity | None = self.cleaned_data.get(field_name)
            if value:
                ProductMacronutrient.objects.update_or_create(
                    product=product,
                    macronutrient=macronutrient,
                    defaults={"amount": value},
                )
            else:
                ProductMacronutrient.objects.filter(
                    product=product,
                    macronutrient=macronutrient,
                ).delete()

        # 4️⃣ Commit once
        if commit:
            product.save()

        return product
