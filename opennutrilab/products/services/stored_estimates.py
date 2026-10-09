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
reference for the product (see ProductNutrient).
"""

import logging
from collections.abc import Iterable
from decimal import Decimal
from typing import NamedTuple

from django.db import transaction
from django.utils import timezone

from opennutrilab.products.models import EstimatedNutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductEstimate
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.services.estimate_validation import validate_estimate
from opennutrilab.products.services.reference_composition import rounding_margin

logger = logging.getLogger(__name__)


class Amount(NamedTuple):
    """One nutrient of a product's composition, per 100 g, in the nutrient's unit."""

    amount: Decimal
    low: Decimal
    # None when no upper end is known.
    high: Decimal | None
    # The share of the product, in percent, that the figure covers: all of it for
    # a declared figure.
    coverage: Decimal
    # Whether the label declares it.
    declared: bool


def kept_estimates(
    products: Iterable[Product],
) -> dict[str, dict[str, EstimatedNutrient]]:
    """
    The kept estimate of each product, by barcode and nutrient code, worked out
    again where it is stale or was never worked out.
    """
    products = list(products)
    kept = {
        estimate.product_id: estimate
        for estimate in ProductEstimate.objects.filter(
            product__in=products
        ).prefetch_related("nutrients")
    }
    found: dict[str, dict[str, EstimatedNutrient]] = {}
    for product in products:
        estimate = kept.get(product.pk)
        if estimate is None or estimate.stale:
            estimate = work_out(product)
        found[product.pk] = {row.nutrient_id: row for row in estimate.nutrients.all()}
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
    else:
        nutrients = validated.nutrients
        confidence = validated.confidence
    with transaction.atomic():
        estimate, _created = ProductEstimate.objects.update_or_create(
            product=product,
            defaults={"worked_out_at": timezone.now(), "stale": False},
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


def mark_stale(barcode: str | None = None) -> None:
    """Mark the kept estimate of a product stale, or every one with no barcode."""
    kept = ProductEstimate.objects.filter(stale=False)
    if barcode is not None:
        kept = kept.filter(product_id=barcode)
    kept.update(stale=True)


def compositions(products: Iterable[Product]) -> dict[str, dict[str, Amount]]:
    """The composition of each product, by barcode and nutrient code (see module)."""
    products = list(products)
    composition: dict[str, dict[str, Amount]] = {
        barcode: {
            code: Amount(
                amount=row.amount,
                low=row.low,
                high=row.high,
                coverage=row.coverage_point,
                declared=False,
            )
            for code, row in rows.items()
        }
        for barcode, rows in kept_estimates(products).items()
    }
    for barcode, code, amount in ProductNutrient.objects.filter(
        product__in=products
    ).values_list("product_id", "nutrient_id", "amount"):
        margin = rounding_margin(amount)
        composition[barcode][code] = Amount(
            amount=amount,
            low=max(Decimal(0), amount - margin),
            high=amount + margin,
            coverage=Decimal(100),
            declared=True,
        )
    return composition
