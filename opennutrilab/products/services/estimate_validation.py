"""
What an estimate says against the label, and how far to trust it.

**Validation.** The values a label declares are the reference, so each nutrient
the product declares is set against what its ingredients give. A declared figure
is an interval, its rounding (33 is 32.5 to 33.5, see rounding_margin) with the
tolerance the European Commission allows around it (see label_tolerance), and so
is the estimate. They agree when the two meet. Otherwise the label declares less than
its ingredients bring at the least, or more than they can bring at the most, and
a warning says so. Nothing is blocked or corrected: what is off may be the label,
a composition or the order of the ingredients, and the check does not say which.

Two things keep this from being as plain as it sounds:

- The label is also one of the things the shares are worked out from: the figures
  for fat, saturated fat, carbohydrates, sugars, fibre, proteins and salt are
  rules of percentage_estimation. When they were used, they agree with the
  estimate by construction, and the check says so (`constrained`) rather than
  count it as a confirmation. What tests them is whether the shares could be
  worked out with them at all, and when not, the warning of percentage_estimation
  names the nutrients that were off. The figures that were not used, energy above
  all (a label computes it from the others), are the independent checks.
- A nutrient that only some of the ingredients give has a figure to meet only
  from below: the amount counts what is missing as nothing, and there is no
  highest end (see nutrient_estimation). Such a check can fail, and cannot
  confirm much, so it does not count as an agreement for the confidence.

A nutrient whose figure on a label follows a convention the law does not fix is
compared with what all the conventions give together (CONVENTIONS).

A label given per 100 ml (a liquid) is kept as it is printed, and the estimate,
which is per 100 g, is set against it per 100 ml through the density of the product
(see percentage_estimation.product_density). With no density known there is no
check: the two are not the same quantity.

**Confidence.** The estimate of each nutrient comes with the parts it is built
from, each between 0 and 1 and 1 being nothing to doubt, and a score that is
their product, so that one part that fails drags the whole down, and it can be
worked out from what is shown:

- coverage: the share of the product whose ingredients give a value for the
  nutrient (the point of nutrient_estimation's coverage);
- quality: the grade of what they give, as the mean over those ingredients,
  weighted by their share, of their foods' grades on the scale that weights the
  foods in reference_composition (A 1, B 0.75, C 0.5, D 0.25, no grade 0.25);
- uncertainty: how well the recipe is known, the part of the product that could be
  one ingredient or another: half of the sum of the widths of the shares of the
  ingredients that carry the composition. It counts against the score (1 - x);
- agreement: the share of the independent checks, those that could have failed,
  that agree. A nutrient the label named as one that cannot be given (see
  percentage_estimation) counts as failed. None when there is no such check, and
  the score then takes it for 1: nothing contradicts the estimate, which is not
  that it was confirmed.

Coverage and quality are those of each nutrient, uncertainty and agreement those
of the product. The score is a guide to compare estimates, and has no meaning of
its own: the parts are what to read.
"""

from collections.abc import Collection
from collections.abc import Mapping
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN
from decimal import Decimal
from typing import NamedTuple

from django.db.models import TextChoices
from django.utils.formats import number_format

from opennutrilab.products.models import Product
from opennutrilab.products.services.derived_nutrients import sums_in
from opennutrilab.products.services.label_tolerance import label_reading
from opennutrilab.products.services.nutrient_estimation import NutrientAmount
from opennutrilab.products.services.nutrient_estimation import nutrients_of
from opennutrilab.products.services.percentage_estimation import NUTRIENTS
from opennutrilab.products.services.percentage_estimation import EstimateWarning
from opennutrilab.products.services.percentage_estimation import PercentageEstimate
from opennutrilab.products.services.percentage_estimation import Problem
from opennutrilab.products.services.percentage_estimation import Solution
from opennutrilab.products.services.percentage_estimation import load
from opennutrilab.products.services.percentage_estimation import percentages_of
from opennutrilab.products.services.percentage_estimation import solve_shares
from opennutrilab.products.services.reference_composition import GRADE_WEIGHTS
from opennutrilab.products.services.reference_composition import NO_GRADE_WEIGHT
from opennutrilab.products.services.reference_composition import Estimate

