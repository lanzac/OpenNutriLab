from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import (
    Layout, Field, Div, Submit, HTML, Row, Column
)
# https://django-crispy-forms.readthedocs.io/en/latest/layouts.html
from crispy_forms.bootstrap import (
    FieldWithButtons, StrictButton, AppendedText, AccordionGroup
)
from crispy_bootstrap5.bootstrap5 import BS5Accordion, FloatingField

from django.urls import reverse
from quantityfield.fields import QuantityFormField
from .schema import AnnotatedSchema, MacronutrientsSchema
from itertools import zip_longest


def prioritize_unit_choice(default_unit_in_form, unit_choices):
    """
    Place l'unité par défaut en tête de liste dans unit_choices.

    :param default_unit_in_form: str – unité à prioriser (ex: "µg")
    :param unit_choices: list of (str, str) – ex: [("mg", "mg"), ("µg", "µg")]
    :return: list of (str, str) – même structure, avec l'unité priorisée en premier
    """
    mylist = unit_choices.copy()
    mylist.insert(0, mylist.pop(mylist.index(default_unit_in_form)))
    return mylist

class FoodForm(forms.ModelForm):

    class Meta:
        model = Food
        fields = ['barcode', 'name', 'image', 'description', 'energy']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Champs de base
        self.fields_categories = {'description': list(self._meta.fields), 'macronutrients': [], 'vitamins': []}
        self.dynamic_fields_info = {}  # field_name -> info dict
        # Ajout des champs dynamiques
        self.add_schema_fields(MacronutrientsSchema)
        # self.configure_field_widgets()
        
        
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_enctype = 'multipart/form-data'

        layout_fields = []

        # Barcode + bouton Fetch uniquement si création
        barcode_field = None
        if not self.instance.pk:
            barcode_field = FieldWithButtons(
                Field('barcode'),
                StrictButton(
                    '🔍 Fetch',
                    css_class='btn btn-outline-secondary',
                    type='button',
                    id='fetch-food-data'
                )
            )
        else:
            barcode_field = Field('barcode')
            self.fields['barcode'].widget.attrs.update({
                'readonly': True,
                'class': 'form-control bg-light',
            })
            

        # Autres champs de base
        layout_fields += [
            Row(
                Column(barcode_field, css_class="col-md-6"),
                Column(Field('name'), css_class="col-md-6"),
            ),
            FloatingField('description', style="height: 100px"),
            Row(
                Column(Field('image'), css_class="col-md-7"),
                Column(
                    HTML(
                        '{% load form_tags static %}'
                        '{% if form.instance.image %}'
                        '<img src="{{ form.instance.image.url }}" style="max-width: 200px;" />'
                        '{% else %}'
                        '<img src="{% static "images/default.jpg" %}" style="max-width: 200px;" />'
                        '{% endif %}'
                    ), css_class="col-md-5"
                )
            , css_class="gx-5 justify-content-center"),
            Field(AppendedText('energy', 'per 100g')),
        ]

        # Champs dynamiques avec "per 100g" quand il faut

        accordion_groups = []
        for category_name, field_names in self.fields_categories.items():
            if category_name == 'description':
                continue

            columns = []
            # Regrouper les champs deux par deux
            field_pairs = zip_longest(*[iter(field_names)] * 2)

            for left, right in field_pairs:
                row_columns = []
                if left:
                    row_columns.append(Column(AppendedText(left, 'per 100g'), css_class="col-md-5"))
                if right:
                    row_columns.append(Column(AppendedText(right, 'per 100g'), css_class="col-md-5"))
                columns.append(Row(*row_columns, css_class="gx-5 justify-content-center"))

            accordion_groups.append(
                AccordionGroup(
                    category_name.capitalize(),
                    *columns,
                )
            )
            
        
        layout_fields.append(BS5Accordion(*accordion_groups, always_open=True))
        
        layout_fields.append(
            Div(
                Submit('save', 'Save', css_class='btn btn-primary'),
                HTML(f'<a class="btn btn-secondary ms-2" href="{reverse("list_foods")}">Cancel</a>'),
                css_class="mt-3"
            )
        )

        self.helper.layout = Layout(*layout_fields)
        
    # Deprecated soon
    def configure_field_widgets(self):
        for name, field in self.fields.items():
            if isinstance(field, QuantityFormField):
                field.widget.attrs['step'] = '0.01'
            widget = field.widget
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('class', 'form-control')
            elif isinstance(widget, forms.MultiWidget):
                for subwidget in widget.widgets:
                    if isinstance(subwidget, forms.TextInput):
                        subwidget.attrs.setdefault('class', 'form-control')
                    elif isinstance(subwidget, forms.NumberInput):
                        subwidget.attrs.update({'class': 'form-control', 'type': 'number', 'min': '0.00'})
                    elif isinstance(subwidget, forms.Select):
                        subwidget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')
        

    def add_schema_fields(self, schema: AnnotatedSchema):
        """
        Ajoute dynamiquement les champs du schéma et stocke leurs métadonnées dans self.dynamic_fields_info.
        """
        through_model_class = getattr(schema, 'through_model_class', None)
        if not through_model_class:
            raise ValueError(f"Le schéma {schema.__name__} doit définir through_model_class.")
        for field_name_in_schema in schema.model_fields:
            field_name = schema.get_form_field_name(field_name_in_schema)
            related_model_class = schema.related_model_class
            related_instance = related_model_class.objects.filter(name=field_name_in_schema).first()
            if not related_instance:
                print(f"Warning: {field_name_in_schema} not found in {related_model_class.__name__}. Skipping field {field_name}.")
                continue
            form_field = schema.get_formfield()
            form_field.label = f"{related_instance}"
            self.fields[field_name] = form_field
            self.fields_categories[schema.field_category].append(field_name)
            self.dynamic_fields_info[field_name] = {
                'category': schema.field_category,
                'related_model': related_model_class,
                'through_model': through_model_class,
                'name_in_schema': field_name_in_schema,
            }
            # Initial value if editing
            if self.instance.pk:
                through_entry = (
                    through_model_class.objects
                    .filter(food=self.instance, **{f"{related_model_class._meta.model_name}": related_instance})
                    .only("amount")
                    .first()
                )

                if through_entry:
                    form_field.initial = getattr(through_entry, 'amount', None)
                else:
                    form_field.widget.attrs.update({
                        'class': 'form-control',
                        'placeholder': "!!! No data found for this field !!!",
                    })

    def save(self, commit=True):
        food = super().save(commit=commit)
        for field_name, info in self.dynamic_fields_info.items():
            if info['category'] == 'description':
                continue
            related_instance = info['related_model'].objects.filter(name=info['name_in_schema']).first()
            if not related_instance:
                continue
            amount = self.cleaned_data.get(field_name)
            filter_kwargs = {'food': food, info['related_model']._meta.model_name: related_instance}
            if amount:
                info['through_model'].objects.update_or_create(defaults={'amount': amount}, **filter_kwargs)
            else:
                info['through_model'].objects.filter(**filter_kwargs).delete()
        return food