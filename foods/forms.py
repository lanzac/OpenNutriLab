from django import forms
from .models import Food, Macronutrient, FoodMacronutrient, Vitamin, FoodVitamin, VITAMIN_UNIT_CHOICES_VALUES, DEFAULT_VITAMIN_UNIT, DEFAULT_MACRONUTRIENT_UNIT
from quantityfield.fields import QuantityFormField
import copy
from .widgets import InputGroupWithLabelWidget


VITAMIN_PREFIX = 'vitamin_'
MACRONUTRIENT_PREFIX = 'macronutrient_'

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
        self.fields_categories = { # it's oredered dict since python 3.7+
            'description': self._meta.fields,
            'macronutrients': [],
            'vitamins': [],
        }

        # Création dynamique des champs pour chaque vitamine
        for vitamin in Vitamin.objects.all():
            field_name = f'{VITAMIN_PREFIX}{vitamin.name}'

            # Champ pour la valeur
            # required=False is set because vitamin is optional to submit form

            unit_choices = prioritize_unit_choice(vitamin.default_unit_in_form, VITAMIN_UNIT_CHOICES_VALUES)

            FoodVitaminFormField = QuantityFormField(
                base_units=vitamin.default_unit_in_form,
                unit_choices=unit_choices,  # On garde les unités de base
                required=False,
                label=f"{vitamin} {f'({vitamin.description})' if vitamin.description else ''}",
            )

            # FoodVitaminFormField = FoodVitamin._meta.get_field('amount').formfield(required=False)

            self.fields[field_name] = FoodVitaminFormField
            self.fields_categories['vitamins'].append(field_name)


            # Pré-remplissage si instance existe
            if self.instance.pk:
                try:
                    fv = FoodVitamin.objects.get(food=self.instance, vitamin=vitamin)
                    self.fields[field_name].initial = fv.amount
                except FoodVitamin.DoesNotExist:
                    pass

        for macronutrient in Macronutrient.objects.all():
            field_name = f'{MACRONUTRIENT_PREFIX}{macronutrient.name}'

            # Champ pour la valeur
            FoodMacronitrientFormField = FoodMacronutrient._meta.get_field('amount').formfield(required=False)
            FoodMacronitrientFormField.label = f"{macronutrient.name} {f'({macronutrient.description})' if macronutrient.description else ''}"


            self.fields[field_name] = FoodMacronitrientFormField
            self.fields_categories['macronutrients'].append(field_name)


            # Pré-remplissage si instance existe
            if self.instance.pk:
                try:
                    fv = FoodMacronutrient.objects.get(food=self.instance, macronutrient=macronutrient)
                    self.fields[field_name].initial = fv.amount
                except FoodMacronutrient.DoesNotExist:
                    pass


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



    def save(self, commit=True):
        food = super().save(commit=commit)

        # Sauvegarde des valeurs de vitamines
        for field_name in self.fields:
            if field_name.startswith(VITAMIN_PREFIX):
                vitamin_name = field_name[len(VITAMIN_PREFIX):]
                amount = self.cleaned_data.get(field_name)

                try:
                    vitamin = Vitamin.objects.get(name=vitamin_name)
                except Vitamin.DoesNotExist:
                    continue  # Sécurité au cas où

                if amount:
                    amount.base_units = DEFAULT_VITAMIN_UNIT
                    FoodVitamin.objects.update_or_create(
                        food=food,
                        vitamin=vitamin,
                        defaults={'amount': amount}
                    )
                else:
                    FoodVitamin.objects.filter(food=food, vitamin=vitamin).delete()

            if field_name.startswith(MACRONUTRIENT_PREFIX):
                macronutrient_name = field_name[len(MACRONUTRIENT_PREFIX):]
                amount = self.cleaned_data.get(field_name)

                try:
                    macronutrient = Macronutrient.objects.get(name=macronutrient_name)
                except Macronutrient.DoesNotExist:
                    continue
                if amount:
                    FoodMacronutrient.objects.update_or_create(
                        food=food,
                        macronutrient=macronutrient,
                        defaults={'amount': amount}
                    )
                else:
                    FoodMacronutrient.objects.filter(food=food, macronutrient=macronutrient).delete()
        return food