from django.contrib import admin
from .models import Food, Vitamin, FoodVitamin, Macronutrient, FoodMacronutrient
# Register your models here.

admin.site.register([Food, Macronutrient, FoodMacronutrient, Vitamin, FoodVitamin])