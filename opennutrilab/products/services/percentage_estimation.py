"""
The percentages a label does not give, worked out from what it does say.

A label gives the order of the ingredients, a few percentages, and the nutrition
of the whole product. Nothing else is used. The unknown is the share of the
product that each ingredient, sub-ingredients included, makes up, and these are
the rules it has to follow:

- the ingredients at the top of the list add up to 100 %;
- the sub-ingredients of an ingredient add up to that ingredient;
- a declared percentage holds within its rounding (33 is 32.5 to 33.5, see
  rounding_margin). It is a share of the whole product, one written next to a
  sub-ingredient too (Regulation (EU) 1169/2011, annex VIII: the quantity of an
  ingredient is given as a percentage of the finished food): in "mini-involtini
  12 % (fromage 8,4 %, speck 3,6 %)" the two add up to the 12 %;
- the list is in descending order of weight (Regulation (EU) 1169/2011,
  article 18), so an ingredient never weighs more than the one before it in the
  same list. The regulation has exceptions that a text does not show, which can
  only make a result too narrow, and are reported when they make it impossible;
- the nutrition of the product, per 100 g, is what its ingredients add up to.
  For each nutrient on the label, the lowest the ingredients can make is below
  the label's upper end and the highest they can make is above its lower end.
  Each ingredient is itself an interval, and taking each nutrient on its own
  keeps the rules linear. So the intervals can be a little wider than the truth,
  never narrower.

Energy is left out of the last rule: a label computes it from the other
nutrients, so it says nothing more about the ingredients. Step 8 checks it.

The composition that counts for an ingredient is the one of the coarsest level
that has one in its branch: "raisins secs (raisins, huile de tournesol)" is
worked out from dried grapes, not from fresh ones and oil, whose water would
count for nothing but a quarter of the sugars. The sub-ingredients are used when
the ingredient has no composition of its own, and still get a percentage.

One more narrowing, from the label. A preparation whose name says it was cooked or
canned and whose parts include water ("petit épeautre et orge perlée cuits (eau,
petit épeautre, orge perlée, sel)") lists what went into the cooking, each as its
weight when used, so a part is the food before it, raw or dry, and not the cooked
one: the water is already one of the parts. A reference with no raw or dry food
keeps all of its foods.

A preparation has its own when it draws on source foods, and then it counts even
if the label lists its parts. Failing that, the parts the label lists count. A
preparation with neither falls back on the references it is made of, as a range
(see components_composition), and has none when one of them has none.

All of these are linear rules over the percentages, so what each percentage can
be is found exactly: its lowest and highest values among all the combinations
that follow the rules, one linear program for each (scipy, HiGHS). The point
value is a combination in the middle of them, which follows the rules as they
do (see _ranges), and a declared percentage keeps its own figure when it still
holds.

An additive with no composition does not leave the nutrition unused. What it
brings is unknown, anything from nothing to 100 g of each nutrient per 100 g of
itself (see _unknown), which only widens what the ingredients may add up to; it
is not counted as zero. The nutrition of the label then still narrows the other
ingredients, which an additive in a pinch should not keep from doing. So does a
vitamin: an ingredient that is a nutrient (Ingredient.nutrient), "vitamine B6",
is added to a food in a pinch too, and no one knows how much it is diluted in.
Its own nutrient is not given by it either, so that nutrient is only what the other
ingredients bring, at least (see nutrient_estimation): the label's figure for it,
which can be more, then agrees.

When the rules cannot all hold, nothing is guessed:
- an ingredient with no composition, other than an additive or a nutrient, leaves
  the nutrition unused, and says which;
- a label that the compositions cannot give leaves it unused, and says which
  nutrients are off. It is the label that is not trusted here and the composition
  that may be wrong, and the warning does not say which;
- a figure of the label is read as the rounding it is written with (33 is 32.5 to
  33.5, and a 0 is "less than 0.5 g" for a macronutrient), see label_tolerance. If
  that cannot agree with the ingredients for some nutrients, those are read with
  the tolerance the European Commission allows around a declared figure, and the
  result says so: a label is never exactly what the food holds. It is only then,
  since the tolerance is wide and would take from what the other figures tell;
- a label given per 100 ml (a liquid, Product.nutrition_unit) is kept as it prints
  it and set against the compositions, which are per 100 g, through the density of
  the product (see product_density). With no density known for every ingredient it
  is left unused, and says so: setting the two against each other as they are
  would call the label wrong for the density of the liquid;
- declared percentages and order that contradict each other give no estimate.

The processing a food goes through is not modelled: the percentages are of the
ingredients as used, and the nutrition is of the food as sold, so a product that
loses water (baked, dried) is out of reach of the nutrition rule.
"""

