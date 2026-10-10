"""
A product's estimate, kept, and a product's composition as meals count it.

Working a product's estimate out takes about a second (estimate_validation), which
a page that reads a whole inventory cannot spend on each product. So the estimate
is kept (ProductEstimate) and read back, and worked out again by the next reading
once it is stale: a change to a product's ingredients or label marks its own
estimate, and a change to anything a composition is made of (a reference, a
preparation, an additive, a source food and its values, the catalogue) marks them
all, since finding the products it touches would take as long as working them out
again (see signals). The `refresh_estimates` command works out the stale ones at
once.

A product's composition is what its label declares, where it declares it, with the
rounding it is written with, and its estimate for the rest: the label is the
reference for the product (see ProductNutrient). What the label's figure gives of
another nutrient by a one-term derivation (the sodium of its salt) is the label's
too, so that a composition does not hold a salt and a sodium that disagree.

A composition is per 100 g, as the estimate is. A label given per 100 ml (Product.
nutrition_unit) is kept as it is printed, and is turned into one per 100 g with the
density of the product, which the kept estimate holds (Product.density): 91 g of fat
per 100 ml of an oil of 0.91 g/ml is 100 g per 100 g. With no density known it is
used as it is, as per 100 g, which is what a millilitre counting as a gram makes of it
(see Product.grams_of).
"""

import logging
from collections.abc import Iterable
from collections.abc import Mapping
from decimal import ROUND_CEILING
from decimal import ROUND_FLOOR
from decimal import Decimal
from typing import NamedTuple

from django.db import transaction
from django.utils import timezone

from opennutrilab.products.models import EstimatedNutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductEstimate
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.services.derived_nutrients import DERIVATIONS
from opennutrilab.products.services.estimate_validation import validate_estimate
from opennutrilab.products.services.reference_composition import rounding_margin

logger = logging.getLogger(__name__)

# The figures of a label turned into another unit are given to this many places.
_FIGURE = Decimal("0.000001")


class Amount(NamedTuple):
    """One nutrient of a product's composition, per 100 g, in the nutrient's unit."""

    amount: Decimal
    low: Decimal
    # None when no upper end is known.
    high: Decimal | None
    # The share of the product, in percent, that the figure covers: all of it for
    # a declared figure.
    coverage: Decimal
    # Whether it comes from the label: declared there, or what the label's own
    # figure gives (see _worked_back).
    declared: bool


def kept_estimates(
    products: Iterable[Product],
) -> dict[str, dict[str, EstimatedNutrient]]:
    """
    The kept estimate of each product, by barcode and nutrient code, worked out
    again where it is stale or was never worked out.
    """
    return {
        barcode: {row.nutrient_id: row for row in estimate.nutrients.all()}
        for barcode, estimate in _worked_out(list(products)).items()
    }


def _worked_out(products: list[Product]) -> dict[str, ProductEstimate]:
    """The kept estimate of each product, worked out again where it has to be."""
    kept = {
        estimate.product_id: estimate
        for estimate in ProductEstimate.objects.filter(
            product__in=products
        ).prefetch_related("nutrients")
    }
    found: dict[str, ProductEstimate] = {}
    for product in products:
        estimate = kept.get(product.pk)
        if estimate is None or estimate.stale:
            estimate = work_out(product)
        found[product.pk] = estimate
    return found


def work_out(product: Product) -> ProductEstimate:
    """
    Work the estimate of a product out and keep it, in place of the one kept.

    One the solver fails on is kept with no nutrient, and logged: it is worked out
    again when something it is made of changes.
    """
    try:
        validated = validate_estimate(product)
    except RuntimeError:
        logger.exception(
            "The estimate of product %s could not be worked out", product.pk
        )
        nutrients = {}
        confidence = {}
        density = None
    else:
        nutrients = validated.nutrients
        confidence = validated.confidence
        density = validated.density
    with transaction.atomic():
        estimate, _created = ProductEstimate.objects.update_or_create(
            product=product,
            defaults={
                "worked_out_at": timezone.now(),
                "stale": False,
                "density_low": None if density is None else density[0],
                "density_high": None if density is None else density[1],
            },
        )
        estimate.nutrients.all().delete()
        EstimatedNutrient.objects.bulk_create(
            EstimatedNutrient(
                estimate=estimate,
                nutrient_id=code,
                amount=found.amount,
                low=found.low,
                high=found.high,
                coverage_low=found.coverage.low,
                coverage_point=found.coverage.point,
                coverage_high=found.coverage.high,
                confidence=None if code not in confidence else confidence[code].score,
            )
            for code, found in nutrients.items()
        )
    # Read back, so that what is returned is what a reading finds.
    return ProductEstimate.objects.prefetch_related("nutrients").get(pk=estimate.pk)


