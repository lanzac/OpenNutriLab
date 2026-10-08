from decimal import Decimal
from typing import Any

from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction
from django.db.models import Count
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import QuerySet
from django.db.models import Subquery
from django.db.models.functions import Coalesce
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

from .models import Additive
from .models import AdditiveNutrient
from .models import Ingredient
from .models import IngredientTaxon
from .models import Nutrient
from .models import NutrientComponent
from .models import Preparation
from .models import Product
from .models import ProductNutrient
from .models import ReferenceIngredient
from .models import Source
from .models import SourceFood
from .models import SourceFoodNutrient
from .services.additive_services import AdditiveConversionError
from .services.additive_services import additives_known_as
from .services.additive_services import convert_to_additive
from .services.additive_services import ensure_convertible as ensure_additive
from .services.english_names import propose_english_names as propose_names_for
from .services.english_names import taken_by
from .services.preparation_services import Part
from .services.preparation_services import PreparationConversionError
from .services.preparation_services import convert_to_preparation
from .services.preparation_services import ensure_convertible
from .services.preparation_services import parts_seen
from .services.product_services import plain_amount
from .services.reference_composition import Estimate
from .services.reference_composition import reference_composition
from .services.reference_proposals import propose_foods as propose_foods_for
from .services.reference_services import ReferenceNameError
from .services.reference_services import clean_name
from .services.reference_services import create_reference_from_foods
from .services.reference_services import suggest_source_foods
from .services.translation import translation_enabled


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
    list_select_related = ("product", "reference", "preparation", "additive")
    autocomplete_fields = ("reference", "preparation", "additive")
    ordering = ("id",)

    @admin.display(description="Ingredient (hierarchical)")
    def indented_name(self, obj: Ingredient) -> str:
        indent = "— " * self.get_level(obj)
        return f"{indent}{obj.item}"

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


def most_used_first(ingredient_field: str) -> list[Any]:
    """
    The ordering of the references and of the preparations: the most used first.

    `ingredient_field` is the one of Ingredient that points to them. It is a
    subquery and not the `usage_count` annotation, because Django also applies the
    ordering to the queryset of the fields of other admins that point to them (the
    autocomplete of an ingredient's form), which is not annotated, and refuses an
    aggregate there.
    """
    uses = (
        Ingredient.objects.filter(**{ingredient_field: OuterRef("pk")})
        .order_by()
        .values(ingredient_field)
        .annotate(total=Count("pk"))
        .values("total")
    )
    return [Coalesce(Subquery(uses), 0).desc(), "name_en", "id"]


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


class HasEnglishNameFilter(admin.SimpleListFilter):
    title = gettext_lazy("English name")
    parameter_name = "english_name"

    def lookups(
        self, request: HttpRequest, model_admin: admin.ModelAdmin[Any]
    ) -> list[tuple[Any, str]]:
        return [
            ("without", _("Without an English name")),
            ("with", _("With an English name")),
        ]

    def queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
        if self.value() == "without":
            return queryset.filter(name_en="")
        if self.value() == "with":
            return queryset.exclude(name_en="")
        return queryset


def _usage_count(item: Any) -> int:
    count: object = getattr(item, "usage_count", None)
    return count if isinstance(count, int) else item.usages.count()


def propose_english_names_page(
    model_admin: admin.ModelAdmin[Any], request: HttpRequest, queryset: QuerySet[Any]
) -> HttpResponseBase | None:
    """
    Propose an English name for each selected reference, preparation or additive
    that has none (see services.english_names).

    Two steps on one action, as for the foods: the first shows a proposal for
    each, with where it comes from, in a field that can be edited, the second
    (the form's "apply") gives the ticked ones the name in their field. Nothing is
    written without that second step.
    """
    waiting = list(
        queryset.filter(name_en="")
        .prefetch_related("source_foods")
        .order_by("name_fr", "id")
    )
    if "apply" in request.POST:
        _give_english_names(model_admin, request, waiting)
        return HttpResponseRedirect(request.get_full_path())
    if not waiting:
        model_admin.message_user(
            request,
            _("The selected ones already have an English name."),
            level=messages.WARNING,
        )
        return None
    proposed = propose_names_for(waiting)
    if proposed.translator_failed:
        model_admin.message_user(
            request,
            _(
                "The translator did not answer: the names it would have "
                "proposed are left blank."
            ),
            level=messages.WARNING,
        )
    context = {
        **model_admin.admin_site.each_context(request),
        "title": _("Propose English names"),
        "opts": model_admin.opts,
        "proposals": [
            (proposal, _usage_count(proposal.item)) for proposal in proposed.proposals
        ],
        "translator_set": translation_enabled(),
        "selected_ids": request.POST.getlist(ACTION_CHECKBOX_NAME),
        "action_checkbox_name": ACTION_CHECKBOX_NAME,
    }
    return TemplateResponse(request, "admin/products/english_names.html", context)