import itertools
from collections import defaultdict
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from decimal import ROUND_CEILING
from decimal import ROUND_FLOOR
from decimal import ROUND_HALF_EVEN
from decimal import Decimal
from typing import NamedTuple

import numpy as np
from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _
from numpy.typing import NDArray
from scipy.optimize import linprog

from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.services.derived_nutrients import derived_nutrients
from opennutrilab.products.services.food_forms import CANNED_WORDS
from opennutrilab.products.services.food_forms import COOKED_WORDS
from opennutrilab.products.services.food_forms import Form
from opennutrilab.products.services.food_forms import fold
from opennutrilab.products.services.food_forms import has_a_word_of
from opennutrilab.products.services.label_tolerance import label_reading
from opennutrilab.products.services.reference_composition import Estimate
from opennutrilab.products.services.reference_composition import components_composition
from opennutrilab.products.services.reference_composition import reference_composition
from opennutrilab.products.services.reference_composition import rounding_margin

# The nutrients of a label that tell what the ingredients are. In parent first
# order: a nutrient a food lacks is at most the one it is part of.
NUTRIENTS = (
    "fat",
    "saturated_fat",
    "carbohydrates",
    "sugars",
    "fiber",
    "proteins",
    "salt",
)
# A food with none of these has no composition worth counting.
REQUIRED_NUTRIENTS = frozenset({"fat", "carbohydrates", "proteins"})

_HUNDRED = 100.0
# The point of a share looks in this many directions, from this seed.
_DIRECTIONS = 32
_SEED = 0
# What the solver leaves of a rule that holds exactly.
_TOLERANCE = 1e-7
_DIGITS = Decimal("0.01")

# What went into a cooking is the food before it: raw, or dry.
BEFORE_COOKING = frozenset({Form.RAW, Form.DRIED})
# The words of a name that say its food was cooked or canned.
PROCESSED_WORDS = COOKED_WORDS | CANNED_WORDS

Range = tuple[float, float]
Matrix = NDArray[np.float64]
# The lowest and the highest value of each share, and a combination in the middle.
Ranges = tuple[Matrix, Matrix, Matrix]


class Interval(NamedTuple):
    """A share of the product, in percent. `point` is within `low` and `high`."""

    low: Decimal
    point: Decimal
    high: Decimal


class Problem(TextChoices):
    """
    What the estimate has to say besides its figures: what kept it from using all
    there is, and where it parts from the label. "%(detail)s" is what.
    """

    NO_COMPOSITION = (
        "no_composition",
        _(
            "The nutrition of the product was not used: no composition is known "
            "for %(detail)s."
        ),
    )
    NO_NUTRITION = (
        "no_nutrition",
        _("The nutrition of the product was not used: it declares none."),
    )
    LABEL_DISAGREES = (
        "label_disagrees",
        _(
            "The nutrition of the product was not used: the compositions of its "
            "ingredients cannot give it (%(detail)s)."
        ),
    )
    WITHIN_TOLERANCE = (
        "within_tolerance",
        _(
            "%(detail)s: the label is not exactly what the ingredients give, but "
            "within the tolerance the European Commission allows on a label, so "
            "it was read with that tolerance."
        ),
    )
    NUTRITION_PER_VOLUME = (
        "nutrition_per_volume",
        _(
            "The nutrition of the product was not used: the label gives it per "
            "100 ml, and the density of its ingredients, to convert it to per 100 "
            "g, is not known."
        ),
    )
    IMPOSSIBLE = (
        "impossible",
        _(
            "The declared percentages and the order of the ingredients "
            "contradict each other: nothing could be estimated."
        ),
    )
    # Said by estimate_validation, which compares the estimate with the label. Here
    # "%(detail)s" is the nutrient, and the figures come with their unit.
    DECLARED_BELOW = (
        "declared_below",
        _(
            "%(detail)s: the label declares %(declared)s, but its ingredients "
            "bring at least %(estimated)s."
        ),
    )
    DECLARED_ABOVE = (
        "declared_above",
        _(
            "%(detail)s: the label declares %(declared)s, but its ingredients "
            "bring at most %(estimated)s."
        ),
    )


