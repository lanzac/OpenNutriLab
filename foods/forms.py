from django import forms
from django.db import models
from .models import Food, Macronutrient, FoodMacronutrient, Vitamin, FoodVitamin, VITAMIN_UNIT_CHOICES_VALUES, DEFAULT_VITAMIN_UNIT, DEFAULT_MACRONUTRIENT_UNIT
from quantityfield.fields import QuantityFormField
import copy
from .widgets import InputGroupWithLabelWidget
from .schema import AnnotatedSchema, MacronutrientsSchema
from typing import Any, Optional


def get_through_model_class(main_model, related_model) -> models.Model | None:
    """
    Returns the through/intermediate model between main_model and related_model, or None if not found.
    Works for ManyToMany and ForeignKey relations with a through model.
    """
    
    for field in main_model._meta.get_fields():
        # ManyToMany with explicit through
        if (field.many_to_many and field.related_model == related_model):
            return field.remote_field.through
    return None


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

        # Initialise les catégories de champs
        self.fields_categories: dict[str, list[dict[str, Any]]] = { # it's oredered dict since python 3.7+
            'description': [{"field_name": f} for f in self._meta.fields],
            'macronutrients': [],
            'vitamins': [],
        }

        # Création dynamique des champs pour chaque vitamine
        # for vitamin in Vitamin.objects.all():
        #     field_name = f'{VITAMIN_PREFIX}{vitamin.name}'

        #     # Champ pour la valeur
        #     # required=False is set because vitamin is optional to submit form

        #     unit_choices = prioritize_unit_choice(vitamin.default_unit_in_form, VITAMIN_UNIT_CHOICES_VALUES)

        #     FoodVitaminFormField = QuantityFormField(
        #         base_units=vitamin.default_unit_in_form,
        #         unit_choices=unit_choices,  # On garde les unités de base
        #         required=False,
        #         label=f"{vitamin} {f'({vitamin.description})' if vitamin.description else ''}",
        #     )

        #     # FoodVitaminFormField = FoodVitamin._meta.get_field('amount').formfield(required=False)

        #     self.fields[field_name] = FoodVitaminFormField
        #     self.fields_categories['vitamins'].append(field_name)


        #     # Pré-remplissage si instance existe
        #     if self.instance.pk:
        #         try:
        #             fv = FoodVitamin.objects.get(food=self.instance, vitamin=vitamin)
        #             self.fields[field_name].initial = fv.amount
        #         except FoodVitamin.DoesNotExist:
        #             pass

        
        # Add macronutrient fields using the generic function
        self.add_schema_fields(MacronutrientsSchema)

        for field in self.fields.values():

            if isinstance(field, QuantityFormField):
                # Si c'est un champ QuantityField, on utilise le widget InputGroupWithLabelWidget
                field.widget.attrs['step'] = '0.01'  # Assure que le champ accepte les décimales

            widget = field.widget
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('class', 'form-control')
            elif isinstance(widget, forms.MultiWidget):
                for subwidget in widget.widgets:
                    if isinstance(subwidget, forms.TextInput):
                        subwidget.attrs.setdefault('class', 'form-control')
                    elif isinstance(subwidget, forms.NumberInput):
                        subwidget.attrs.update({
                            'class': 'form-control',
                            'type': 'number',
                            'min': '0.00',
                        })
                    elif isinstance(subwidget, forms.Select):
                        subwidget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')

    def add_schema_fields(self, schema: AnnotatedSchema):
        """
        Generic: Dynamically add a form field for each field defined in the schema.
        Updates self.fields and self.fields_categories in place.
        - schema: the schema class (must have model_fields and field_prefix)
        """
        through_model_class = get_through_model_class(Food, schema.related_model_class)
        
        if (not through_model_class):
            raise ValueError(f"No through model found for {Food.__name__} and {schema.related_model_class.__name__}")
                
        for field_name_in_schema in schema.model_fields:
            field_name = f'{schema.field_category}_{field_name_in_schema}'
            form_field: forms.Field = through_model_class._meta.get_field('amount').formfield(required=False)

            # Get the corresponding field (e.g., fat, sugars) in the related model (models.Model)
            corresponding_field_in_model: models.fields.Field = schema.related_model_class.objects.filter(name=field_name_in_schema).first()
            
            form_field.label = f"{corresponding_field_in_model if corresponding_field_in_model else f'!!!{schema.related_model_class.__name__} not found in database!!!'}"

            self.fields[field_name] = form_field
            self.fields_categories[schema.field_category].append({
                "field_name": field_name, 
                "through_model_class": through_model_class,
                "field_name_in_schema": field_name_in_schema,
                "related_model_class": schema.related_model_class,
            })

            # Assign initial value if editing an instance
            if getattr(self.instance, 'pk', None) and corresponding_field_in_model:
                # Find the name of the related object field in the through model
                filter_kwargs = {
                    'food': self.instance,
                    f"{schema.related_model_class._meta.model_name}__name": field_name_in_schema
                }
                through_entry = through_model_class.objects.filter(**filter_kwargs).first()
                if through_entry and hasattr(through_entry, 'amount'):
                    form_field.initial = through_entry.amount
                elif not through_entry:
                    # Ajoute un warning au champ si aucune entrée n'est trouvée
                    form_field.widget.attrs.update({
                        'class': 'form-control ',
                        'placeholder': "!!! No data found for this field !!!",
                    })

    def save(self, commit=True):
        food = super().save(commit=commit)
        
        for field_category, category in self.fields_categories.items():
            if field_category == 'description':
                continue # Skip description, already saved by super().save()
            
            for field_info in category:
                field_name = field_info['field_name']
                through_model_class = field_info['through_model_class']
                field_name_in_schema = field_info['field_name_in_schema']
                related_model_class = field_info['related_model_class']
                
                related_instance = related_model_class.objects.filter(name=field_name_in_schema).first()
                if not related_instance:
                    continue  # ou lève une exception
                
                # Get the value from the form
                amount = self.cleaned_data.get(field_name)
                
                if amount:
                    filter_kwargs = {
                        'food': self.instance,
                        related_model_class._meta.model_name: related_instance
                    }
                    
                    through_model_class.objects.update_or_create(
                        defaults={'amount': amount},
                        **filter_kwargs
                    )
                else:
                    through_model_class.objects.filter(**filter_kwargs).delete()
                

            

        # Sauvegarde des valeurs de vitamines
        # for field_name in self.fields:
        #     if field_name.startswith(VITAMIN_PREFIX):
        #         vitamin_name = field_name[len(VITAMIN_PREFIX):]
        #         amount = self.cleaned_data.get(field_name)

        #         try:
        #             vitamin = Vitamin.objects.get(name=vitamin_name)
        #         except Vitamin.DoesNotExist:
        #             continue  # Sécurité au cas où

        #         if amount:
        #             amount.base_units = DEFAULT_VITAMIN_UNIT
        #             FoodVitamin.objects.update_or_create(
        #                 food=food,
        #                 vitamin=vitamin,
        #                 defaults={'amount': amount}
        #             )
        #         else:
        #             FoodVitamin.objects.filter(food=food, vitamin=vitamin).delete()

        # return food