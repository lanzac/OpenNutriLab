from django.db import models
from quantityfield.fields import QuantityField
from foods.units import (
    DEFAULT_ENERGY_UNIT,
    ENERGY_UNIT_CHOICES_VALUES,
    DEFAULT_MACRONUTRIENT_UNIT,
    DEFAULT_VITAMIN_UNIT,
    VITAMIN_UNIT_CHOICES,
    VITAMIN_UNIT_CHOICES_VALUES
)
from .fields import EAN13Field

class Macronutrient(models.Model):
    name = models.CharField(max_length=100, primary_key=True)
    description = models.TextField(blank=True)

    def __str__(self):
        """
        Returns a user-friendly label for the macronutrient, including its description if available.
        """
        label = self.name.replace('_', ' ').title()
        if self.description:
            label += f" ({self.description})"
        return label


class Vitamin(models.Model):
    name = models.CharField(max_length=100, primary_key=True)
    description = models.TextField(blank=True)
    emojis = models.CharField(max_length=100, blank=True, null=True)
    # Conventional default unit for the given vitamin to show in the form
    default_unit_in_form = models.CharField(
        choices=VITAMIN_UNIT_CHOICES,
        max_length=10,
        default=DEFAULT_VITAMIN_UNIT
    )

    def __str__(self):
        return f"Vitamin {self.name} {self.emojis if self.emojis else ''}"


class Food(models.Model):
    barcode = EAN13Field(primary_key=True)
    name = models.CharField(max_length=100)
    image = models.ImageField(upload_to='images/products/', null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # 🔹 Energy
    energy = QuantityField(base_units=DEFAULT_ENERGY_UNIT, unit_choices=ENERGY_UNIT_CHOICES_VALUES, null=True)


    # 🔹 Macronutrients
    macronutrients = models.ManyToManyField(
        Macronutrient,
        through='FoodMacronutrient',
        related_name='foods'
    )

    # 🔹 Vitamins
    vitamins = models.ManyToManyField(
        Vitamin,
        through='FoodVitamin',
        related_name='foods')


    def __str__(self):
        return f"{self.name}"


class FoodVitamin(models.Model):
    food = models.ForeignKey('Food', on_delete=models.CASCADE)
    vitamin = models.ForeignKey(Vitamin, on_delete=models.CASCADE)
    # QuantityField unit_choices does not show the human-readable representation
    # in the form, so I use a custom unit_choices, tell me if I'm wrong or if
    # there is a better way to do it :)
    amount = QuantityField(base_units=DEFAULT_VITAMIN_UNIT, unit_choices=VITAMIN_UNIT_CHOICES_VALUES, null=True)

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
