from typing import final, override

from django.db import models
from quantityfield.fields import QuantityField

from foods.units import (
    DEFAULT_ENERGY_UNIT,
    DEFAULT_MACRONUTRIENT_UNIT,
    DEFAULT_VITAMIN_UNIT,
    ENERGY_UNIT_CHOICES_VALUES,
    VITAMIN_UNIT_CHOICES,
    VITAMIN_UNIT_CHOICES_VALUES,
)

from .fields import EAN13Field


@final
class Macronutrient(models.Model):
    name = models.CharField(max_length=100, primary_key=True)
    description = models.TextField(blank=True)

    @override
    def __str__(self) -> str:
        label: str = self.name.replace("_", " ").title()
        if self.description:
            label += f" ({self.description})"
        return label


@final
class Vitamin(models.Model):
    name = models.CharField(max_length=100, primary_key=True)
    description = models.TextField(blank=True)
    emojis = models.CharField(max_length=100, blank=True, null=True)
    # Conventional default unit for the given vitamin to show in the form
    default_unit_in_form = models.CharField(
        choices=VITAMIN_UNIT_CHOICES,
        max_length=10,
        default=DEFAULT_VITAMIN_UNIT,
    )

    @override
    def __str__(self) -> str:
        return f"Vitamin {self.name} {self.emojis if self.emojis else ''}"


@final
class Food(models.Model):
    barcode = EAN13Field(primary_key=True)
    name = models.CharField(max_length=100)
    image = models.ImageField(
        upload_to="images/products/", null=True, blank=True
    )
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # 🔹 Energy
    energy: QuantityField = QuantityField(
        base_units=DEFAULT_ENERGY_UNIT,
        unit_choices=ENERGY_UNIT_CHOICES_VALUES,
        null=True,
    )  # pyright: ignore[reportCallIssue]

    # 🔹 Macronutrients
    macronutrients = models.ManyToManyField(  # pyright: ignore[reportUnknownVariableType]
        to=Macronutrient, through="FoodMacronutrient", related_name="foods"
    )

    # 🔹 Vitamins
    vitamins = models.ManyToManyField(  # pyright: ignore[reportUnknownVariableType]
        to=Vitamin, through="FoodVitamin", related_name="foods"
    )

    @override
    def __str__(self) -> str:
        return f"{self.name}"


@final
class FoodVitamin(models.Model):
    food = models.ForeignKey(Food, on_delete=models.CASCADE)
    vitamin = models.ForeignKey(Vitamin, on_delete=models.CASCADE)
    # QuantityField unit_choices does not show the human-readable representation
    # in the form, so I use a custom unit_choices, tell me if I'm wrong or if
    # there is a better way to do it :)
    amount = QuantityField(
        base_units=DEFAULT_VITAMIN_UNIT,
        unit_choices=VITAMIN_UNIT_CHOICES_VALUES,
        null=True,
    )  # pyright: ignore[reportCallIssue]

    # For this manually created intermediate table (with "through") I need to add
    # the unicity constraint because Django not doing it :(
    constraints = [
        models.UniqueConstraint(
            fields=["food", "vitamin"], name="unique_food_vitamin"
        )
    ]

    @override
    def __str__(self) -> str:
        return f"{self.food.name} Vitamin {self.vitamin.name} amount"

    @final
    class Meta:
        verbose_name = "Food Vitamin"
        verbose_name_plural = "Food Vitamins"
        ordering = ["food", "vitamin"]


@final
class FoodMacronutrient(models.Model):
    food = models.ForeignKey(Food, on_delete=models.CASCADE)
    macronutrient = models.ForeignKey(Macronutrient, on_delete=models.CASCADE)
    amount = QuantityField(base_units=DEFAULT_MACRONUTRIENT_UNIT, null=True)  # pyright: ignore[reportCallIssue]

    # For this manually created intermediate table (with "through") I need to add
    # the unicity constraint because Django not doing it :(
    constraints = [
        models.UniqueConstraint(
            fields=["food", "macronutrient"], name="unique_food_macronutrient"
        )
    ]

    @override
    def __str__(self) -> str:
        return (
            f"{self.food.name} Macronutrient {self.macronutrient.name} amount"
        )

    @final
    class Meta:
        verbose_name = "Food Macronutrient"
        verbose_name_plural = "Food Macronutrients"
        ordering = ["food", "macronutrient"]