class EstimateWarning(NamedTuple):
    problem: Problem
    detail: str = ""
    # The nutrients (by code) the detail is about, when it names some.
    codes: tuple[str, ...] = ()
    # What else the message names, by placeholder.
    figures: Mapping[str, str] | None = None

    def message(self) -> str:
        return str(self.problem.label) % {"detail": self.detail, **(self.figures or {})}


class PercentageEstimate(NamedTuple):
    # By ingredient id: its share of the whole product. Empty when impossible.
    percentages: dict[int, Interval]
    warnings: list[EstimateWarning]
    # Whether the nutrition of the product narrowed the percentages.
    used_nutrition: bool


class Node(NamedTuple):
    """One ingredient, siblings in the order the label lists them."""

    key: int
    parent: int | None
    name: str
    declared: Decimal | None = None
    # (low, high) per 100 g, for the nutrients in NUTRIENTS; None if it has none.
    composition: Mapping[str, Range] | None = None
    # (low, high) in g/ml, when its reference has one (see product_density).
    density: Range | None = None
    # An additive or a vitamin, added in a pinch: left out of the density.
    in_a_pinch: bool = False


Row = tuple[dict[int, float], float]


@dataclass
class Rules:
    """
    Linear rules over the columns: `ub` rows are <=, `eq` rows are =.

    The rows are not to change once the rules have been solved.
    """

    width: int
    ub: list[Row] = field(default_factory=list)
    eq: list[Row] = field(default_factory=list)
    bounds: list[Range] = field(default_factory=list)
    _matrices: tuple[Matrix | None, Matrix | None] | None = field(
        default=None, init=False, repr=False
    )

    def solve(self, objective: Matrix) -> Matrix | None:
        """The columns that minimise the objective, or None if no values follow
        the rules."""
        if self._matrices is None:
            self._matrices = (
                self._matrix(self.ub) if self.ub else None,
                self._matrix(self.eq) if self.eq else None,
            )
        result = linprog(
            objective,
            A_ub=self._matrices[0],
            b_ub=[bound for _, bound in self.ub] if self.ub else None,
            A_eq=self._matrices[1],
            b_eq=[bound for _, bound in self.eq] if self.eq else None,
            bounds=self.bounds,
            method="highs",
        )
        if result.status == 2:  # noqa: PLR2004
            return None
        if result.status != 0:
            msg = f"The linear program failed: {result.message}"
            raise RuntimeError(msg)
        return np.asarray(result.x, dtype=np.float64)

    def _matrix(self, rows: Sequence[Row]) -> Matrix:
        matrix = np.zeros((len(rows), self.width))
        for r, (coefficients, _bound) in enumerate(rows):
            for column, value in coefficients.items():
                matrix[r, column] = value
        return matrix


class Loaded(NamedTuple):
    """A product as the estimate reads it from the database."""

    nodes: list[Node]
    label: dict[str, Range]
    nutrient_names: dict[str, str]
    # The whole composition of each node's reference, parallel to `nodes`.
    compositions: list[dict[str, Estimate]]
    # The nutrient each one is part of, by code (sugars are carbohydrates).
    parents: dict[str, str | None]
    # The unit each nutrient is given in, by code.
    units: dict[str, str]
    # What the label is given per 100 of: "g", or "ml" (see Product.nutrition_unit).
    label_unit: str = Product.ServingUnit.GRAM
    # The same figures with the tolerance around them (see label_tolerance).
    label_tolerated: dict[str, Range] | None = None
    # The group the catalogue puts each nutrient in, by code.
    groups: dict[str, str] | None = None