def _declared(amount: Decimal) -> Amount:
    """A figure of the label, within the rounding it is written with."""
    margin = rounding_margin(amount)
    return Amount(
        amount=amount,
        low=max(Decimal(0), amount - margin),
        high=amount + margin,
        coverage=Decimal(100),
        declared=True,
    )


def _worked_back(declared: Mapping[str, Amount]) -> dict[str, Amount]:
    """
    What the label declares of a nutrient it does not, when a derivation that has
    one term says it: it declares salt, and salt is sodium times 0.0025, so it
    declares the sodium that goes with it, however far an estimate from the
    ingredients lies from it. The rounding of the figure carries over.
    """
    found: dict[str, Amount] = {}
    for derived, terms in DERIVATIONS.items():
        if len(terms) != 1 or derived not in declared:
            continue
        term = terms[0]
        if term.component in declared:
            continue
        figure = declared[derived]
        found[term.component] = Amount(
            amount=figure.amount / term.factor,
            low=figure.low / term.factor,
            high=None if figure.high is None else figure.high / term.factor,
            coverage=figure.coverage,
            declared=True,
        )
    return found


def mark_stale(barcode: str | None = None) -> None:
    """Mark the kept estimate of a product stale, or every one with no barcode."""
    kept = ProductEstimate.objects.filter(stale=False)
    if barcode is not None:
        kept = kept.filter(product_id=barcode)
    kept.update(stale=True)


def _declared_per_mass(amount: Decimal, density: tuple[Decimal, Decimal]) -> Amount:
    """
    A figure of a label given per 100 ml as it is per 100 g: the amount over the
    middle of the density, its lowest end over the heaviest millilitre, its highest
    over the lightest, so that the range is never narrower than the truth.
    """
    declared = _declared(amount)
    least, most = density
    return Amount(
        amount=(amount / ((least + most) / 2)).quantize(_FIGURE),
        low=(declared.low / most).quantize(_FIGURE, ROUND_FLOOR),
        high=(
            None
            if declared.high is None
            else (declared.high / least).quantize(_FIGURE, ROUND_CEILING)
        ),
        coverage=declared.coverage,
        declared=True,
    )


def compositions(products: Iterable[Product]) -> dict[str, dict[str, Amount]]:
    """
    The composition of each product, by barcode and nutrient code, per 100 g (see
    module). It sets `density` on each product from the estimate it has just read.
    """
    products = list(products)
    by_barcode = {product.pk: product for product in products}
    worked_out = _worked_out(products)
    for barcode, estimate in worked_out.items():
        # What a cached property is: the value is read once, and it is this one.
        vars(by_barcode[barcode])["density"] = (
            None
            if estimate.density_low is None or estimate.density_high is None
            else (estimate.density_low, estimate.density_high)
        )
    composition: dict[str, dict[str, Amount]] = {
        barcode: {
            row.nutrient_id: Amount(
                amount=row.amount,
                low=row.low,
                high=row.high,
                coverage=row.coverage_point,
                declared=False,
            )
            for row in estimate.nutrients.all()
        }
        for barcode, estimate in worked_out.items()
    }
    label: dict[str, dict[str, Amount]] = {barcode: {} for barcode in composition}
    for barcode, code, amount in ProductNutrient.objects.filter(
        product__in=products
    ).values_list("product_id", "nutrient_id", "amount"):
        product = by_barcode[barcode]
        per_millilitre = product.nutrition_unit == Product.ServingUnit.MILLILITRE.value
        label[barcode][code] = (
            _declared_per_mass(amount, product.density)
            if per_millilitre and product.density is not None
            else _declared(amount)
        )
    for barcode, declared in label.items():
        declared.update(_worked_back(declared))
        composition[barcode].update(declared)
    return composition