def _give_english_names(
    model_admin: admin.ModelAdmin[Any], request: HttpRequest, items: list[Any]
) -> None:
    given = 0
    for item in items:
        name = clean_name(request.POST.get(f"name_{item.pk}", ""))
        if f"apply_{item.pk}" not in request.POST or not name:
            continue
        if other := taken_by(name, item):
            _english_name_refused(
                model_admin,
                request,
                item,
                _("%(name)s is already the English name of %(other)s.")
                % {"name": name, "other": other},
            )
            continue
        item.name_en = name
        try:
            item.clean_fields()
            with transaction.atomic():
                item.save(update_fields=["name_en"])
        except ValidationError as e:
            _english_name_refused(model_admin, request, item, " ".join(e.messages))
        except IntegrityError:
            # Another request gave it since the check.
            _english_name_refused(
                model_admin,
                request,
                item,
                _("%(name)s is already the English name of another.") % {"name": name},
            )
        else:
            given += 1
    model_admin.message_user(
        request, _("%(count)d item(s) given an English name.") % {"count": given}
    )


def _english_name_refused(
    model_admin: admin.ModelAdmin[Any], request: HttpRequest, item: Any, why: str
) -> None:
    model_admin.message_user(request, f"{item.name}: {why}", level=messages.ERROR)


class KnownAsAdditiveFilter(admin.SimpleListFilter):
    """The references that have the name of an additive (see additive_services)."""

    title = gettext_lazy("additive")
    parameter_name = "known_additive"

    def lookups(
        self, request: HttpRequest, model_admin: admin.ModelAdmin[Any]
    ) -> list[tuple[Any, str]]:
        return [("known", _("Known as an additive"))]

    def queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
        if self.value() == "known":
            known = additives_known_as(list(ReferenceIngredient.objects.all()))
            return queryset.filter(pk__in=known)
        return queryset


