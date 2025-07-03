from django.core.management.base import BaseCommand
from django.core.management import call_command
from foods.models import Macronutrient

class Command(BaseCommand):
    help = "Clear Macronutrient table and load fixture"

    def handle(self, *args, **kwargs):
        self.stdout.write("Deleting Macronutrient data...")
        Macronutrient.objects.all().delete()
        self.stdout.write("Loading macronutrients fixture...")
        call_command('loaddata', 'macronutrients.json')
        self.stdout.write("Done.")
