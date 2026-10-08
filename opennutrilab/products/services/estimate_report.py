"""
The estimate of a product as it is served: the API's answer, and what the product
page shows.

It puts together what estimate_validation works out (the nutrients, the shares of
the ingredients, the check against the label, the confidence, the warnings) with
what a reader needs to make sense of it: the names in the language served, the
ingredients as a tree in the label's order, and the sources the figures come from
with the attribution their licences require.

A nutrient read more than one way (vitamin A, see estimate_validation.CONVENTIONS)
is one entry, with the other readings in it: the second reading is a way to read
the same nutrient, not another nutrient.
"""

from collections import defaultdict
from collections.abc import Mapping

from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from opennutrilab.products.api.schemas.outbound import AdditiveOut
from opennutrilab.products.api.schemas.outbound import CheckOut
from opennutrilab.products.api.schemas.outbound import ConfidenceOut
from opennutrilab.products.api.schemas.outbound import DeclaredOut
from opennutrilab.products.api.schemas.outbound import EstimateOut
from opennutrilab.products.api.schemas.outbound import IngredientEstimateOut
from opennutrilab.products.api.schemas.outbound import NutrientEstimateOut
from opennutrilab.products.api.schemas.outbound import PreparationOut
from opennutrilab.products.api.schemas.outbound import RangeOut
from opennutrilab.products.api.schemas.outbound import ReadingOut
from opennutrilab.products.api.schemas.outbound import ReferenceOut
from opennutrilab.products.api.schemas.outbound import SourceOut
from opennutrilab.products.api.schemas.outbound import WarningOut
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import Source
from opennutrilab.products.services.estimate_validation import CONVENTIONS
from opennutrilab.products.services.estimate_validation import ValidatedEstimate
from opennutrilab.products.services.estimate_validation import validate_estimate
from opennutrilab.products.services.nutrient_estimation import NutrientAmount
from opennutrilab.products.services.percentage_estimation import Interval
from opennutrilab.products.services.percentage_estimation import PercentageEstimate

# The processing a food goes through is out of the estimate's reach (see
# percentage_estimation), and the reader has to be told.
CAVEAT = _(
    "Cooking, drying and other processing are not modelled: the percentages are "
    "those of the ingredients as used and the nutrition is that of the product as "
    "sold, so what a product loses in the making (water, vitamins) is not counted. "
    "Every figure is an estimate."
)


def build_estimate(product: Product) -> EstimateOut:
    """The estimate of a stored product, ready to be served."""
    validated = validate_estimate(product)
    return EstimateOut(
        barcode=product.barcode,
        used_nutrition=validated.percentages.used_nutrition,
        warnings=[
            WarningOut(
                problem=warning.problem.value,
                message=warning.message(),
                nutrients=list(warning.codes),
            )
            for warning in validated.warnings
        ],
        nutrients=_nutrients(validated),
        ingredients=_ingredients(product, validated.percentages),
        sources=_sources(product),
        caveat=str(CAVEAT),
    )


def _nutrients(validated: ValidatedEstimate) -> list[NutrientEstimateOut]:
    """One entry for each nutrient estimated or declared, in catalogue order."""
    readings = {code for others in CONVENTIONS.values() for code in others}
    shown = (validated.nutrients.keys() | validated.checks.keys()) - readings
    catalogue = Nutrient.objects.in_bulk(validated.nutrients.keys() | shown)
    return [
        _nutrient(catalogue[code], validated, catalogue)
        for code in sorted(shown, key=lambda c: (catalogue[c].display_order, c))
    ]


