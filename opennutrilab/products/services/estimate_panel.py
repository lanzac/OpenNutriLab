"""
What the gauges of a product's estimate are drawn from.

The estimate itself is `estimate_report.build_estimate`; this puts it as the page
needs it to draw (frontend/src/apps/products/estimate): the ingredients as one list
in the order of the label, each with its depth, and each nutrient with the group it
belongs to and the verdict of the label's figure against it. Nothing is worked out
here: every figure is the estimate's, and the page only draws it.
"""

from collections.abc import Iterator
from collections.abc import Sequence
from typing import Any

from opennutrilab.products.api.schemas.outbound import EstimateOut
from opennutrilab.products.api.schemas.outbound import IngredientEstimateOut
from opennutrilab.products.api.schemas.outbound import NutrientEstimateOut
from opennutrilab.products.api.schemas.outbound import RangeOut
from opennutrilab.products.models import Nutrient


def walk_ingredients(
    ingredients: Sequence[IngredientEstimateOut],
) -> Iterator[tuple[int, IngredientEstimateOut]]:
    """The ingredients tree as (depth, ingredient) in the order of the label."""

    def visit(
        level: Sequence[IngredientEstimateOut], depth: int
    ) -> Iterator[tuple[int, IngredientEstimateOut]]:
        for ingredient in level:
            yield depth, ingredient
            yield from visit(ingredient.sub_ingredients, depth + 1)

    return visit(ingredients, 0)


def ingredient_name(ingredient: IngredientEstimateOut) -> str:
    """What the ingredient is: a food, a preparation, an additive or a nutrient."""
    for found in (
        ingredient.reference,
        ingredient.preparation,
        ingredient.additive,
        ingredient.nutrient,
    ):
        if found is not None:
            return found.name
    return ""


def _range(found: RangeOut | None) -> dict[str, Any] | None:
    return None if found is None else found.model_dump(mode="json")


def _nutrient(
    found: NutrientEstimateOut, groups: dict[str, Nutrient]
) -> dict[str, Any]:
    nutrient = groups.get(found.code)
    group = Nutrient.Group.OTHER if nutrient is None else nutrient.group
    return {
        "code": found.code,
        "name": found.name,
        "unit": found.unit,
        "group": str(group),
        "group_label": str(Nutrient.Group(group).label),
        "estimated": _range(found.estimated),
        # The label's figure agrees with the ingredients, and narrows the estimate.
        "narrowed": found.narrowed,
        "coverage": None if found.coverage is None else str(found.coverage.point),
        "confidence": (
            None
            if found.confidence is None
            else found.confidence.model_dump(mode="json")
        ),
        "declared": (
            None if found.declared is None else found.declared.model_dump(mode="json")
        ),
        # What the label's figure says of the estimate, and whether it could say
        # anything: a figure the estimate was worked out with confirms nothing.
        "verdict": None if found.check is None else found.check.verdict,
        "constrained": found.check is not None and found.check.constrained,
        # It agrees within the tolerance the Commission allows, not the rounding.
        "tolerated": found.check is not None and found.check.tolerated,
    }


def estimate_panel(estimate: EstimateOut) -> dict[str, Any]:
    """The estimate as the gauges are drawn from it, ready to be sent as JSON."""
    groups = {
        nutrient.code: nutrient
        for nutrient in Nutrient.objects.filter(
            code__in=[found.code for found in estimate.nutrients]
        )
    }
    return {
        # What the label's table is given per 100 of ("g" or "ml"), and what a
        # millilitre weighs when it is known: the page converts between the two, so
        # that the estimate (per 100 g) and the label (as printed) can be shown in
        # either, and the label is never changed.
        "label_unit": estimate.label_unit,
        "density": _range(estimate.density),
        "ingredients": [
            {
                "name": ingredient_name(ingredient),
                "depth": depth,
                "declared": (
                    None if ingredient.declared is None else str(ingredient.declared)
                ),
                "estimated": _range(ingredient.estimated),
                # What an ingredient that is a nutrient adds, per 100 g, and its unit.
                "added": _range(ingredient.added),
                "added_unit": (
                    None if ingredient.nutrient is None else ingredient.nutrient.unit
                ),
            }
            for depth, ingredient in walk_ingredients(estimate.ingredients)
        ],
        "nutrients": [_nutrient(found, groups) for found in estimate.nutrients],
    }
