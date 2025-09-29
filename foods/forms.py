from itertools import zip_longest
from typing import Any

from crispy_bootstrap5.bootstrap5 import BS5Accordion
from crispy_bootstrap5.bootstrap5 import FloatingField
from crispy_forms.bootstrap import AccordionGroup
from crispy_forms.bootstrap import AppendedText

# https://django-crispy-forms.readthedocs.io/en/latest/layouts.html
from crispy_forms.bootstrap import FieldWithButtons
from crispy_forms.bootstrap import StrictButton
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML
from crispy_forms.layout import Column
from crispy_forms.layout import Div
from crispy_forms.layout import Field
from crispy_forms.layout import Layout
from crispy_forms.layout import Row
from crispy_forms.layout import Submit
from django import forms
from django.urls import reverse
from quantityfield.fields import QuantityFormField

from .models import Food
from .schema import AnnotatedSchema
from .schema import MacronutrientsSchema


class FoodForm(forms.ModelForm):
    class Meta:
        model = Food
        fields: list[str] = ["barcode", "name", "image", "description", "energy"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType]
        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownArgumentType]

        # Champs de base
        self.fields_categories = {
            "description": self._meta.fields,
            "macronutrients": [],
        }
        self.dynamic_fields_info: dict[Any, Any] = {}  # field_name -> info dict
        # Ajout des champs dynamiques
        self.add_schema_fields(MacronutrientsSchema)
        # self.configure_field_widgets()  # noqa: ERA001

        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.form_enctype = "multipart/form-data"  # pyright: ignore[reportAttributeAccessIssue]

        layout_fields: list[Any] = []

        # Barcode + bouton Fetch uniquement si création
        barcode_field = None
        if not self.instance.pk:
            barcode_field = FieldWithButtons(
                Field("barcode"),
                StrictButton(
                    "🔍 Fetch",
                    css_class="btn btn-outline-secondary",
                    type="button",
                    id="fetch-food-data",
                ),
            )
        else:
            barcode_field = Field("barcode")
            self.fields["barcode"].widget.attrs.update(
                {
                    "readonly": True,
                    "class": "form-control bg-light",
                },
            )

        # Autres champs de base
        layout_fields += [
            Row(
                Column(barcode_field, css_class="col-md-6"),
                Column(Field("name"), css_class="col-md-6"),
            ),
            FloatingField("description", style="height: 100px"),
            Row(
                Column(Field("image"), css_class="col-md-7"),
                Column(
                    HTML(
                        """
    {% load form_tags static %}
    {% if form.instance.image %}
      <img src="{{ form.instance.image.url }}" style="max-width: 200px;" />
    {% else %}
      <img src="{% static 'images/default.jpg' %}" style="max-width: 200px;" />
    {% endif %}
    """,
                    ),
                    css_class="col-md-5",
                ),
                css_class="gx-5 justify-content-center",
            ),
            Field(AppendedText("energy", "per 100g")),
        ]

        # Champs dynamiques avec "per 100g" quand il faut

        accordion_groups: list[Any] = []
        for category_name, field_names in self.fields_categories.items():
            if category_name == "description":
                continue

            columns: list[Any] = []
            # Regrouper les champs deux par deux
            field_pairs: zip_longest[tuple[Any, ...]] = zip_longest(
                *[iter(field_names)] * 2,  # pyright: ignore[reportUnknownArgumentType, reportCallIssue, reportArgumentType]
            )

            for left, right in field_pairs:
                row_columns: list[Any] = []
                if left:
                    row_columns.append(
                        Column(AppendedText(left, "per 100g"), css_class="col-md-5"),
                    )
                if right:
                    row_columns.append(
                        Column(AppendedText(right, "per 100g"), css_class="col-md-5"),
                    )
                columns.append(
                    Row(*row_columns, css_class="gx-5 justify-content-center"),
                )

            accordion_groups.append(
                AccordionGroup(
                    category_name.capitalize(),
                    *columns,
                ),
            )

        layout_fields.append(BS5Accordion(*accordion_groups, always_open=True))

        layout_fields.append(
            Div(
                Submit("save", "Save", css_class="btn btn-primary"),
                HTML(
                    f'<a class="btn btn-secondary ms-2" href="{reverse("list_foods")}"'
                    f">Cancel</a>",
                ),
                css_class="mt-3",
            ),
        )

        self.helper.layout = Layout(*layout_fields)

    # Deprecated soon
    def configure_field_widgets(self) -> None:
        for field in self.fields.values():
            if isinstance(field, QuantityFormField):
                field.widget.attrs["step"] = "0.01"
            widget = field.widget
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", "form-control")
            elif isinstance(widget, forms.MultiWidget):
                for subwidget in widget.widgets:
                    if isinstance(subwidget, forms.TextInput):
                        subwidget.attrs.setdefault("class", "form-control")
                    elif isinstance(subwidget, forms.NumberInput):
                        subwidget.attrs.update(
                            {"class": "form-control", "type": "number", "min": "0.00"},
                        )
                    elif isinstance(subwidget, forms.Select):
                        subwidget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")

    def add_schema_fields(self, schema: AnnotatedSchema):
        """
        Ajoute dynamiquement les champs du schéma et stocke leurs
        métadonnées dans self.dynamic_fields_info.
        """
        through_model_class = getattr(schema, "through_model_class", None)
        if not through_model_class:
            msg = f"Le schéma {schema.__name__} doit définir through_model_class."
            raise ValueError(
                msg,
            )
        for field_name_in_schema in schema.model_fields:  # pyright: ignore[reportDeprecated]
            field_name = schema.get_form_field_name(field_name_in_schema)
            related_model_class = schema.related_model_class
            related_instance = related_model_class.objects.filter(
                name=field_name_in_schema,
            ).first()
            if not related_instance:
                import logging  # noqa: PLC0415

                logging.warning(
                    "Warning: %s not found in %s. Skipping field %s.",
                    field_name_in_schema,
                    related_model_class.__name__,
                    field_name,
                )
                continue
            form_field = schema.get_formfield()
            form_field.label = f"{related_instance}"
            self.fields[field_name] = form_field
            self.fields_categories[schema.field_category].append(field_name)  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue, reportOptionalMemberAccess]
            self.dynamic_fields_info[field_name] = {
                "category": schema.field_category,
                "related_model": related_model_class,
                "through_model": through_model_class,
                "name_in_schema": field_name_in_schema,
            }
            # Initial value if editing
            if self.instance.pk:
                through_entry = (
                    through_model_class.objects.filter(
                        food=self.instance,
                        **{f"{related_model_class._meta.model_name}": related_instance},  # noqa: SLF001
                    )
                    .only("amount")
                    .first()
                )

                if through_entry:
                    form_field.initial = getattr(through_entry, "amount", None)
                else:
                    form_field.widget.attrs.update(
                        {
                            "class": "form-control",
                            "placeholder": "!!! No data found for this field !!!",
                        },
                    )

    def save(self, commit: bool = True):  # noqa: FBT001, FBT002
        food = super().save(commit=commit)
        for field_name, info in self.dynamic_fields_info.items():
            if info["category"] == "description":
                continue
            related_instance = (
                info["related_model"]
                .objects.filter(name=info["name_in_schema"])
                .first()
            )
            if not related_instance:
                continue
            amount = self.cleaned_data.get(field_name)
            filter_kwargs = {
                "food": food,
                info["related_model"]._meta.model_name: related_instance,  # noqa: SLF001
            }
            if amount:
                info["through_model"].objects.update_or_create(
                    defaults={"amount": amount},
                    **filter_kwargs,
                )
            else:
                info["through_model"].objects.filter(**filter_kwargs).delete()
        return food
