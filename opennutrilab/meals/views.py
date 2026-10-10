from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.views import View

from opennutrilab.meals.forms import ProfileForm
from opennutrilab.meals.models import Profile
from opennutrilab.meals.services.energy import EQUATIONS
from opennutrilab.meals.services.energy import KJ_PER_KCAL
from opennutrilab.meals.services.needs import Kind
from opennutrilab.meals.services.needs import Needs
from opennutrilab.meals.services.needs import daily_needs
from opennutrilab.meals.services.needs import references
from opennutrilab.products.models import Nutrient
from opennutrilab.products.pnns import pnns_group_names

if TYPE_CHECKING:
    from opennutrilab.users.models import User

# The order the groups of the catalogue are shown in.
GROUPS = [
    Nutrient.Group.ENERGY,
    Nutrient.Group.MACRONUTRIENT,
    Nutrient.Group.VITAMIN,
    Nutrient.Group.MINERAL,
    Nutrient.Group.OTHER,
]


class NeedsView(LoginRequiredMixin, View):
    """The user's profile, and the needs for a day it gives."""

    template_name = "meals/needs.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        profile = _profile_of(request)
        return self._render(request, ProfileForm(instance=profile), profile)

    def post(self, request: HttpRequest) -> HttpResponse:
        profile = _profile_of(request)
        form = ProfileForm(request.POST, instance=profile)
        if not form.is_valid():
            return self._render(request, form, profile)
        saved = cast("Profile", form.save(commit=False))
        saved.user = cast("User", request.user)
        saved.save()
        messages.success(request, _("Your profile was saved."))
        return redirect("nutrition_needs")

    def _render(
        self, request: HttpRequest, form: ProfileForm, profile: Profile | None
    ) -> HttpResponse:
        context: dict[str, Any] = {"form": form, "needs": None}
        if profile is not None:
            needs = daily_needs(profile)
            context |= {
                "needs": needs,
                "energy_kj": needs.energy * KJ_PER_KCAL,
                "metabolisms": [
                    (EQUATIONS[name], kcal)
                    for name, kcal in needs.basal_metabolisms.items()
                ],
                "groups": need_rows(needs),
                "ratios": ratio_rows(needs),
                "sources": references()["sources"],
            }
        return render(request, self.template_name, context)


def _profile_of(request: HttpRequest) -> Profile | None:
    return Profile.objects.filter(user=cast("User", request.user)).first()


def need_rows(needs: Needs) -> list[dict[str, Any]]:
    """The needs as the page's table shows them, by group of the catalogue."""
    catalogue = Nutrient.objects.in_bulk(
        {code for need in needs.nutrients for code in need.nutrients}
    )
    kinds = _labels(Kind.choices)
    by_group: dict[str, list[dict[str, Any]]] = {str(group): [] for group in GROUPS}
    for need in needs.nutrients:
        first = catalogue[need.nutrients[0]]
        share = need.energy_share
        by_group[first.group].append(
            {
                "name": " + ".join(catalogue[code].name for code in need.nutrients),
                "low": need.low,
                "high": need.high,
                "unit": first.unit,
                "share_low": None if share is None else share.low,
                "share_high": None if share is None else share.high,
                # What each end is, and where it comes from.
                "ends": [
                    f"{kinds[kind]} ({source})"
                    for kind, source in dict.fromkeys(
                        (
                            (need.low_kind, need.low_source),
                            (need.high_kind, need.high_source),
                        )
                    )
                    if kind
                ],
            }
        )
    labels = _labels(Nutrient.Group.choices)
    return [
        {"label": labels[group], "rows": rows}
        for group, rows in by_group.items()
        if rows
    ]


def ratio_rows(needs: Needs) -> list[dict[str, Any]]:
    catalogue = Nutrient.objects.in_bulk(
        {
            code
            for ratio in needs.ratios
            for code in (*ratio.numerator, *ratio.denominator)
        }
    )
    kinds = _labels(Kind.choices)

    def side(terms: dict[str, Decimal]) -> str:
        return " + ".join(catalogue[code].name for code in terms)

    return [
        {
            "numerator": side(ratio.numerator),
            "denominator": side(ratio.denominator),
            # Weighted when the ratio is in moles (sodium over potassium).
            "molar": any(f != 1 for f in ratio.numerator.values()),
            "low": ratio.low,
            "high": ratio.high,
            "kind": kinds.get(ratio.kind, ""),
            "source": ratio.source,
        }
        for ratio in needs.ratios
    ]