def _nutrient(
    nutrient: Nutrient, validated: ValidatedEstimate, catalogue: Mapping[str, Nutrient]
) -> NutrientEstimateOut:
    code = nutrient.code
    estimated = validated.nutrients.get(code)
    confidence = validated.confidence.get(code)
    check = validated.checks.get(code)
    return NutrientEstimateOut(
        code=code,
        name=nutrient.name,
        unit=nutrient.unit,
        estimated=None if estimated is None else _amount(estimated),
        coverage=None if estimated is None else _range(estimated.coverage),
        confidence=(
            None
            if confidence is None
            else ConfidenceOut(
                score=confidence.score,
                coverage=confidence.coverage,
                quality=confidence.quality,
                uncertainty=confidence.uncertainty,
                agreement=confidence.agreement,
            )
        ),
        declared=(
            None
            if check is None
            else DeclaredOut(
                amount=check.declared,
                low=check.declared_range[0],
                high=check.declared_range[1],
            )
        ),
        check=(
            None
            if check is None
            else CheckOut(
                verdict=check.verdict.value,
                gap=check.gap,
                constrained=check.constrained,
                compared_low=None if check.estimated is None else check.estimated[0],
                compared_high=None if check.estimated is None else check.estimated[1],
            )
        ),
        other_readings=[
            ReadingOut(name=catalogue[other].name, estimated=_amount(found))
            for other in CONVENTIONS.get(code, ())
            if (found := validated.nutrients.get(other)) is not None
        ],
    )


def _amount(amount: NutrientAmount) -> RangeOut:
    return RangeOut(low=amount.low, point=amount.amount, high=amount.high)


def _range(interval: Interval) -> RangeOut:
    return RangeOut(low=interval.low, point=interval.point, high=interval.high)


def _ingredients(
    product: Product, percentages: PercentageEstimate
) -> list[IngredientEstimateOut]:
    """The ingredients as the label's tree, with their declared and estimated shares."""
    children: defaultdict[int | None, list[Ingredient]] = defaultdict(list)
    # In the order of the label, which is the order they were created in.
    for ingredient in product.ingredients.select_related(
        "reference", "preparation", "additive"
    ):
        children[ingredient.parent_id].append(ingredient)

    def build(ingredient: Ingredient) -> IngredientEstimateOut:
        share = percentages.percentages.get(ingredient.id)
        return IngredientEstimateOut(
            reference=(
                None
                if ingredient.reference is None
                else ReferenceOut.model_validate(ingredient.reference)
            ),
            preparation=(
                None
                if ingredient.preparation is None
                else PreparationOut.model_validate(ingredient.preparation)
            ),
            additive=(
                None
                if ingredient.additive is None
                else AdditiveOut.model_validate(ingredient.additive)
            ),
            declared=ingredient.percentage,
            estimated=None if share is None else _range(share),
            sub_ingredients=[build(sub) for sub in children[ingredient.id]],
        )

    return [build(root) for root in children[None]]


def _recipes_by_default(product: Product) -> set[int]:
    """
    The preparations of the product that count by what they are made of, and the
    preparations those are made of, however deep (see percentage_estimation): a
    preparation with no source food whose label lists no parts.

    A nested preparation is taken whether or not it has foods of its own, which is
    more than is used and never less.
    """
    reached = set(
        Ingredient.objects.filter(
            product=product,
            preparation__isnull=False,
            preparation__source_foods__isnull=True,
            sub_ingredients__isnull=True,
        ).values_list("preparation", flat=True)
    )
    frontier = set(reached)
    while frontier:
        frontier = set(
            Preparation.objects.filter(used_in_preparations__in=frontier).values_list(
                "pk", flat=True
            )
        )
        frontier -= reached
        reached |= frontier
    return reached


def _sources(product: Product) -> list[SourceOut]:
    """
    The sources of the foods the product's references, preparations and additives
    draw on, and of those of what a preparation is made of when it counts by that
    (see _recipes_by_default).
    """
    by_default = _recipes_by_default(product)
    return [
        SourceOut(
            code=source.code,
            name=source.name,
            version=source.version,
            url=source.url,
            attribution=source.attribution,
        )
        for source in Source.objects.filter(
            Q(foods__reference_ingredients__usages__product=product)
            | Q(foods__preparations__usages__product=product)
            | Q(foods__additives__usages__product=product)
            | Q(foods__reference_ingredients__used_in_preparations__in=by_default)
            | Q(foods__preparations__in=by_default)
        )
        .distinct()
        .order_by("code")
    ]