# Vitamin A on a label: the regulation gives it in µg with no conversion, so the
# amount of beta-carotene that counts for a µg of retinol is not known (CIQUAL's
# is 12, the EU scientific convention 6). A nutrient maps to the others that are
# the same thing read another way; all are worked out from the same shares.
CONVENTIONS: dict[str, tuple[str, ...]] = {"vitamin_a": ("vitamin_a_sixth",)}

# The scores and the shares are given with two decimals.
_DIGITS = Decimal("0.01")
_TOP_GRADE_WEIGHT = max(GRADE_WEIGHTS.values())


class Verdict(TextChoices):
    AGREES = "agrees"
    # The label declares less than the ingredients bring at the least.
    DECLARED_BELOW = "declared_below"
    # The label declares more than the ingredients can bring at the most.
    DECLARED_ABOVE = "declared_above"
    # No ingredient gives the nutrient: there is nothing to compare.
    NOT_ESTIMATED = "not_estimated"


class Check(NamedTuple):
    """One nutrient the product declares, set against what its ingredients give."""

    nutrient: str
    unit: str
    declared: Decimal
    # The declared figure with the rounding it is written with: (low, high).
    declared_range: tuple[Decimal, Decimal]
    # What the ingredients give: (low, high), with None for no highest end known
    # (a nutrient only some of them give). Several estimates make one when the
    # nutrient has CONVENTIONS. None when no ingredient gives it.
    estimated: tuple[Decimal, Decimal | None] | None
    verdict: Verdict
    # How far apart the two intervals are, in the unit: 0 when they meet.
    gap: Decimal
    # The label's figure was one of the rules the shares were worked out with, so
    # it agrees by construction.
    constrained: bool
    # It agrees only within the tolerance the Commission allows around a figure,
    # not within the rounding alone (see label_tolerance).
    tolerated: bool = False
    # What the figure can stand for with that tolerance: (low, high).
    tolerance_range: tuple[Decimal, Decimal] | None = None

    @property
    def informative(self) -> bool:
        """Whether the check could have failed, and says something if it did not."""
        if self.constrained or self.estimated is None:
            return False
        return self.verdict is not Verdict.AGREES or self.estimated[1] is not None


class Confidence(NamedTuple):
    """How far to trust the estimate of one nutrient. See the module's description."""

    score: Decimal
    coverage: Decimal
    quality: Decimal
    uncertainty: Decimal
    agreement: Decimal | None


class ValidatedEstimate(NamedTuple):
    # By nutrient code, as nutrient_estimation gives them. Empty when the shares
    # are impossible or no ingredient has a composition.
    nutrients: dict[str, NutrientAmount]
    percentages: PercentageEstimate
    # One for each declared nutrient, by code.
    checks: dict[str, Check]
    # One for each estimated nutrient, by code.
    confidence: dict[str, Confidence]
    # All there is to say, non-blocking: the shares' own first (the same as
    # `percentages`), then the declared figures that the ingredients do not give.
    warnings: list[EstimateWarning]
    # What a millilitre of the product weighs, in g/ml, as (low, high), when the
    # density of every ingredient is known (see percentage_estimation).
    density: tuple[Decimal, Decimal] | None = None


def validate_estimate(product: Product) -> ValidatedEstimate:
    """The nutrients of a product, checked against its label, with their confidence."""
    loaded = load(product)
    solution = solve_shares(
        loaded.nodes,
        loaded.label,
        loaded.nutrient_names,
        label_unit=loaded.label_unit,
        tolerated=loaded.label_tolerated,
    )
    sums = sums_in(loaded.units)
    nutrients = nutrients_of(solution, loaded.compositions, loaded.parents, sums)
    declared = dict(product.declared_nutrients.values_list("nutrient_id", "amount"))
    compared = nutrients
    if loaded.label_unit != Product.ServingUnit.GRAM.value:
        # A label per 100 ml is kept as it is printed and set against the estimate
        # as it is per 100 ml. With no density to tell what that is, the two are
        # not the same quantity and there is nothing to say about them.
        if solution.density is None:
            declared = {}
        else:
            compared = _per_volume(nutrients, solution.density)

    checks = compare(
        declared,
        compared,
        loaded.units,
        constrained=NUTRIENTS if solution.used_nutrition else (),
        groups=loaded.groups,
    )
    return ValidatedEstimate(
        nutrients,
        percentages_of(solution),
        checks,
        confidence_of(solution, loaded.compositions, nutrients, checks, sums),
        [*solution.warnings, *mismatches(checks, loaded.nutrient_names, loaded.units)],
        None if solution.density is None else _density_figures(solution.density),
    )


