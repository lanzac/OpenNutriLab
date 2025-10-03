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


class FoodForm(forms.ModelForm):
    class Meta:
        model = Food
        # Fields from the Food model, extended with those from the Macronutrient model
        # Nutritional values defined in this form : energy + macronutrients
        fields: list[str] = ["barcode", "name", "image", "description", "energy"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType]
        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownArgumentType]

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
        barcode_field: FieldWithButtons | Field = self._build_barcode_field()
        nutritional_values_fields_layout: list[Field] = (
            self._get_nutritional_values_fields_layout()
        )
        self._configure_field_widgets_attrs()
        # --------------------------------------------------------------------

        # --------------------------------------------------------------------
        # FormHelper layout configuration
        # --------------------------------------------------------------------
        self.helper.layout = Layout(
            Row(
                Column(barcode_field, css_class="col-md-6"),
                Column(Field("name"), css_class="col-md-6"),
            ),
            FloatingField("description", style="height: 100px"),
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

    def _build_barcode_field(self) -> FieldWithButtons | Field:
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

    def _get_nutritional_values_fields_layout(self) -> list[Field]:
        """
        Build the crispy-forms layout for energy + all macronutrient fields.
        If editing, pre-fill fields with the values from FoodMacronutrient.
        """
        fields_layout: list[Field] = []

        # Energy field (MultiWidgetField)
        # Using PrependedText without text for MultiWidgetField to avoid layout issues
        energy_field = PrependedText(field="energy", text="")
        fields_layout.append(energy_field)

        # Macronutrient fields (one field per macronutrient)
        for macronutrient in Macronutrient.objects.all():
            # Becareful here with prefix "macronutrient_" which is used in the form
            # field names in order to match the naming convention defined in
            # ProductFormSchema
            # Field name convention: "macronutrients_<macronutrient.name>"
            field_name = f"macronutrients_{macronutrient.name.lower()}"

            # Clone form field from FoodMacronutrient.amount (QuantityFormField)
            # definition
            macronutrient_form_field = FoodMacronutrient._meta.get_field(  # noqa: SLF001
                field_name="amount",
            ).formfield(required=False)

            macronutrient_form_field.label = str(macronutrient)

            # If editing an existing Food, try to fetch stored amountc
            if self.instance and self.instance.pk:
                amount_value = (
                    FoodMacronutrient.objects.filter(
                        food=self.instance,
                        macronutrient=macronutrient,
                    )
                    .values_list("amount", flat=True)
                    .first()
                )

                if amount_value is not None:
                    macronutrient_form_field.initial = amount_value
                else:
                    macronutrient_form_field.widget.attrs.update(
                        {
                            "class": "form-control",
                            "placeholder": "!!! No data found for this field !!!",
                        },
                    )

            # Add field into the form
            self.fields[field_name] = macronutrient_form_field
            # Add to crispy layout
            fields_layout.append(
                PrependedText(field=field_name, text=""),
            )

        return fields_layout

    def _configure_field_widgets_attrs(self) -> None:
        for field in self.fields.values():
            if not isinstance(field, QuantityFormField):
                continue

            widget: type[Widget] | Widget = field.widget
            widget.attrs["step"] = "0.01"

            if not isinstance(widget, forms.MultiWidget):
                continue

            for subwidget in widget.widgets:
                if not isinstance(subwidget, forms.NumberInput):
                    continue

                subwidget.attrs.update(
                    {"class": "form-control", "type": "number", "min": "0.00"},
                )

    def save(self, commit: bool = True):  # noqa: FBT001, FBT002
        # Save the main Food object first
        food = super().save(commit=commit)

        # Iterate over all macronutrients to handle their dynamic form fields
        for macronutrient in Macronutrient.objects.all():
            field_name = f"macronutrients_{macronutrient.name.lower()}"
            value = self.cleaned_data.get(field_name)

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
