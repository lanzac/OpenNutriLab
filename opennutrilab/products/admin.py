from typing import Any

from django.contrib import admin
from django.contrib import messages
from django.db.models import Count
from django.db.models import QuerySet
from django.http import HttpRequest
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.utils.safestring import SafeString
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

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
from .services.reference_services import ReferenceNameError
from .services.reference_services import create_reference_from_foods
from .services.reference_services import suggest_source_foods


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
    list_display = ("indented_name", "product", "percentage")
    list_filter = ("product",)
    list_select_related = ("product", "reference")
    autocomplete_fields = ("reference",)
    ordering = ("id",)

    @admin.display(description="Ingredient (hierarchical)")
    def indented_name(self, obj: Ingredient) -> str:
        indent = "— " * self.get_level(obj)
        return f"{indent}{obj.reference}"

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
    list_filter = ("source", "food_group", "food_subgroup")
    search_fields = ("code", "name_fr", "name_en")
    inlines = (SourceFoodNutrientInline,)
    actions = ("create_reference",)

    @admin.action(
        description=gettext_lazy(
            "Create a reference ingredient from the selected foods"
        )
    )
    def create_reference(
        self, request: HttpRequest, queryset: QuerySet[SourceFood]
    ) -> HttpResponseRedirect | None:
        """One reference that draws on all of them, opened to be named."""
        foods = list(queryset.select_related("source").order_by("source__code", "code"))
        try:
            reference = create_reference_from_foods(foods)
        except ReferenceNameError as e:
            self.message_user(request, str(e), level=messages.ERROR)
            return None
        return HttpResponseRedirect(
            reverse("admin:products_referenceingredient_change", args=[reference.pk])
        )


@admin.register(IngredientTaxon)
class IngredientTaxonAdmin(admin.ModelAdmin[IngredientTaxon]):
    # Loaded by `manage.py import_off_taxonomy`, which overwrites edits made here.
    list_display = ("off_id", "name_en", "name_fr")
    search_fields = ("off_id", "name_en", "name_fr")


class HasSourceFoodsFilter(admin.SimpleListFilter):
    title = gettext_lazy("source foods")
    parameter_name = "source_foods"

    def lookups(
        self, request: HttpRequest, model_admin: admin.ModelAdmin[Any]
    ) -> list[tuple[Any, str]]:
        return [
            ("with", _("With source foods")),
            ("without", _("Without source foods")),
        ]

    def queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
        if self.value() == "with":
            return queryset.filter(food_count__gt=0)
        if self.value() == "without":
            return queryset.filter(food_count=0)
        return queryset


@admin.register(ReferenceIngredient)
class ReferenceIngredientAdmin(admin.ModelAdmin[ReferenceIngredient]):
    """
    Where the references are curated: those to review come with how many
    products use them and how many source foods they draw on, the most used
    first, and a reference's page suggests foods that may fit it.
    """

    list_display = ("name_en", "name_fr", "status", "used_by", "source_food_count")
    list_filter = ("status", HasSourceFoodsFilter)
    search_fields = ("name_fr", "name_en")
    autocomplete_fields = ("source_foods",)
    fields = (
        "name_en",
        "name_fr",
        "status",
        "description",
        "source_foods",
        "suggested_foods",
    )
    readonly_fields = ("suggested_foods",)
    actions = ("mark_curated",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[ReferenceIngredient]:
        # Not super(): it sorts by get_ordering before the counts exist. The
        # list and the autocomplete apply that ordering to this queryset.
        return ReferenceIngredient.objects.annotate(
            usage_count=Count("usages", distinct=True),
            food_count=Count("source_foods", distinct=True),
        )

    def get_ordering(self, request: HttpRequest) -> list[str]:
        return ["-usage_count", "name_en", "id"]

    @admin.display(description=gettext_lazy("Ingredients"), ordering="usage_count")
    def used_by(self, obj: ReferenceIngredient) -> int:
        count: object = getattr(obj, "usage_count", None)
        return count if isinstance(count, int) else obj.usages.count()

    @admin.display(description=gettext_lazy("Source foods"), ordering="food_count")
    def source_food_count(self, obj: ReferenceIngredient) -> int:
        count: object = getattr(obj, "food_count", None)
        return count if isinstance(count, int) else obj.source_foods.count()

    @admin.display(description=gettext_lazy("Foods that may fit"))
    def suggested_foods(self, obj: ReferenceIngredient) -> str | SafeString:
        if obj.pk is None:
            return "-"
        foods = suggest_source_foods(obj)
        if not foods:
            return _("None found by name.")
        return format_html(
            "<ul>{}</ul>",
            format_html_join(
                "",
                '<li><a href="{}">{} {}</a> ({})</li>',
                (
                    (
                        reverse("admin:products_sourcefood_change", args=[food.pk]),
                        food.code,
                        food.name_fr or food.name_en,
                        food.source.code,
                    )
                    for food in foods
                ),
            ),
        )

    @admin.action(description=gettext_lazy("Mark the selected references as curated"))
    def mark_curated(
        self, request: HttpRequest, queryset: QuerySet[ReferenceIngredient]
    ) -> None:
        """A curated reference needs its English name, so those lacking it wait."""
        pks = list(queryset.values_list("pk", flat=True))
        ready = ReferenceIngredient.objects.filter(pk__in=pks).exclude(name_en="")
        updated = ready.update(status=ReferenceIngredient.Status.CURATED)
        if skipped := len(pks) - ready.count():
            self.message_user(
                request,
                _("%(count)d reference(s) lack an English name and were not marked.")
                % {"count": skipped},
                level=messages.WARNING,
            )
        self.message_user(
            request, _("%(count)d reference(s) marked as curated.") % {"count": updated}
        )