def load(product: Product) -> Loaded:
    """Read a product's ingredients, their compositions and its label."""
    ingredients = list(
        product.ingredients.select_related(
            "reference", "preparation", "additive", "nutrient"
        ).prefetch_related(
            "preparation__source_foods",
            "preparation__components",
            "preparation__preparation_components",
        )
    )
    catalogue = {nutrient.code: nutrient for nutrient in Nutrient.objects.all()}
    derived = list(derived_nutrients())
    # A reference and a preparation can have the same id: the kind is in the key.
    items = {(type(i.item), i.item.pk): i.item for i in ingredients}
    own = {key: reference_composition(item, derived) for key, item in items.items()}
    listed_parts = {i.parent_id for i in ingredients if i.parent_id is not None}
    before_cooking = _parts_that_went_into_a_cooking(ingredients)
    raw: dict[tuple[type, int], dict[str, Estimate]] = {}
    by_default: dict[int, dict[str, Estimate]] = {}
    full: list[dict[str, Estimate]] = []
    for i in ingredients:
        key = (type(i.item), i.item.pk)
        if i.id in before_cooking:
            if key not in raw:
                raw[key] = reference_composition(
                    items[key], derived, forms=BEFORE_COOKING
                )
            composition = raw[key]
        else:
            composition = own[key]
        # Only a preparation with no food and no part listed here: see the module.
        if (
            not composition
            and i.preparation is not None
            and i.id not in listed_parts
            and not i.preparation.source_foods.all()
        ):
            if i.preparation.pk not in by_default:
                by_default[i.preparation.pk] = components_composition(
                    i.preparation, derived
                )
            composition = by_default[i.preparation.pk]
        full.append(composition)
    nodes = [
        Node(
            key=i.id,
            parent=i.parent_id,
            name=i.item.name,
            declared=i.percentage,
            composition=_macronutrients(composition, catalogue)
            or (_unknown() if _is_no_food(i) else None),
            density=_density_of(i),
            in_a_pinch=_is_no_food(i),
        )
        for i, composition in zip(ingredients, full, strict=True)
    ]
    label: dict[str, Range] = {}
    tolerated: dict[str, Range] = {}
    for code, amount in product.declared_nutrients.filter(
        nutrient__in=NUTRIENTS
    ).values_list("nutrient_id", "amount"):
        reading = label_reading(code, catalogue[code].group, Decimal(amount))
        label[code] = _floats(reading.rounded)
        tolerated[code] = _floats(reading.tolerated)
    return Loaded(
        nodes,
        label,
        {code: nutrient.name for code, nutrient in catalogue.items()},
        full,
        {code: nutrient.parent_id for code, nutrient in catalogue.items()},
        {code: nutrient.unit for code, nutrient in catalogue.items()},
        product.nutrition_unit,
        tolerated,
        {code: nutrient.group for code, nutrient in catalogue.items()},
    )


def _parts_that_went_into_a_cooking(ingredients: Sequence[Ingredient]) -> set[int]:
    """
    The ingredients (ids) that are references listed as the parts of a preparation
    whose name says it was cooked or canned, when water is among them.

    "petit épeautre et orge perlée cuits (eau, petit épeautre 3,2 %, orge perlée
    3,2 %, sel)": the label gives each part as its weight when it was used
    (Regulation 1169/2011, annex VIII), and lists the cooking water as one of them,
    so the barley is the dry grain. Counted as cooked barley it would bring its
    water a second time. The cooking is said by the parent, not by the part, which
    is why its name does not carry it.
    """
    by_id = {i.id: i for i in ingredients}
    siblings: defaultdict[int, list[Ingredient]] = defaultdict(list)
    for i in ingredients:
        if i.parent_id is not None:
            siblings[i.parent_id].append(i)
    cooking = {
        parent_id
        for parent_id, parts in siblings.items()
        if (parent := by_id[parent_id]).preparation is not None
        and any(
            has_a_word_of(name, PROCESSED_WORDS)
            for name in (parent.preparation.name_fr, parent.preparation.name_en)
        )
        and any(_is_water(part) for part in parts)
    }
    return {
        i.id
        for parent_id in cooking
        for i in siblings[parent_id]
        if i.reference is not None and not _is_water(i)
    }


