from django.db import models
import pint.babel_names
from quantityfield.fields import QuantityField


# Default Pint units definition file
# https://github.com/hgrecco/pint/blob/master/pint/default_en.txt
ENERGY_UNIT_CHOICES = ['kJ', 'kcal']

VITAMIN_UNIT_CHOICES = ['mg', 'µg']

VITAMIN_UNIT_CHOICES_HUMAN_READABLE = [
    ('mg', 'mg'),
    ('µg', 'µg'),
]

DEFAULT_MACRONUTRIENT_UNIT = 'g'
DEFAULT_VITAMIN_UNIT = 'mg'


class Macronutrient(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"Macronutrient {self.name}"

class Vitamin(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    emojis = models.CharField(max_length=100, blank=True, null=True)
    # Conventional default unit for the given vitamin to show in the form
    default_unit_in_form = models.CharField(
        choices=VITAMIN_UNIT_CHOICES_HUMAN_READABLE,
        max_length=2,
        default=DEFAULT_VITAMIN_UNIT
    )

    def __str__(self):
        return f"Vitamin {self.name} {self.emojis if self.emojis else ''}"


class Food(models.Model):
    barcode = models.CharField(max_length=13, primary_key=True)  # EAN-13 format
    name = models.CharField(max_length=100)
    image = models.ImageField(upload_to='images/products/', null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # 🔹 Energy
    energy = QuantityField(base_units='kJ', unit_choices=ENERGY_UNIT_CHOICES, null=True)
    # energy = MeasurementField(measurement=Energy, unit_choices=ENERGY_UNIT_CHOICES, null=True)

    # 🔹 Vitamins
    vitamins = models.ManyToManyField(Vitamin, through='FoodVitamin')

    def __str__(self):
        return f"{self.name}"


class FoodVitamin(models.Model):
    food = models.ForeignKey('Food', on_delete=models.CASCADE)
    vitamin = models.ForeignKey(Vitamin, on_delete=models.CASCADE)
    # amount = MeasurementField(measurement=Mass, unit_choices=VITAMIN_UNIT_CHOICES)
    amount = QuantityField(base_units=DEFAULT_VITAMIN_UNIT, unit_choices=VITAMIN_UNIT_CHOICES)

    # For this manually created intermediate table (with "through") I need to add
    # the unicity constraint because Django not doing it :(
    constraints = [
        models.UniqueConstraint(
            fields=['food', 'vitamin'],
            name='unique_food_vitamin'
        )
    ]

    def __str__(self):
        return f"{self.food.name} Vitamin {self.vitamin.name} amount"
    class Meta:
        verbose_name = "Food Vitamin"
        verbose_name_plural = "Food Vitamins"
        ordering = ['food', 'vitamin']

class FoodMacronutrient(models.Model):
    food = models.ForeignKey('Food', on_delete=models.CASCADE)
    macronutrient = models.ForeignKey(Macronutrient, on_delete=models.CASCADE)
    amount = QuantityField(base_units=DEFAULT_MACRONUTRIENT_UNIT, null=True)

    # For this manually created intermediate table (with "through") I need to add
    # the unicity constraint because Django not doing it :(
    constraints = [
        models.UniqueConstraint(
            fields=['food', 'macronutrient'],
            name='unique_food_macronutrient'
        )
    ]

    def __str__(self):
        return f"{self.food.name} Macronutrient {self.macronutrient.name} amount"
    class Meta:
        verbose_name = "Food Macronutrient"
        verbose_name_plural = "Food Macronutrients"
        ordering = ['food', 'macronutrient']