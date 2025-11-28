from django.contrib import admin

from .models import Ingredient
from .models import IngredientRef
from .models import Macronutrient
from .models import Product
from .models import ProductMacronutrient
from .models import ProductVitamin
from .models import Vitamin

# Register your models here.

admin.site.register(
    [
        Product,
        Macronutrient,
        ProductMacronutrient,
        Vitamin,
        ProductVitamin,
        IngredientRef,
    ]
)


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin[Ingredient]):
    list_display = (
        "indented_name",
        "product",
        "percentage",
    )

    ordering = ("id",)

    @admin.display(description="Ingredient (hierarchical)")
    def indented_name(self, obj: Ingredient) -> str:
        indent = "— " * self.get_level(obj)
        return f"{indent}{obj.name}"

    def get_level(self, obj: Ingredient) -> int:
        level = 0
        parent = obj.parent
        while parent:
            level += 1
            parent = parent.parent
        return level