def _labels(choices: Sequence[tuple[Any, Any]]) -> dict[str, str]:
    return {str(value): str(label) for value, label in choices}


class MealsView(LoginRequiredMixin, View):
    """The meals of a day. Rendered by React (frontend/src/apps/meals)."""

    template_name = "meals/meals.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        # Everything the React page needs from the server, handed over as one
        # |json_script blob. csrfToken cannot be read from the cookie:
        # CSRF_COOKIE_HTTPONLY is on. The labels are translated here, so that the
        # .po catalogue stays the single source of truth.
        props = {
            "csrfToken": get_token(request),
            "languageCode": get_language(),
            "today": timezone.localdate().isoformat(),
            "needsUrl": reverse("nutrition_needs"),
            "inventoryUrl": reverse("list_products"),
            "labels": meals_labels(),
            "groupNames": pnns_group_names(),
        }
        return render(request, self.template_name, {"meals_props": props})


def meals_labels() -> dict[str, str]:
    return {
        "loading": _("Loading…"),
        "loadError": _("The meals could not be loaded."),
        "saveError": _("The change could not be saved."),
        "previousDay": _("Previous day"),
        "nextDay": _("Next day"),
        "day": _("Day"),
        "today": _("Today"),
        "emptyInventory": _(
            "Your inventory has no product to put in a meal: add some to it first."
        ),
        "goInventory": _("Go to the inventory"),
        "serving": _("serving"),
        "quantity": _("Quantity"),
        "unit": _("Unit"),
        "noMass": _("no serving"),
        "remove": _("Take out of the meal"),
        "addProduct": _("Add a product"),
        "chooseProduct": _("Choose a product…"),
        "add": _("Add"),
        "emptyMeal": _("Nothing in this meal yet."),
        "emptyMealEaten": _("Nothing eaten at this meal."),
        "eaten": _("Eaten"),
        "toAdd": _("To add"),
        "eatenHelp": _(
            "Mark the meals you have eaten: a proposed day counts what they brought, "
            "keeps them as they are, and only adds what the rest of the day needs."
        ),
        "noProfile": _("Fill in your profile to set the day against your needs."),
        "myNeeds": _("My needs"),
        "emptyDay": _("Put products in a meal to see what the day brings."),
        "dayTitle": _("The day against your needs"),
        "coverageNote": _(
            "Coverage: the share of the food whose composition gives a value. "
            "What is not covered counts as nothing, so a total is what is at "
            "least there, and the range after it is what it can be."
        ),
        "nutrient": _("Nutrient"),
        "total": _("Total"),
        "need": _("Need"),
        "status": _("Status"),
        "coverage": _("Coverage"),
        "ratios": _("Ratios"),
        "ratio": _("Ratio"),
        "inMoles": _("in moles"),
        "below": _("Below"),
        "within": _("Met"),
        "above": _("Above"),
        "unknown": _("Unknown"),
        "uncertain": _(
            "Not certain: the range of the total, or what the food does not "
            "cover, could change it."
        ),
        "proposeDay": _("Propose a day"),
        "proposing": _("Looking for the best day…"),
        "proposeError": _("No day could be proposed."),
        "proposeNeedsProfile": _("Fill in your profile to propose a day."),
        "proposalTitle": _("Proposed day"),
        "closeProposal": _("Close"),
        "proposal_optimal": _("The best day your inventory allows."),
        "proposal_time_limit": _("The time ran out: this is the best day found."),
        "proposal_failed": _("No day could be worked out."),
        "proposal_no_candidates": _(
            "No product of your inventory has a composition to count."
        ),
        "proposal_nothing_to_fill": _(
            "Every meal of the day is eaten: there is nothing to add."
        ),
        "proposal_nothing_to_add": _(
            "Nothing to add: the meals eaten bring what the day needs, as far as "
            "your inventory goes."
        ),
        "skipped": _("Left aside, with no energy value:"),
        "useDay": _("Use this day"),
        "confirmReplace": _("Replace what is in the meals not yet eaten?"),
        "limitsTitle": _("Limits for the proposed day"),
        "limitsHelp": _(
            "Switch a product off to leave it out of the proposed day, and choose "
            "the meals it may be in and the most of it a day. With every meal "
            "ticked and no most, a product has no limit. Changes are saved as you "
            "make them."
        ),
        "limitsUse": _("Use in the proposed day"),
        "limitsUseAll": _("All products"),
        # %(used)s and %(total)s are put in client-side.
        "limitsInUse": _("%(used)s of %(total)s in use"),
        "limitsKeepOneMeal": _(
            "A product needs a meal: use the switch to leave it out."
        ),
        "limitsSaving": _("Saving…"),
        "uncategorised": _("Uncategorised"),
        "dateHint": _("mm/dd/yyyy"),
        "chooseDay": _("Choose a day in a calendar"),
        "limitsMeals": _("Meals"),
        "limitsMost": _("Most a day"),
        "product": _("Product"),
        "saved": _("Saved"),
        "suggestFoods": _("Suggest foods"),
        "suggesting": _("Looking for foods…"),
        "suggestError": _("No food could be suggested."),
        "suggestionsTitle": _("Foods to get"),
        # %(before)s, %(after)s and %(total)s are put in client-side.
        "suggestion_optimal": _(
            "With these foods, %(after)s of the %(total)s needs and ratios are not "
            "met, against %(before)s without them."
        ),
        "suggestion_time_limit": _(
            "The time ran out: with the best foods found, %(after)s of the "
            "%(total)s needs and ratios are not met, against %(before)s without."
        ),
        "suggestion_failed": _("No day could be worked out."),
        "suggestion_no_gaps": _(
            "Your inventory misses nothing: there is nothing to suggest."
        ),
        "suggestion_no_foods": _(
            "No food of the table would close what your inventory misses."
        ),
        "suggestion_no_suggestion": _(
            "No food is worth getting for what your inventory misses."
        ),
        "suggestion_nothing_to_fill": _(
            "Every meal of the day is eaten: there is nothing to suggest."
        ),
        "suggestionCaution": _(
            "A suggestion is worked out from composition alone. It takes no account "
            "of contaminants (mercury in some fish), of too much of one thing "
            "(vitamin A in liver), of cooking or of taste: check it before acting on "
            "it. It is a kind of food: the product that is that food is for you to "
            "find."
        ),
        "suggestedDay": _("See the day with these foods"),
        "suggestedFood": _("suggested"),
        "view": _("Display"),
        "viewGauges": _("Gauges"),
        "viewTable": _("Table"),
        "legendZone": _("Expected"),
        "legendRange": _("Range the value can be in"),
        "legendUncertain": _("Not certain"),
        "legendOpen": _("Dashed: no upper end is known."),
        "legendEaten": _("Darker: already eaten"),
        "ofWhichEaten": _("of which eaten"),
        "shareOfMinimum": _("Share of the minimum"),
        "shareOfLimit": _("Share of the limit"),
        "totalQuantity": _("Total quantity"),
        # %(percent)s and %(package)s are put in client-side.
        "packageShare": _("%(percent)s of a package of %(package)s"),
        # %(reached)s and %(total)s are put in client-side.
        "groupReached": _("%(reached)s of %(total)s met"),
        "collapseAll": _("Fold all"),
        "expandAll": _("Unfold all"),
        "limitsWhole": _("Use the whole package"),
        "limitsWholeHelp": _(
            "The day proposed uses all of the package, even if that goes over a need."
        ),
        "limitsWholeNeedsPackage": _("Give the product's total quantity first."),
        "coversNeed": _("covers the need"),
        # %(percent)s is put in client-side, with its percent sign.
        "ofNeed": _("%(percent)s of the need"),
    }
