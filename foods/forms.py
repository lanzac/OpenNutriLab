from typing import TYPE_CHECKING

from crispy_bootstrap5.bootstrap5 import BS5Accordion
from crispy_bootstrap5.bootstrap5 import FloatingField
from crispy_forms.bootstrap import AccordionGroup

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
from django.urls import reverse
from quantityfield.fields import QuantityFormField

from .models import Food
from .models import FoodMacronutrient
from .models import Macronutrient

if TYPE_CHECKING:
    from django.forms.widgets import Widget
    from pint import Quantity


class FoodForm(forms.ModelForm):
    class Meta:
        model = Food
        # Fields from the Food model, extended with those from the Macronutrient model
        # Nutritional values defined in this form : energy + macronutrients
        fields: list[str] = ["barcode", "name", "image", "description", "energy"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, extra_data: dict[str, str] | None = None, **kwargs):  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType]
        # register extra_data variable before calling the super() method
        # https://djangoandy.com/2023/08/23/passing-custom-variables-into-django-forms/
        self.extra_data: dict[str, str] | None = extra_data
        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownArgumentType]

        self.fetched_image_url: str | None = (
            self.extra_data.get("fetched_image_url") if self.extra_data else None
        )

        # --------------------------------------------------------------------
        # FormHelper configuration
        # --------------------------------------------------------------------
        # django-crispy-forms implements a class called FormHelper that defines the form
        # rendering behavior.
        # https://django-crispy-forms.readthedocs.io/en/latest/crispy_tag_forms.html#crispy-tag-forms
        self.helper = FormHelper()
        # --------------------------------------------------------------------

        # --------------------------------------------------------------------
        # Fields configuration
        # --------------------------------------------------------------------
        # 🔹Barcode
        self.fields[
            "barcode"
        ].help_text = "Enter the 13-digit EAN code from the packaging."
        barcode_field: FieldWithButtons | Field = self._get_barcode_field_layout()

        # 🔹 Nutritional values
        self._add_nutritional_value_fields()  # Add dynamic fields (macronutrients)
        nutritional_values_fields_layout: list[Field] = (
            self._get_nutritional_values_layout()
        )

        # 🔹 Configure widgets attrs for all QuantityFormField fields
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
                    HTML("{% include 'foods/components/image_preview.html' %}"),
                    css_class="col-md-4 d-flex align-items-center justify-content-center",  # noqa: E501
                ),
            ),
            BS5Accordion(
                AccordionGroup(
                    "Nutritional values (per 100g)",
                    *nutritional_values_fields_layout,
                ),
                always_open=True,
            ),
            FormActions(
                Submit("save", "Save", css_class="btn-primary"),
                HTML(
                    f'<a class="btn btn-secondary ms-2" href="{reverse("list_foods")}"'
                    f">Cancel</a>",
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
                    "🔍 Fetch",
                    css_class="btn btn-outline-secondary",
                    type="button",
                    id="fetch-food-data",
                ),
            )
        self.fields["barcode"].widget.attrs.update(
            {
                "readonly": True,
                "class": "form-control bg-light",
            },
        )
        return Field("barcode")

    def _add_nutritional_value_fields(self) -> None:
        """Add energy + macronutrient fields to self.fields."""
        # Energy field is already in the form, so no need to clone here

        for macronutrient in Macronutrient.objects.all():
            field_name = f"macronutrients_{macronutrient.name.lower()}"
            form_field: QuantityFormField = FoodMacronutrient._meta.get_field(  # noqa: SLF001
                field_name="amount",
            ).formfield(
                required=False,
            )
            form_field.label = str(macronutrient)

            if self.instance and self.instance.pk:
                amount_value: Quantity | None = (
                    FoodMacronutrient.objects.filter(
                        food=self.instance,
                        macronutrient=macronutrient,
                    )
                    .values_list("amount", flat=True)
                    .first()
                )
                if amount_value is not None:
                    form_field.initial = amount_value
                else:
                    form_field.widget.attrs.update(
                        {
                            "class": "form-control",
                            "placeholder": "!!! No data found for this field !!!",
                        },
                    )

            self.fields[field_name] = form_field

    def _get_nutritional_values_layout(self) -> list[Field]:
        """Return crispy-forms layout for energy + macronutrients."""
        layout_fields: list[Field] = [PrependedText(field="energy", text="")]
        layout_fields += [
            PrependedText(field=f"macronutrients_{m.name.lower()}", text="")
            for m in Macronutrient.objects.all()
        ]
        return layout_fields

    def _configure_field_widgets_attrs(self) -> None:
        for field in self.fields.values():
            if isinstance(field, QuantityFormField):
                widget: type[Widget] | Widget = field.widget
                widget.attrs["step"] = "0.01"

                if isinstance(widget, forms.MultiWidget):
                    for subwidget in widget.widgets:
                        if isinstance(subwidget, forms.NumberInput):
                            subwidget.attrs.update(
                                {
                                    "class": "form-control",
                                    "type": "number",
                                    "min": "0.00",
                                },
                            )

    def save(self, commit: bool = True):  # noqa: FBT001, FBT002
        # Save the main Food object first
        food = super().save(commit=commit)

        # Iterate over all macronutrients to handle their dynamic form fields
        for macronutrient in Macronutrient.objects.all():
            field_name = f"macronutrients_{macronutrient.name.lower()}"
            value: Quantity | None = self.cleaned_data.get(field_name)

            if value:
                # Create or update the FoodMacronutrient entry for this macronutrient
                FoodMacronutrient.objects.update_or_create(
                    food=food,
                    macronutrient=macronutrient,
                    defaults={"amount": value},
                )
            else:
                # If no value was provided, remove the association to keep the DB clean
                FoodMacronutrient.objects.filter(
                    food=food,
                    macronutrient=macronutrient,
                ).delete()

        return food
