from django.core.management.base import BaseCommand
from foods.models import Macronutrient, Vitamin
from foods.units import DEFAULT_MACRONUTRIENT_UNIT, VitaminUnitChoices
from foods.schema import MacronutrientsSchema
import json

class Command(BaseCommand):
    help = "Initializes nutrient types if they do not already exist."
    
    def handle(self, *args, **kwargs):
        
        
        # Macronutrient.objects.all().delete()
        # Initialize Macronutrients from the MacronutrientsSchema
        schema_props = MacronutrientsSchema.model_json_schema()["properties"]
        fixture = []

        for field, props in schema_props.items():
            title = props.get("title")
            fixture.append({
                "model": "foods.macronutrient",
                "pk": field,
                "fields": {
                    "description": ""
                }
            })

        with open("foods/fixtures/macronutrients.json", "w") as f:
            json.dump(fixture, f, indent=2)
        

        # vitamins_data = [
        #     {"name": "A", "description": "", "default_unit_in_form": VitaminUnitChoices.MG.value},
        #     {"name": "B1", "description": "Thiamine", "default_unit_in_form": VitaminUnitChoices.MG.value},
        #     {"name": "B2", "description": "Riboflavin", "default_unit_in_form": VitaminUnitChoices.MG.value},
        #     {"name": "B3", "description": "Niacin", "default_unit_in_form": VitaminUnitChoices.MG.value},
        #     {"name": "B5", "description": "Pantothenic Acid", "default_unit_in_form": VitaminUnitChoices.MG.value},
        #     {"name": "B6", "description": "Pyridoxine", "default_unit_in_form": VitaminUnitChoices.MG.value},
        #     {"name": "B7", "description": "Biotin", "default_unit_in_form": VitaminUnitChoices.UG.value},
        #     {"name": "B9", "description": "Folate", "default_unit_in_form": VitaminUnitChoices.UG.value},
        #     {"name": "B12", "description": "Cobalamin", "default_unit_in_form": VitaminUnitChoices.UG.value},
        #     {"name": "C", "description": "", "default_unit_in_form": VitaminUnitChoices.MG.value},
        #     {"name": "D", "description": "", "default_unit_in_form": VitaminUnitChoices.UG.value},
        #     {"name": "E", "description": "", "default_unit_in_form": VitaminUnitChoices.MG.value},
        #     {"name": "K", "description": "", "default_unit_in_form": VitaminUnitChoices.UG.value}
        # ]

        # # Vitamin.objects.all().delete()

        # for vitamin_data in vitamins_data:
        #     # On passe les champs en keyword arguments pour get_or_create
        #     vitamin_obj, created = Vitamin.objects.get_or_create(
        #         name=vitamin_data["name"],
        #         defaults={
        #             "description": vitamin_data["description"],
        #             "default_unit_in_form": vitamin_data["default_unit_in_form"]
        #         }
        #     )
        #     if created:
        #         self.stdout.write(self.style.SUCCESS(f'Vitamin "{vitamin_obj.name}" created.'))
        #     else:
        #         self.stdout.write(f'Vitamin "{vitamin_obj.name}" already exists.')