def _is_water(ingredient: Ingredient) -> bool:
    reference = ingredient.reference
    return reference is not None and (
        fold(reference.name_fr) == "eau" or fold(reference.name_en) == "water"
    )


def estimate_percentages(product: Product) -> PercentageEstimate:
    """What the label of a product says of the shares of its ingredients."""
    loaded = load(product)
    return percentages_of(
        solve_shares(
            loaded.nodes,
            loaded.label,
            loaded.nutrient_names,
            label_unit=loaded.label_unit,
            tolerated=loaded.label_tolerated,
        )
    )


@dataclass(frozen=True)
class Solution:
    """
    What the rules left of the shares, for what is worked out from them.

    `rules` are those that held, with the nutrition of the product when it was
    used. `ranges` is the lowest and the highest value of each node, and a
    combination that follows the rules, in the middle of them. Both are
    None when no values follow the rules.
    """

    nodes: Sequence[Node]
    # The nodes whose composition counts, and those that leave a branch without.
    units: list[int]
    without: list[int]
    warnings: list[EstimateWarning]
    used_nutrition: bool
    rules: Rules | None = None
    ranges: tuple[Matrix, Matrix, Matrix] | None = None
    # What a millilitre of the product weighs, in g/ml, when it can be told.
    density: Range | None = None
    # The nutrients (by code) whose figure only agreed with the ingredients when
    # read with the tolerance.
    tolerated: tuple[str, ...] = ()


def solve_shares(
    nodes: Sequence[Node],
    label: Mapping[str, Range],
    nutrient_names: Mapping[str, str] | None = None,
    *,
    label_unit: str = Product.ServingUnit.GRAM,
    tolerated: Mapping[str, Range] | None = None,
) -> Solution:
    """
    The share each node can be, from the rules in the module's description.

    `tolerated` is the label with the tolerance around each figure, to fall back on
    for the nutrients the rounding alone cannot agree with.

    `label` is the interval of each nutrient of the whole product, per 100 g, or per
    100 ml when `label_unit` says so. A figure per 100 ml is set against the
    compositions, which are per 100 g, through the density of the product (see
    product_density), as it would be per 100 g; with none known it is not used.
    """
    if not nodes:
        return Solution(nodes, [], [], [], used_nutrition=False)
    warnings: list[EstimateWarning] = []
    tree = _tree(nodes)
    units, without = _units(nodes)
    # An ingredient with no composition may be of any density.
    density = None if without else product_density(nodes, units)

    nutrition: Rules | None = None
    if reason := _why_unused(nodes, label, without, label_unit, density):
        warnings.append(reason)
    else:
        if label_unit != Product.ServingUnit.GRAM.value:
            assert density is not None  # the branch above
            label = _per_mass(label, density)
            tolerated = None if tolerated is None else _per_mass(tolerated, density)
        nutrition = _with_nutrition(tree, nodes, units, label)

    rules = nutrition
    ranges = _ranges(nutrition) if nutrition is not None else None
    read_with_tolerance: tuple[str, ...] = ()
    if ranges is None and tolerated and nutrition is not None:
        found = _read_with_tolerance(tree, nodes, units, label, tolerated)
        if found is not None:
            nutrition, ranges, read_with_tolerance = found
            rules = nutrition
            warnings.append(
                _named(Problem.WITHIN_TOLERANCE, read_with_tolerance, nutrient_names)
            )
    if ranges is None:
        rules = tree
        ranges = _ranges(tree)
        if ranges is None:
            warnings.append(EstimateWarning(Problem.IMPOSSIBLE))
            return Solution(
                nodes, units, without, warnings, used_nutrition=False, density=density
            )
        if nutrition is not None:
            # Off even with the tolerance, when there is one.
            off = _disagreeing(tree, nodes, units, {**label, **(tolerated or {})})
            warnings.append(_named(Problem.LABEL_DISAGREES, off, nutrient_names))
    return Solution(
        nodes,
        units,
        without,
        warnings,
        used_nutrition=rules is nutrition,
        rules=rules,
        ranges=ranges,
        density=density,
        tolerated=read_with_tolerance,
    )


