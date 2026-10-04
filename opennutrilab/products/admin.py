from decimal import Decimal
from typing import Any

from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db import transaction
from django.db.models import Count
from django.db.models import QuerySet
from django.http import HttpRequest
from django.http import HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.template.response import TemplateResponse
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
from .services.product_services import plain_amount
from .services.reference_composition import Estimate
from .services.reference_composition import reference_composition
from .services.reference_proposals import propose_foods as propose_foods_for
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


def _estimate_amount(estimate: Estimate, unit: str) -> str:
    """ "9.3 mg", "Below the detection limit: 0.02 g" or "Traces"."""
    qualifier = SourceFoodNutrient.Qualifier
    if estimate.qualifier == qualifier.TRACES:
        return str(qualifier.TRACES.label)
    if estimate.qualifier == qualifier.LESS_THAN:
        limit = plain_amount(estimate.high or Decimal(0))
        return f"{qualifier.LESS_THAN.label}: {limit} {unit}"
    if estimate.amount is None:
        return "-"
    return f"{plain_amount(estimate.amount)} {unit}"


def _estimate_range(estimate: Estimate) -> str:
    low = "?" if estimate.low is None else plain_amount(estimate.low)
    high = "?" if estimate.high is None else plain_amount(estimate.high)
    return f"{low} \u2013 {high}"


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
        "composition",
    )
    readonly_fields = ("suggested_foods", "composition")
    actions = ("propose_foods", "mark_curated")

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

    @admin.display(description=gettext_lazy("Composition"))
    def composition(self, obj: ReferenceIngredient) -> str | SafeString:
        """What the foods say together (see services.reference_composition)."""
        if obj.pk is None:
            return "-"
        estimates = reference_composition(obj)
        if not estimates:
            return _("No composition: no source food gives any value.")
        nutrients = Nutrient.objects.in_bulk(list(estimates))
        ordered = sorted(
            estimates.items(), key=lambda e: (nutrients[e[0]].display_order, e[0])
        )
        return format_html(
            '<div style="max-height: 28em; overflow: auto"><table>'
            "<thead><tr><th>{}</th><th>{}</th><th>{}</th><th>{}</th><th>{}</th></tr>"
            "</thead><tbody>{}</tbody></table></div>",
            _("Nutrient"),
            _("Amount per 100 g"),
            _("Range"),
            _("Grades"),
            _("Foods"),
            format_html_join(
                "",
                "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>",
                (
                    (
                        nutrients[code].name,
                        _estimate_amount(estimate, nutrients[code].unit),
                        _estimate_range(estimate),
                        ", ".join(estimate.grades),
                        ", ".join(str(food) for food in estimate.foods),
                    )
                    for code, estimate in ordered
                ),
            ),
        )

    @admin.action(
        description=gettext_lazy("Propose CIQUAL foods for the selected references"),
        permissions=["change"],
    )
    def propose_foods(
        self, request: HttpRequest, queryset: QuerySet[ReferenceIngredient]
    ) -> HttpResponseBase | None:
        """
        Propose a food for each selected reference that has none, to check.

        Two steps on one action: the first shows a proposal per reference, the
        second (the form's "apply") links the ones that are checked, each to
        the food chosen. Nothing is linked without that second step.
        """
        waiting = list(queryset.filter(food_count=0))
        if "apply" in request.POST:
            self._link_proposed_foods(request, waiting)
            return HttpResponseRedirect(request.get_full_path())
        if not waiting:
            self.message_user(
                request,
                _("The selected references already have source foods."),
                level=messages.WARNING,
            )
            return None
        context = {
            **self.admin_site.each_context(request),
            "title": _("Propose CIQUAL foods"),
            "opts": self.opts,
            "proposals": [
                (proposal, self.used_by(proposal.reference))
                for proposal in propose_foods_for(waiting)
            ],
            "selected_ids": request.POST.getlist(ACTION_CHECKBOX_NAME),
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(
            request, "admin/products/referenceingredient/proposals.html", context
        )

    def _link_proposed_foods(
        self, request: HttpRequest, references: list[ReferenceIngredient]
    ) -> None:
        mark_curated = "mark_curated" in request.POST
        linked = curated = 0
        with transaction.atomic():
            for reference in references:
                if f"link_{reference.pk}" not in request.POST:
                    continue
                choice = request.POST.get(f"choice_{reference.pk}", "")
                food = (
                    SourceFood.objects.filter(pk=int(choice)).first()
                    if choice.isdigit()
                    else None
                )
                if food is None:
                    continue
                reference.source_foods.add(food)
                linked += 1
                if mark_curated and reference.name_en:
                    reference.status = ReferenceIngredient.Status.CURATED
                    reference.save(update_fields=["status"])
                    curated += 1
        self.message_user(
            request,
            _(
                "%(linked)d reference(s) linked to a CIQUAL food, "
                "%(curated)d marked as curated."
            )
            % {"linked": linked, "curated": curated},
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
