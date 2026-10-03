from django.contrib import admin

from .models import Ingredient
from .models import IngredientTaxon
from .models import Nutrient
from .models import NutrientComponent
from .models import Product
from .models import ProductNutrient
from .models import ReferenceIngredient
from .models import Source
from .models import SourceFood
from .models import SourceFoodNutrient


class NutrientComponentInline(admin.TabularInline[NutrientComponent]):
    model = NutrientComponent
    fk_name = "derived"
    extra = 0


@admin.register(Nutrient)
class NutrientAdmin(admin.ModelAdmin[Nutrient]):
    list_display = (
        "code",
        "name_fr",
        "name_en",
        "unit",
        "group",
        "parent",
        "on_label",
        "ciqual_code",
        "off_key",
    )
    list_filter = ("group", "on_label")
    inlines = (NutrientComponentInline,)


class ProductNutrientInline(admin.TabularInline[ProductNutrient]):
    model = ProductNutrient
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin[Product]):
    list_display = ("barcode", "name", "created_at")
    search_fields = ("barcode", "name")
    inlines = (ProductNutrientInline,)


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin[Ingredient]):
    list_display = (
        "indented_name",
        "product",
        "percentage",
        "off_ciqual_food_code",
        "reference",
    )
    list_filter = ("product",)
    autocomplete_fields = ("reference",)
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


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin[Source]):
    list_display = ("code", "name", "version")


class SourceFoodNutrientInline(admin.TabularInline[SourceFoodNutrient]):
    model = SourceFoodNutrient
    extra = 0


@admin.register(SourceFood)
class SourceFoodAdmin(admin.ModelAdmin[SourceFood]):
    list_display = ("code", "name_fr", "name_en", "source", "food_group")
    list_filter = ("source",)
    search_fields = ("code", "name_fr", "name_en")
    inlines = (SourceFoodNutrientInline,)


@admin.register(IngredientTaxon)
class IngredientTaxonAdmin(admin.ModelAdmin[IngredientTaxon]):
    # Loaded by `manage.py import_off_taxonomy`, which overwrites edits made here.
    list_display = ("off_id", "name_en", "name_fr")
    search_fields = ("off_id", "name_en", "name_fr")


@admin.register(ReferenceIngredient)
class ReferenceIngredientAdmin(admin.ModelAdmin[ReferenceIngredient]):
    list_display = ("name_fr", "name_en")
    search_fields = ("name_fr", "name_en")
    autocomplete_fields = ("source_foods",)