def _why_unused(
    nodes: Sequence[Node],
    label: Mapping[str, Range],
    without: Sequence[int],
    label_unit: str,
    density: Range | None,
) -> EstimateWarning | None:
    """What keeps the nutrition of the label from being used at all, if anything."""
    if not label:
        return EstimateWarning(Problem.NO_NUTRITION)
    if without:
        return EstimateWarning(
            Problem.NO_COMPOSITION, ", ".join(nodes[i].name for i in without)
        )
    if label_unit != Product.ServingUnit.GRAM.value and density is None:
        return EstimateWarning(Problem.NUTRITION_PER_VOLUME)
    return None


def _named(
    problem: Problem, codes: Sequence[str], names: Mapping[str, str] | None
) -> EstimateWarning:
    """A warning about nutrients, which names them in the language served."""
    detail = ", ".join((names or {}).get(code, code) for code in codes)
    return EstimateWarning(problem, detail, tuple(codes))


def estimate(
    nodes: Sequence[Node],
    label: Mapping[str, Range],
    nutrient_names: Mapping[str, str] | None = None,
    *,
    label_unit: str = Product.ServingUnit.GRAM,
    tolerated: Mapping[str, Range] | None = None,
) -> PercentageEstimate:
    """The share each node can be, as intervals. See solve_shares."""
    return percentages_of(
        solve_shares(
            nodes, label, nutrient_names, label_unit=label_unit, tolerated=tolerated
        )
    )


def percentages_of(solution: Solution) -> PercentageEstimate:
    if solution.ranges is None:
        return PercentageEstimate({}, solution.warnings, used_nutrition=False)
    lows, highs, points = solution.ranges
    percentages = {
        node.key: interval(node.declared, lows[i], points[i], highs[i])
        for i, node in enumerate(solution.nodes)
    }
    return PercentageEstimate(
        percentages, solution.warnings, used_nutrition=solution.used_nutrition
    )


def _floats(ends: tuple[Decimal, Decimal]) -> Range:
    return float(ends[0]), float(ends[1])


def _read_with_tolerance(
    tree: Rules,
    nodes: Sequence[Node],
    units: Sequence[int],
    label: Mapping[str, Range],
    tolerated: Mapping[str, Range],
) -> tuple[Rules, Ranges, tuple[str, ...]] | None:
    """
    The rules with the nutrition when the label is read with its tolerance, the
    ranges they leave, and the nutrients that needed it; None if it does not help.

    The nutrients the rounding cannot agree with are widened first and alone, so
    that the others keep telling what they do, and all of them if that is not
    enough.
    """
    off = tuple(
        code for code in _disagreeing(tree, nodes, units, label) if code in tolerated
    )
    if not off:
        return None
    tried: list[dict[str, Range]] = []
    for widened in (
        {**label, **{code: tolerated[code] for code in off}},
        {**label, **tolerated},
    ):
        if widened in tried:
            continue
        tried.append(widened)
        rules = _with_nutrition(tree, nodes, units, widened)
        ranges = _ranges(rules)
        if ranges is not None:
            return rules, ranges, off
    return None


def _declared_range(amount: Decimal) -> Range:
    margin = rounding_margin(amount)
    return float(max(Decimal(0), amount - margin)), float(amount + margin)


def _macronutrients(
    composition: Mapping[str, Estimate], catalogue: Mapping[str, Nutrient]
) -> dict[str, Range] | None:
    """
    The (low, high) of each nutrient in NUTRIENTS, or None for a composition that
    lacks the main ones.

    A nutrient it does not have is somewhere from nothing to the one it is part
    of (sugars are carbohydrates), or to the 100 g everything is given for.
    """
    if not composition.keys() >= REQUIRED_NUTRIENTS:
        return None
    ranges: dict[str, Range] = {}
    for code in NUTRIENTS:
        if (estimate_ := composition.get(code)) is not None:
            high = float(estimate_.high) if estimate_.high is not None else _HUNDRED
            ranges[code] = (float(estimate_.low or 0), high)
            continue
        parent = catalogue[code].parent_id if code in catalogue else None
        ranges[code] = (0.0, ranges[parent][1] if parent in ranges else _HUNDRED)
    return ranges


