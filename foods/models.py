from typing import final
from typing import override

from django.db import models
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower
from django.db.models.functions import Upper
from quantityfield.fields import QuantityField

from foods.units import DEFAULT_ENERGY_UNIT
from foods.units import DEFAULT_MACRONUTRIENT_UNIT
from foods.units import DEFAULT_VITAMIN_UNIT
from foods.units import ENERGY_UNIT_CHOICES_VALUES
from foods.units import VITAMIN_UNIT_CHOICES
from foods.units import VITAMIN_UNIT_CHOICES_VALUES

from .fields import EAN13Field


@final
class Macronutrient(models.Model):
    name = models.CharField(max_length=100, primary_key=True)
    description = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            UniqueConstraint(
                Lower("name"),
                name="unique_macronutrient_name_case_insensitive",
            ),
        ]

    @override
    def __str__(self) -> str:
        label: str = self.name.replace("_", " ").title()
        if self.description:
            label += f" ({self.description})"
        return label


@final
class Vitamin(models.Model):
    name = models.CharField(max_length=100, primary_key=True)
    common_name = models.TextField(max_length=100, blank=True)
    atc_code = models.CharField(max_length=7, unique=True)
    chembl_id = models.CharField(max_length=12, unique=True)

    # Conventional default unit for the given vitamin to show in the form
    default_unit_in_form = models.CharField(
        choices=VITAMIN_UNIT_CHOICES,
        max_length=10,
        default=DEFAULT_VITAMIN_UNIT,
    )

    class Meta:
        constraints = [
            UniqueConstraint(
                Lower("name"),
                name="unique_vitamin_name_case_insensitive",
            ),
            UniqueConstraint(
                Upper("atc_code"),
                name="unique_vitamin_atc_code_case_insensitive",
            ),
            UniqueConstraint(
                Upper("chembl_id"),
                name="unique_vitamin_chembl_id_case_insensitive",
            ),
        ]

    @override
    def __str__(self) -> str:
        label: str = self.name.replace("_", " ").title()
        if self.common_name:
            label += f" ({self.common_name})"
        return label


@final
class Food(models.Model):
    barcode = EAN13Field(primary_key=True)
    name = models.CharField(max_length=100)
    image = models.ImageField(upload_to="images/products/", null=True, blank=True)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    # 🔹 Energy
    energy: QuantityField = QuantityField(
        base_units=DEFAULT_ENERGY_UNIT,
        unit_choices=ENERGY_UNIT_CHOICES_VALUES,
        null=True,
    )  # pyright: ignore[reportCallIssue]

    # 🔹 Macronutrients
    macronutrients = models.ManyToManyField(  # pyright: ignore[reportUnknownVariableType]
        to=Macronutrient,
        through="FoodMacronutrient",
        related_name="foods",
    )

    # 🔹 Vitamins
    vitamins = models.ManyToManyField(  # pyright: ignore[reportUnknownVariableType]
        to=Vitamin,
        through="FoodVitamin",
        related_name="foods",
    )

    @override
    def __str__(self) -> str:
        label: str = self.name.replace("_", " ").title()
        return label


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
        models.UniqueConstraint(fields=["food", "vitamin"], name="unique_food_vitamin"),
    ]

    @final
    class Meta:
        verbose_name = "Food Vitamin"
        verbose_name_plural = "Food Vitamins"
        ordering = ["food", "vitamin"]

    @override
    def __str__(self) -> str:
        return f"{self.food} {self.vitamin} amount"


@final
class FoodMacronutrient(models.Model):
    food = models.ForeignKey(Food, on_delete=models.CASCADE)
    macronutrient = models.ForeignKey(Macronutrient, on_delete=models.CASCADE)
    amount = QuantityField(base_units=DEFAULT_MACRONUTRIENT_UNIT, null=True)  # pyright: ignore[reportCallIssue]

    # For this manually created intermediate table (with "through") I need to add
    # the unicity constraint because Django not doing it :(
    constraints = [
        models.UniqueConstraint(
            fields=["food", "macronutrient"],
            name="unique_food_macronutrient",
        ),
    ]

    @final
    class Meta:
        verbose_name = "Food Macronutrient"
        verbose_name_plural = "Food Macronutrients"
        ordering = ["food", "macronutrient"]

    @override
    def __str__(self) -> str:
        return f"{self.food.name} {self.macronutrient.name} amount"