@admin.register(ReferenceIngredient)
class ReferenceIngredientAdmin(admin.ModelAdmin[ReferenceIngredient]):
    """
    Where the references are curated: those to review come with how many
    products use them and how many source foods they draw on, the most used
    first, and a reference's page suggests foods that may fit it. A reference
    whose parts a label lists is a preparation, and is made one when a product is
    read: how many times each was seen with parts on a label says which are yet to
    be converted, and an action converts them.
    """

    list_display = (
        "name_en",
        "name_fr",
        "status",
        "used_by",
        "seen_with_parts",
        "source_food_count",
    )
    list_filter = (
        "status",
        HasSourceFoodsFilter,
        HasEnglishNameFilter,
        KnownAsAdditiveFilter,
    )
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
    actions = (
        "propose_foods",
        "propose_english_names",
        "mark_curated",
        "make_preparation",
        "make_additive",
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[ReferenceIngredient]:
        # Not super(): it sorts by get_ordering before the counts exist. The
        # list and the autocomplete apply that ordering to this queryset.
        return ReferenceIngredient.objects.annotate(
            usage_count=Count("usages", distinct=True),
            with_parts_count=Count(
                "usages", filter=Q(usages__sub_ingredients__isnull=False), distinct=True
            ),
            food_count=Count("source_foods", distinct=True),
        )

    def get_ordering(self, request: HttpRequest) -> list[Any]:
        return most_used_first("reference")

    @admin.display(description=gettext_lazy("Ingredients"), ordering="usage_count")
    def used_by(self, obj: ReferenceIngredient) -> int:
        count: object = getattr(obj, "usage_count", None)
        return count if isinstance(count, int) else obj.usages.count()

    @admin.display(
        description=gettext_lazy("Seen with parts"), ordering="with_parts_count"
    )
    def seen_with_parts(self, obj: ReferenceIngredient) -> int:
        """The times a label listed its parts: what a preparation looks like."""
        count: object = getattr(obj, "with_parts_count", None)
        if isinstance(count, int):
            return count
        return obj.usages.filter(sub_ingredients__isnull=False).distinct().count()

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
        # What the licences of the sources ask to be shown wherever their data is.
        sources = {
            food.source for estimate in estimates.values() for food in estimate.foods
        }
        return format_html(
            '<div style="max-height: 28em; overflow: auto"><table>'
            "<thead><tr><th>{}</th><th>{}</th><th>{}</th><th>{}</th><th>{}</th></tr>"
            "</thead><tbody>{}</tbody></table></div>{}",
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
            format_html_join(
                "",
                "<p>{}</p>",
                (
                    (source.attribution,)
                    for source in sorted(sources, key=lambda s: s.code)
                    if source.attribution
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

    @admin.action(
        description=gettext_lazy("Propose English names for the selected references"),
        permissions=["change"],
    )
    def propose_english_names(
        self, request: HttpRequest, queryset: QuerySet[ReferenceIngredient]
    ) -> HttpResponseBase | None:
        return propose_english_names_page(self, request, queryset)

    def has_make_additive_permission(self, request: HttpRequest) -> bool:
        """It adds an additive, repoints ingredients and deletes a reference."""
        return request.user.has_perms(
            (
                "products.add_additive",
                "products.change_ingredient",
                "products.delete_referenceingredient",
            )
        )

    @admin.action(
        description=gettext_lazy("Make an additive of the selected references"),
        permissions=["make_additive"],
    )
    def make_additive(
        self, request: HttpRequest, queryset: QuerySet[ReferenceIngredient]
    ) -> HttpResponseBase | None:
        """
        Turn each ticked reference into an additive (see additive_services).

        Two steps on one action, as for the preparations: the first shows what each
        reference becomes, the second (the form's "apply") converts the ticked ones.
        A reference that has the name of an additive is merged into it, and is ticked
        for the curator when the name is the same word and not only its plural.
        """
        selected = list(queryset.order_by("name_en", "name_fr", "id"))
        known = additives_known_as(selected)
        if "apply" in request.POST:
            ticked = [r for r in selected if f"convert_{r.pk}" in request.POST]
            self._make_additives(request, ticked)
            return HttpResponseRedirect(request.get_full_path())
        rows: list[dict[str, Any]] = []
        for reference in selected:
            match = known.get(reference.pk)
            try:
                ensure_additive(reference, match)
                refusal = ""
            except AdditiveConversionError as e:
                refusal = str(e)
            rows.append(
                {
                    "reference": reference,
                    "uses": self.used_by(reference),
                    "match": match,
                    "refusal": refusal,
                    "ticked": not refusal and (match is None or match.exact),
                }
            )
        if all(row["refusal"] for row in rows):
            for row in rows:
                self.message_user(request, row["refusal"], level=messages.ERROR)
            return None
        context = {
            **self.admin_site.each_context(request),
            "title": _("Make additives"),
            "opts": self.opts,
            "rows": rows,
            "selected_ids": request.POST.getlist(ACTION_CHECKBOX_NAME),
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(
            request, "admin/products/referenceingredient/make_additive.html", context
        )

    def _make_additives(
        self, request: HttpRequest, references: list[ReferenceIngredient]
    ) -> None:
        made: list[str] = []
        for reference in references:
            name = reference.name
            try:
                convert_to_additive(reference)
            except AdditiveConversionError as e:
                self.message_user(request, str(e), level=messages.ERROR)
            else:
                made.append(name)
        if made:
            self.message_user(
                request,
                _(
                    "%(count)d reference(s) made into additives: %(names)s. "
                    "Check them, then mark them as curated."
                )
                % {"count": len(made), "names": ", ".join(made)},
            )

    def has_make_preparation_permission(self, request: HttpRequest) -> bool:
        """It adds a preparation, repoints ingredients and deletes a reference."""
        return request.user.has_perms(
            (
                "products.add_preparation",
                "products.change_ingredient",
                "products.delete_referenceingredient",
            )
        )

    @admin.action(
        description=gettext_lazy("Make a preparation of the selected references"),
        permissions=["make_preparation"],
    )
    def make_preparation(
        self, request: HttpRequest, queryset: QuerySet[ReferenceIngredient]
    ) -> HttpResponseBase | None:
        """
        Turn each selected reference into a preparation (see preparation_services).

        Two steps on one action, as the proposals are: the first shows what each
        reference becomes, and which cannot, the second (the form's "apply")
        converts. Nothing is deleted without that second step.
        """
        selected = list(queryset.order_by("name_en", "name_fr", "id"))
        if "apply" in request.POST:
            self._make_preparations(request, selected)
            return HttpResponseRedirect(request.get_full_path())
        rows: list[tuple[ReferenceIngredient, str, list[Part]]] = []
        for reference in selected:
            try:
                ensure_convertible(reference)
            except PreparationConversionError as e:
                rows.append((reference, str(e), []))
            else:
                rows.append((reference, "", parts_seen(reference)))
        if all(refusal for _reference, refusal, _parts in rows):
            for _reference, refusal, _parts in rows:
                self.message_user(request, refusal, level=messages.ERROR)
            return None
        context = {
            **self.admin_site.each_context(request),
            "title": _("Make preparations"),
            "opts": self.opts,
            "rows": [
                {
                    "reference": reference,
                    "uses": self.used_by(reference),
                    "foods": self.source_food_count(reference),
                    "refusal": refusal,
                    "parts": parts,
                }
                for reference, refusal, parts in rows
            ],
            "selected_ids": request.POST.getlist(ACTION_CHECKBOX_NAME),
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(
            request, "admin/products/referenceingredient/make_preparation.html", context
        )

    def _make_preparations(
        self, request: HttpRequest, references: list[ReferenceIngredient]
    ) -> None:
        made: list[str] = []
        for reference in references:
            name = reference.name
            try:
                convert_to_preparation(reference)
            except PreparationConversionError as e:
                self.message_user(request, str(e), level=messages.ERROR)
            else:
                made.append(name)
        if made:
            self.message_user(
                request,
                _(
                    "%(count)d reference(s) made into preparations: %(names)s. "
                    "Check their components, then mark them as curated."
                )
                % {"count": len(made), "names": ", ".join(made)},
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


@admin.register(Preparation)
class PreparationAdmin(admin.ModelAdmin[Preparation]):
    """
    What a label lists the parts of ("mozzarella", "gnocchi", "boulette"), curated
    apart from the true ingredients: the references and the preparations it is
    made of, which stand in when a label lists none of its parts, and the source
    foods it draws on when its composition is known. The most used come first.
    """

    list_display = (
        "name_en",
        "name_fr",
        "status",
        "used_by",
        "component_count",
        "source_food_count",
    )
    list_filter = ("status", HasSourceFoodsFilter, HasEnglishNameFilter)
    search_fields = ("name_fr", "name_en")
    autocomplete_fields = ("components", "preparation_components", "source_foods")
    fields = (
        "name_en",
        "name_fr",
        "status",
        "description",
        "components",
        "preparation_components",
        "source_foods",
    )
    actions = ("propose_english_names", "mark_curated")

    def get_queryset(self, request: HttpRequest) -> QuerySet[Preparation]:
        # Not super(): it sorts by get_ordering before the counts exist.
        return Preparation.objects.annotate(
            usage_count=Count("usages", distinct=True),
            component_count=Count("components", distinct=True)
            + Count("preparation_components", distinct=True),
            food_count=Count("source_foods", distinct=True),
        )

    def get_ordering(self, request: HttpRequest) -> list[Any]:
        return most_used_first("preparation")

    @admin.display(description=gettext_lazy("Ingredients"), ordering="usage_count")
    def used_by(self, obj: Preparation) -> int:
        count: object = getattr(obj, "usage_count", None)
        return count if isinstance(count, int) else obj.usages.count()

    @admin.display(description=gettext_lazy("Components"), ordering="component_count")
    def component_count(self, obj: Preparation) -> int:
        count: object = getattr(obj, "component_count", None)
        if isinstance(count, int):
            return count
        return obj.components.count() + obj.preparation_components.count()

    @admin.display(description=gettext_lazy("Source foods"), ordering="food_count")
    def source_food_count(self, obj: Preparation) -> int:
        count: object = getattr(obj, "food_count", None)
        return count if isinstance(count, int) else obj.source_foods.count()

    @admin.action(
        description=gettext_lazy("Propose English names for the selected preparations"),
        permissions=["change"],
    )
    def propose_english_names(
        self, request: HttpRequest, queryset: QuerySet[Preparation]
    ) -> HttpResponseBase | None:
        return propose_english_names_page(self, request, queryset)

    @admin.action(description=gettext_lazy("Mark the selected preparations as curated"))
    def mark_curated(
        self, request: HttpRequest, queryset: QuerySet[Preparation]
    ) -> None:
        """A curated preparation needs its English name, so those lacking it wait."""
        pks = list(queryset.values_list("pk", flat=True))
        ready = Preparation.objects.filter(pk__in=pks).exclude(name_en="")
        updated = ready.update(status=Preparation.Status.CURATED)
        if skipped := len(pks) - ready.count():
            self.message_user(
                request,
                _("%(count)d preparation(s) lack an English name and were not marked.")
                % {"count": skipped},
                level=messages.WARNING,
            )
        self.message_user(
            request,
            _("%(count)d preparation(s) marked as curated.") % {"count": updated},
        )


class AdditiveNutrientInline(admin.TabularInline[AdditiveNutrient]):
    model = AdditiveNutrient
    extra = 0


@admin.register(Additive)
class AdditiveAdmin(admin.ModelAdmin[Additive]):
    """
    The food additives, curated apart from the true ingredients: the E number and
    the functional class, the nutrients one brings (E300 is vitamin C) with where
    the figure comes from, and the source foods it draws on, if a table has it.
    The most used come first.
    """

    list_display = (
        "name_en",
        "name_fr",
        "code",
        "function",
        "status",
        "used_by",
        "nutrient_count",
        "source_food_count",
    )
    list_filter = ("status", "function", HasSourceFoodsFilter, HasEnglishNameFilter)
    search_fields = ("code", "name_fr", "name_en")
    autocomplete_fields = ("source_foods",)
    fields = (
        "name_en",
        "name_fr",
        "code",
        "function",
        "status",
        "description",
        "source_foods",
    )
    inlines = (AdditiveNutrientInline,)
    actions = ("propose_english_names", "mark_curated")

    def get_queryset(self, request: HttpRequest) -> QuerySet[Additive]:
        # Not super(): it sorts by get_ordering before the counts exist.
        return Additive.objects.annotate(
            usage_count=Count("usages", distinct=True),
            nutrient_count=Count("nutrients", distinct=True),
            food_count=Count("source_foods", distinct=True),
        )

    def get_ordering(self, request: HttpRequest) -> list[Any]:
        return most_used_first("additive")

    @admin.display(description=gettext_lazy("Ingredients"), ordering="usage_count")
    def used_by(self, obj: Additive) -> int:
        count: object = getattr(obj, "usage_count", None)
        return count if isinstance(count, int) else obj.usages.count()

    @admin.display(description=gettext_lazy("Nutrients"), ordering="nutrient_count")
    def nutrient_count(self, obj: Additive) -> int:
        count: object = getattr(obj, "nutrient_count", None)
        return count if isinstance(count, int) else obj.nutrients.count()

    @admin.display(description=gettext_lazy("Source foods"), ordering="food_count")
    def source_food_count(self, obj: Additive) -> int:
        count: object = getattr(obj, "food_count", None)
        return count if isinstance(count, int) else obj.source_foods.count()

    @admin.action(
        description=gettext_lazy("Propose English names for the selected additives"),
        permissions=["change"],
    )
    def propose_english_names(
        self, request: HttpRequest, queryset: QuerySet[Additive]
    ) -> HttpResponseBase | None:
        return propose_english_names_page(self, request, queryset)

    @admin.action(description=gettext_lazy("Mark the selected additives as curated"))
    def mark_curated(self, request: HttpRequest, queryset: QuerySet[Additive]) -> None:
        """A curated additive needs its English name, so those lacking it wait."""
        pks = list(queryset.values_list("pk", flat=True))
        ready = Additive.objects.filter(pk__in=pks).exclude(name_en="")
        updated = ready.update(status=Additive.Status.CURATED)
        if skipped := len(pks) - ready.count():
            self.message_user(
                request,
                _("%(count)d additive(s) lack an English name and were not marked.")
                % {"count": skipped},
                level=messages.WARNING,
            )
        self.message_user(
            request,
            _("%(count)d additive(s) marked as curated.") % {"count": updated},
        )