def _is_no_food(ingredient: Ingredient) -> bool:
    """
    Whether an ingredient is an additive or a nutrient (a vitamin): what is added to
    a food in a pinch, and has no composition per 100 g to look for.
    """
    return ingredient.additive is not None or ingredient.nutrient is not None


def _density_of(ingredient: Ingredient) -> Range | None:
    """The density (g/ml) of an ingredient's reference, as (low, high), if any."""
    reference = ingredient.reference
    if reference is None or reference.density_low is None:
        return None
    assert reference.density_high is not None  # both or neither: see the constraint
    return float(reference.density_low), float(reference.density_high)


def product_density(nodes: Sequence[Node], units: Sequence[int]) -> Range | None:
    """
    What a millilitre of the product can weigh, in g/ml, as (low, high); None when
    it cannot be told.

    The ingredients are mixed, so the product weighs somewhere between the lightest
    of them and the heaviest, whatever their shares: the harmonic mean that volumes
    add up to cannot leave that. It is a range wider than the truth, never narrower,
    and it needs the density of every ingredient that counts. An additive or a
    vitamin is left out, being added in a pinch (see _is_no_food), and an ingredient
    with no density, a preparation for one, leaves the product without.
    """
    lows: list[float] = []
    highs: list[float] = []
    for i in units:
        node = nodes[i]
        if node.in_a_pinch:
            continue
        if node.density is None:
            return None
        lows.append(node.density[0])
        highs.append(node.density[1])
    return (min(lows), max(highs)) if lows else None


def _per_mass(label: Mapping[str, Range], density: Range) -> dict[str, Range]:
    """
    A label given per 100 ml as it would be per 100 g: the lowest figure over the
    heaviest millilitre, the highest over the lightest.
    """
    least, most = density
    return {code: (low / most, high / least) for code, (low, high) in label.items()}


def _unknown() -> dict[str, Range]:
    """
    What an ingredient can be when nothing is known of it: anything from nothing
    to the 100 g everything is given for, for each nutrient. It never narrows the
    nutrition rule and never makes it wrong.
    """
    return dict.fromkeys(NUTRIENTS, (0.0, _HUNDRED))


def _units(nodes: Sequence[Node]) -> tuple[list[int], list[int]]:
    """
    The indices of the nodes whose composition counts, which is the coarsest that
    has one in each branch, and of those that leave a branch without any.
    """
    children: defaultdict[int | None, list[int]] = defaultdict(list)
    for i, node in enumerate(nodes):
        children[node.parent].append(i)

    units: list[int] = []
    without: list[int] = []

    def visit(i: int) -> None:
        if nodes[i].composition is not None:
            units.append(i)
        elif subs := children[nodes[i].key]:
            for sub in subs:
                visit(sub)
        else:
            without.append(i)

    for root in children[None]:
        visit(root)
    return units, without


def _tree(nodes: Sequence[Node]) -> Rules:
    """The rules a label's list of ingredients gives, and no more."""
    index = {node.key: i for i, node in enumerate(nodes)}
    problem = Rules(len(nodes), bounds=[(0.0, _HUNDRED)] * len(nodes))
    siblings: defaultdict[int | None, list[int]] = defaultdict(list)
    for i, node in enumerate(nodes):
        siblings[node.parent].append(i)

    for i, node in enumerate(nodes):
        if node.declared is None:
            continue
        # A share of the whole product, whatever the level: that it is within its
        # parent follows from the parent being the sum of its parts.
        low, high = _declared_range(node.declared)
        problem.bounds[i] = (low, min(high, _HUNDRED))

    roots = siblings[None]
    # A label that declares every ingredient need not add up to 100: 99.4 is
    # rounding, not an error.
    if any(nodes[i].declared is None for i in roots):
        problem.eq.append((dict.fromkeys(roots, 1.0), _HUNDRED))
    for parent_key, group in siblings.items():
        if parent_key is not None:
            problem.eq.append(
                ({**dict.fromkeys(group, 1.0), index[parent_key]: -1.0}, 0.0)
            )
        problem.ub.extend(
            ({after: 1.0, before: -1.0}, 0.0)
            for before, after in itertools.pairwise(group)
        )
    return problem