def _density_figures(density: tuple[float, float]) -> tuple[Decimal, Decimal]:
    least, most = (Decimal(str(round(end, 6))) for end in density)
    return least, most


def _per_volume(
    nutrients: Mapping[str, NutrientAmount], density: tuple[float, float]
) -> dict[str, NutrientAmount]:
    """
    The estimate per 100 ml in place of per 100 g: the lowest end with the lightest
    millilitre, the highest with the heaviest, and the point with the middle. The
    interval is wider than the truth, never narrower.
    """
    least, most = _density_figures(density)
    middle = (least + most) / 2
    return {
        code: amount._replace(
            amount=amount.amount * middle,
            low=amount.low * least,
            high=None if amount.high is None else amount.high * most,
        )
        for code, amount in nutrients.items()
    }


def compare(
    declared: Mapping[str, Decimal],
    nutrients: Mapping[str, NutrientAmount],
    units: Mapping[str, str],
    *,
    constrained: Collection[str] = (),
    groups: Mapping[str, str] | None = None,
) -> dict[str, Check]:
    """
    Each declared amount (by nutrient code) set against the estimate. `constrained`
    are the nutrients whose label figure the shares were worked out with, and
    `groups` the group of the catalogue of each nutrient, which tells its tolerance.
    """
    return {
        code: _check(
            code,
            units.get(code, ""),
            amount,
            _estimated(code, nutrients),
            constrained=code in constrained,
            group=(groups or {}).get(code, ""),
        )
        for code, amount in declared.items()
    }


def _estimated(
    code: str, nutrients: Mapping[str, NutrientAmount]
) -> tuple[Decimal, Decimal | None] | None:
    """What the nutrient can be, over all the ways its figure may be read."""
    found = [nutrients[c] for c in (code, *CONVENTIONS.get(code, ())) if c in nutrients]
    if not found:
        return None
    highs = [n.high for n in found if n.high is not None]
    return (
        min(n.low for n in found),
        max(highs) if len(highs) == len(found) else None,
    )


def _check(  # noqa: PLR0913
    code: str,
    unit: str,
    amount: Decimal,
    estimated: tuple[Decimal, Decimal | None] | None,
    *,
    constrained: bool,
    group: str = "",
) -> Check:
    reading = label_reading(code, group, amount)
    low, high = reading.rounded
    widest_low, widest_high = reading.tolerated
    verdict, gap = Verdict.AGREES, Decimal(0)
    if estimated is None:
        verdict = Verdict.NOT_ESTIMATED
    elif estimated[0] > widest_high:
        verdict, gap = Verdict.DECLARED_BELOW, estimated[0] - widest_high
    elif estimated[1] is not None and estimated[1] < widest_low:
        verdict, gap = Verdict.DECLARED_ABOVE, widest_low - estimated[1]
    # Within the tolerance but not within the rounding.
    tolerated = (
        verdict is Verdict.AGREES
        and estimated is not None
        and (estimated[0] > high or (estimated[1] is not None and estimated[1] < low))
    )
    return Check(
        code,
        unit,
        amount,
        (low, high),
        estimated,
        verdict,
        gap,
        constrained,
        tolerated,
        reading.tolerated,
    )


