from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
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