def _with_nutrition(
    tree: Rules,
    nodes: Sequence[Node],
    units: Sequence[int],
    label: Mapping[str, Range],
    *,
    slack: bool = False,
) -> Rules:
    """
    The tree's rules and those of the nutrition. With `slack`, each nutrient has a
    column that lets it be missed, by that many times the label's rounding.
    """
    width = tree.width + (len(label) if slack else 0)
    problem = Rules(
        width,
        ub=list(tree.ub),
        eq=list(tree.eq),
        bounds=[*tree.bounds, *[(0.0, np.inf)] * (width - tree.width)],
    )
    for k, (code, (low, high)) in enumerate(label.items()):
        lows: dict[int, float] = {}
        highs: dict[int, float] = {}
        for i in units:
            composition = nodes[i].composition or {}
            least, most = composition.get(code, (0.0, _HUNDRED))
            lows[i] = least / 100
            highs[i] = -most / 100
        if slack:
            scale = max((high - low) / 2, _TOLERANCE)
            lows[tree.width + k] = -scale
            highs[tree.width + k] = -scale
        problem.ub.append((lows, high))
        problem.ub.append((highs, -low))
    return problem


def _ranges(problem: Rules) -> tuple[Matrix, Matrix, Matrix] | None:
    """
    The lowest and highest value of each of the first columns, and a combination
    in the middle of those that follow the rules; None if none does.

    That combination is the mean of the middles of the combinations that are most
    and least in each of a number of directions, chosen once at random and the
    same every time. Taking the extremes of each column alone would not do: where
    several combinations are as extreme, the solver returns any of them, and the
    mean leans towards the corners (three sub-ingredients of 1.4 % in order would
    come out as 1.30, 0.06 and 0.03 instead of about 0.9, 0.4 and 0.2).
    """
    count = len(problem.bounds)
    lows = np.zeros(count)
    highs = np.zeros(count)
    for i in range(count):
        for sign in (1.0, -1.0):
            objective = np.zeros(count)
            objective[i] = sign
            found = problem.solve(objective)
            if found is None:
                return None
            (lows if sign > 0 else highs)[i] = found[i]

    generator = np.random.default_rng(_SEED)
    middles: list[Matrix] = []
    for _step in range(_DIRECTIONS):
        direction = generator.normal(size=count)
        least = problem.solve(direction)
        most = problem.solve(-direction)
        # The rules held for the columns above and nothing has changed since.
        assert least is not None
        assert most is not None
        middles.append((least + most) / 2)
    return lows, highs, np.mean(middles, axis=0)


def _disagreeing(
    tree: Rules,
    nodes: Sequence[Node],
    units: Sequence[int],
    label: Mapping[str, Range],
) -> list[str]:
    """The nutrients that have to be missed for the rest to hold, the least."""
    problem = _with_nutrition(tree, nodes, units, label, slack=True)
    objective = np.zeros(problem.width)
    objective[tree.width :] = 1.0
    found = problem.solve(objective)
    if found is None:  # Not possible: the slack can relax every nutrient rule.
        return []
    return [code for k, code in enumerate(label) if found[tree.width + k] > _TOLERANCE]


def interval(
    declared: Decimal | None, low: float, point: float, high: float
) -> Interval:
    """Rounded outwards, since the solver is exact only to its tolerance."""
    lowest = _decimal(low).quantize(_DIGITS, ROUND_FLOOR)
    highest = _decimal(high).quantize(_DIGITS, ROUND_CEILING)
    if declared is not None and lowest <= declared <= highest:
        return Interval(lowest, declared, highest)
    middle = _decimal(point).quantize(_DIGITS, ROUND_HALF_EVEN)
    return Interval(lowest, min(max(middle, lowest), highest), highest)


def _decimal(value: float) -> Decimal:
    # + 0.0 turns the -0.0 a solver leaves for nothing into 0.0, not "-0.00".
    return Decimal(str(round(value, 6) + 0.0))