def mismatches(
    checks: Mapping[str, Check],
    names: Mapping[str, str],
    units: Mapping[str, str],
) -> list[EstimateWarning]:
    """A warning for each declared figure the ingredients cannot give."""
    warnings: list[EstimateWarning] = []
    for code, check in checks.items():
        if check.estimated is None or check.verdict not in (
            Verdict.DECLARED_BELOW,
            Verdict.DECLARED_ABOVE,
        ):
            continue
        low, high = check.estimated
        below = check.verdict is Verdict.DECLARED_BELOW
        unit = units.get(code, "")
        # A figure below the estimate is held against its lowest end, and one above
        # against its highest, which is there since the check failed on it.
        end = low if below else high
        assert end is not None
        warnings.append(
            EstimateWarning(
                Problem.DECLARED_BELOW if below else Problem.DECLARED_ABOVE,
                names.get(code, code),
                (code,),
                {
                    "declared": _figure(check.declared, unit),
                    "estimated": _figure(end, unit),
                },
            )
        )
    return warnings


def _figure(value: Decimal, unit: str) -> str:
    return f"{number_format(value.normalize(), use_l10n=True)} {unit}".strip()


def confidence_of(
    solution: Solution,
    compositions: Sequence[Mapping[str, Estimate]],
    nutrients: Mapping[str, NutrientAmount],
    checks: Mapping[str, Check],
    sums: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Confidence]:
    """
    How far to trust each nutrient of an estimate. See the module's description.
    The quality of a sum (`sums` gives the parts of each) is its worst part's.
    """
    if solution.ranges is None or not nutrients:
        return {}
    uncertainty = _uncertainty(solution)
    conflicts = {
        code
        for warning in solution.warnings
        if warning.problem == Problem.LABEL_DISAGREES
        for code in warning.codes
    }
    agreement = _agreement(checks, conflicts)
    confidence: dict[str, Confidence] = {}
    for code, nutrient in nutrients.items():
        coverage = _ratio(nutrient.coverage.point / 100)
        parts = (sums or {}).get(code)
        quality = (
            min(_quality(solution, compositions, part) for part in parts)
            if parts
            else _quality(solution, compositions, code)
        )
        # Worked out from the parts as they are shown, so they give the score.
        score = (
            coverage
            * quality
            * (1 - uncertainty)
            * (Decimal(1) if agreement is None else agreement)
        )
        confidence[code] = Confidence(
            _ratio(score), coverage, quality, uncertainty, agreement
        )
    return confidence


def _quality(
    solution: Solution, compositions: Sequence[Mapping[str, Estimate]], code: str
) -> Decimal:
    """The grade of what the ingredients give of a nutrient, weighted by their share."""
    assert solution.ranges is not None
    shares = solution.ranges[2]
    given = [i for i in solution.units if code in compositions[i]]
    total = sum(shares[i] for i in given)
    if total <= 0:
        return Decimal(0)
    weighted = sum(
        shares[i] * _grade_score(compositions[i][code].grades) for i in given
    )
    return _ratio(weighted / total)


def _grade_score(grades: Sequence[str]) -> float:
    """The mean of the scores of grades, with none counted as the lowest."""
    weights = [GRADE_WEIGHTS.get(grade, NO_GRADE_WEIGHT) for grade in grades]
    if not weights:
        weights = [NO_GRADE_WEIGHT]
    return float(sum(weights) / (_TOP_GRADE_WEIGHT * len(weights)))


def _uncertainty(solution: Solution) -> Decimal:
    """
    Half of the sum of the widths of the shares of the ingredients that carry the
    composition (and of those with none), which is the part of the product that
    could be one ingredient or another: what one gains, another loses.
    """
    assert solution.ranges is not None
    lows, highs, _points = solution.ranges
    width = sum(highs[i] - lows[i] for i in (*solution.units, *solution.without))
    return _ratio(min(1.0, float(width) / 200))


def _agreement(
    checks: Mapping[str, Check], conflicts: Collection[str]
) -> Decimal | None:
    """The share of the checks that could have failed that agree, or None."""
    informative = [check for check in checks.values() if check.informative]
    if not informative:
        return None
    agreeing = sum(
        1
        for check in informative
        if check.verdict is Verdict.AGREES and check.nutrient not in conflicts
    )
    return _ratio(agreeing / len(informative))


def _ratio(value: float | Decimal) -> Decimal:
    return Decimal(str(round(float(value), 6))).quantize(_DIGITS, ROUND_HALF_EVEN)
