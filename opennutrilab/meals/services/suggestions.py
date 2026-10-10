"""
What to get, when the inventory cannot meet the needs: foods that would.

The best day from the inventory is worked out first (services.proposals), and the
needs it misses are the gaps. For each gap, the foods of the CIQUAL table that give
the most of what is missed for the most the day could hold of them are the ones
worth looking at, a few for each. The day is then worked out again with them among
the candidates, as **new** foods (services.optimiser): they cost more than the
inventory's, and at most a few are used, so that only those that close the most are
suggested. What the day then misses, and what each food closes of it, is the answer.

That takes two goes, because the whole day with every food in it is slow for a
solver (it needs whole numbers of steps to fall inside the narrow bands of the
ratios). First the foods are *chosen*, with the inventory in any quantity and no
meal for the new foods, which is quick and finds the same foods; then the day is
worked out for those alone, in whole steps and each in one meal, which is quick
with so few.

A suggestion is a food ("huile de lin"), not a product: a label rarely declares
EPA or DHA, so the user finds the product that is that food. It is counted in grams
and has no serving. Every food of the table may be suggested but those that are no
food for an adult (infant foods), what is drunk (alcohol, water), and salt. No
suggestion is made for sodium or chloride, which salt would meet.

The day may be partly eaten (Meal.eaten), as it is for a proposal (services.proposals):
the meals eaten are counted and kept, so the gaps are what they leave, and the foods
suggested go in the meals that are not eaten.
"""

from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from django.utils.translation import get_language

from opennutrilab.meals.models import MealItem
from opennutrilab.meals.models import Profile
from opennutrilab.meals.services.day_report import DayReport
from opennutrilab.meals.services.day_report import GenericFood
from opennutrilab.meals.services.day_report import GenericItem
from opennutrilab.meals.services.day_report import Status
from opennutrilab.meals.services.day_report import combine
from opennutrilab.meals.services.day_report import report_of
from opennutrilab.meals.services.needs import Needs
from opennutrilab.meals.services.needs import daily_needs
from opennutrilab.meals.services.optimiser import KINDS
from opennutrilab.meals.services.optimiser import Candidate
from opennutrilab.meals.services.optimiser import Options
from opennutrilab.meals.services.optimiser import Pick
from opennutrilab.meals.services.optimiser import Plan
from opennutrilab.meals.services.optimiser import optimise
from opennutrilab.meals.services.optimiser import reference_amount
from opennutrilab.meals.services.proposals import EatenMeals
from opennutrilab.meals.services.proposals import Inventory
from opennutrilab.meals.services.proposals import NoProfileError
from opennutrilab.meals.services.proposals import eaten_meals
from opennutrilab.meals.services.proposals import items_of
from opennutrilab.meals.services.proposals import kept_items
from opennutrilab.meals.services.proposals import load_inventory
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.derived_nutrients import SUMS
from opennutrilab.products.services.derived_nutrients import derived_nutrients
from opennutrilab.products.services.reference_composition import Measure
from opennutrilab.products.services.reference_composition import food_composition
from opennutrilab.products.services.stored_estimates import Amount
from opennutrilab.users.models import User

CIQUAL_SOURCE_PREFIX = "ciqual"
CIQUAL_FOOD_URL = "https://ciqual.anses.fr/#/aliments/{code}"

# The foods looked at for each gap, how much of the gap one must be able to close
# (at the most a day holds of it) to be looked at, and how many a suggestion has.
PER_GAP = 6
MIN_SHARE = 0.2
MOST_NEW = 4
# Seconds the choice of the foods is given, and how far from the best it may stop at.
# Eight is far more than it needs where it was tried (it found the same foods in six),
# and three is not enough.
CHOICE_SECONDS = 8.0
CHOICE_GAP = 0.02
# What a food has to do to be named as closing a gap: this share of what is missed.
MIN_HELP = 0.2
# What is not suggested, in CIQUAL 2025's own words.
NOT_SUGGESTED_GROUPS = frozenset({"aliments infantiles"})
NOT_SUGGESTED_SUBGROUPS = frozenset(
    {
        "boisson alcoolisées",
        "eaux",
        "sels",
        "denrées destinées à une alimentation particulière",
    }
)
# No suggestion is made for these: salt would meet them.
NOT_SOUGHT = frozenset({"energy", "sodium", "chloride"})
# The most of a food in a day, by sub-group, then group, else the default.
DEFAULT_MOST_GRAMS = 250.0
_MOST_BY_SUBGROUP = {
    "huiles de poissons": 20.0,
    "fruits à coque et graines oléagineuses": 50.0,
    "herbes": 10.0,
    "épices": 5.0,
    "algues": 15.0,
    "condiments": 20.0,
    "sucres, miels et assimilés": 30.0,
    "confitures et assimilés": 40.0,
    "chocolats et produits à base de chocolat": 40.0,
}
_MOST_BY_GROUP = {
    "matières grasses": 30.0,
    "viandes, oeufs, poissons": 200.0,
    "produits sucrés": 100.0,
    "aides culinaires et ingrédients divers": 20.0,
}
# A food that is at most this much a day is counted in steps of the smaller size.
SMALL_MOST_GRAMS = 50.0
SMALL_STEP, STEP = 5.0, 10.0


class Gap(NamedTuple):
    """Something the day misses, and the foods are looked for it."""

    name: str
    unit: str
    # The nutrients to raise, with their weight in what is missed.
    terms: dict[str, float]
    # How much of them the day should bring, in the unit of the nutrients.
    reference: float
    # For a ratio, the nutrients that are raised to close it, which `name` is not.
    raised: str = ""


class Help(NamedTuple):
    """What a suggested food closes of a gap."""

    name: str
    unit: str
    amount: Decimal
    # The share of what the day should bring that this food does.
    share: Decimal
    # For a ratio, the nutrients the food gives to close it.
    raised: str = ""


class Suggested(NamedTuple):
    food: GenericFood
    grams: Decimal
    # The meals it is in, and how much in each, in the order of the day.
    picks: list[tuple[str, Decimal]]
    helps: list[Help]


class Suggestions(NamedTuple):
    # "optimal", "time_limit", "failed" (the solver found no day), "no_gaps" (the
    # inventory misses nothing), "no_foods" (no food of the table to look at),
    # "no_suggestion" (none is worth its price) or "nothing_to_fill" (every meal of the
    # day is eaten).
    status: str
    missed_before: int
    missed_after: int
    total: int
    foods: list[Suggested]
    # The day with them, and the best day from the inventory alone: the same when
    # nothing is suggested.
    report: DayReport
    base: DayReport


class Row(NamedTuple):
    """A food of the table with the amounts the first look is made on."""

    pk: int
    code: str
    name_fr: str
    name_en: str
    group: str
    subgroup: str
    amounts: dict[str, float]


class _Ground(NamedTuple):
    """What suggestions are worked out on: the user's day, needs and inventory."""

    user: User
    day: date
    needs: Needs
    eaten: EatenMeals
    inventory: Inventory
    options: Options

    def report(
        self,
        plan: Plan | None,
        added: Mapping[str, Sequence[GenericItem]] | None = None,
        foods: Mapping[str, Mapping[str, Amount]] | None = None,
    ) -> DayReport:
        """
        The day a plan makes (none: the meals eaten alone), with the generic foods
        `added`, by meal, whose compositions are `foods`.
        """
        proposed = [] if plan is None else items_of(plan, self.inventory.products)
        kept = kept_items(proposed, self.eaten.items)
        for kind, found in (added or {}).items():
            kept.setdefault(kind, []).extend(found)
        return report_of(
            self.user, self.day, kept, foods, eaten=self.eaten.items.keys()
        )


def suggest_foods(user: User, day: date, *, time_limit: float = 20.0) -> Suggestions:
    """What to get for the user's inventory to meet the needs of their profile."""
    profile = Profile.objects.filter(user=user).first()
    if profile is None:
        raise NoProfileError(user.pk)
    eaten = eaten_meals(user, day)
    ground = _Ground(
        user,
        day,
        daily_needs(profile),
        eaten,
        load_inventory(user, eaten.grams),
        Options(time_limit=time_limit),
    )
    if eaten.all_eaten:
        return _nothing("nothing_to_fill", ground.report(None))

    base_plan = optimise(
        ground.inventory.candidates,
        ground.needs,
        options=ground.options,
        eaten=eaten.eaten,
    )
    base = ground.report(base_plan)
    gaps = gaps_of(base, ground.needs)
    if not gaps:
        return _nothing("no_gaps", base)
    return _suggest_for(ground, gaps, base)


def _nothing(status: str, base: DayReport) -> Suggestions:
    """No food is suggested: the day is what it is without."""
    missing = missed(base)
    total = len(base.needs or []) + len(base.ratios or [])
    return Suggestions(status, missing, missing, total, [], base, base)


def _suggest_for(ground: _Ground, gaps: list[Gap], base: DayReport) -> Suggestions:
    """The foods of the table that close the gaps of the best day from the inventory."""
    foods = {row.pk: row for row in foods_to_look_at(gaps)}
    if not foods:
        return _nothing("no_foods", base)
    measures = measures_of(foods)
    candidates = {
        f"ciqual:{foods[pk].code}": candidate_of(foods[pk], found)
        for pk, found in measures.items()
        if found
    }
    inventory, needs, eaten = ground.inventory, ground.needs, ground.eaten.eaten
    # First the foods that are worth having, then the day made with those alone.
    choice = optimise(
        [*inventory.candidates, *candidates.values()],
        needs,
        options=Options(
            max_new=MOST_NEW,
            time_limit=CHOICE_SECONDS,
            whole_steps=False,
            gap=CHOICE_GAP,
        ),
        eaten=eaten,
    )
    chosen = [
        candidates[pick.barcode] for pick in _once(choice) if pick.barcode in candidates
    ]
    if not chosen:
        return _nothing(
            "failed" if choice.status == "failed" else "no_suggestion", base
        )
    plan = optimise(
        [*inventory.candidates, *chosen],
        needs,
        options=ground.options._replace(max_new=MOST_NEW),
        eaten=eaten,
    )
    if plan.status == "failed":
        return _nothing("failed", base)

    generic = {
        f"ciqual:{foods[pk].code}": amounts_of(found) for pk, found in measures.items()
    }
    suggested = _suggested(plan, foods, generic, gaps)
    if not suggested:
        return _nothing("no_suggestion", base)
    added: dict[str, list[GenericItem]] = {}
    for found in suggested:
        for kind, grams in found.picks:
            added.setdefault(kind, []).append(GenericItem(found.food, grams))
    report = ground.report(plan, added, generic)
    total = len(base.needs or []) + len(base.ratios or [])
    return Suggestions(
        plan.status, missed(base), missed(report), total, suggested, report, base
    )


# ----------------------------------------------------------------------------
# What is missed
# ----------------------------------------------------------------------------
def missed(report: DayReport) -> int:
    """How many needs and ratios of a day are not met."""
    found = [*(report.needs or []), *(report.ratios or [])]
    return sum(1 for status in found if status.verdict.status != Status.WITHIN)


def gaps_of(report: DayReport, needs: Needs) -> list[Gap]:
    """
    What a day is below, for which foods can be looked for: each lower end of a need
    it does not reach, and each ratio it is under (the numerator is to be raised) or
    over (the denominator is).
    """
    gaps: list[Gap] = []
    names = dict(report.catalogue)
    for status in report.needs or []:
        need = status.need
        if (
            status.verdict.status != Status.BELOW
            or need.low is None
            or NOT_SOUGHT & set(need.nutrients)
        ):
            continue
        gaps.append(
            Gap(
                status.name,
                status.unit,
                dict.fromkeys(need.nutrients, 1.0),
                float(need.low),
            )
        )
    for status in report.ratios or []:
        ratio = status.ratio
        top = combine(report.totals, ratio.numerator).amount
        bottom = combine(report.totals, ratio.denominator).amount
        # Under, the numerator is to be raised; over, the denominator. Either is
        # taken at what it is at the needs at the least, so that a day that has next to
        # none of it does not make a gap of a thousand times its need.
        if status.verdict.status == Status.BELOW and ratio.low is not None:
            terms, other = ratio.numerator, ratio.denominator
            wanted = float(ratio.low) * float(
                max(bottom, Decimal(str(reference_amount(other, needs))))
            )
        elif status.verdict.status == Status.ABOVE and ratio.high is not None:
            terms = ratio.denominator
            wanted = max(float(top / ratio.high), reference_amount(terms, needs))
        else:
            continue
        if NOT_SOUGHT & set(terms) or wanted <= 0:
            continue
        gaps.append(
            Gap(
                f"{status.numerator} / {status.denominator}",
                names[next(iter(terms))].unit,
                {code: float(weight) for code, weight in terms.items()},
                wanted,
                raised=" + ".join(names[code].name for code in terms),
            )
        )
    return gaps


# ----------------------------------------------------------------------------
# What to look at
# ----------------------------------------------------------------------------
def foods_to_look_at(gaps: Iterable[Gap]) -> list[Row]:
    """
    The foods of the table that could close the gaps: for each, the few that would
    give the most of it for what a day holds of them, if that is a fifth of it at
    least.
    """
    gaps = list(gaps)
    codes = {code for gap in gaps for code in gap.terms}
    rows = _rows(codes | {part for code in codes for part in SUMS.get(code, ())})
    chosen: dict[int, Row] = {}
    for gap in gaps:
        ranked = sorted(rows, key=lambda row: -_share(row, gap))
        for row in ranked[:PER_GAP]:
            if _share(row, gap) >= MIN_SHARE:
                chosen[row.pk] = row
    return list(chosen.values())


def _share(row: Row, gap: Gap) -> float:
    """The share of a gap's reference a food gives at the most a day holds of it."""
    per_100g = sum(w * row.amounts.get(code, 0.0) for code, w in gap.terms.items())
    return per_100g * most_grams(row) / 100 / gap.reference


def _rows(codes: Iterable[str]) -> list[Row]:
    """
    Every food that may be suggested, with what it measured of `codes` (exactly:
    a "less than" or a trace is not what a food is looked at on) and its energy.
    Foods with no energy are left out.
    """
    wanted = {*codes, "energy"}
    of_table = {"food__source__code__startswith": CIQUAL_SOURCE_PREFIX}
    amounts: defaultdict[int, dict[str, float]] = defaultdict(dict)
    values = SourceFoodNutrient.objects.filter(
        qualifier=SourceFoodNutrient.Qualifier.EXACT,
        amount__isnull=False,
        nutrient_id__in=wanted,
        **of_table,
    ).values_list("food_id", "nutrient_id", "amount")
    for food_id, code, amount in values.iterator(chunk_size=5000):
        amounts[food_id][code] = float(amount)
    rows: list[Row] = []
    foods = (
        SourceFood.objects.filter(source__code__startswith=CIQUAL_SOURCE_PREFIX)
        .exclude(food_group__in=NOT_SUGGESTED_GROUPS)
        .exclude(food_subgroup__in=NOT_SUGGESTED_SUBGROUPS)
        .values_list("id", "code", "name_fr", "name_en", "food_group", "food_subgroup")
    )
    for pk, code, name_fr, name_en, group, subgroup in foods:
        found = amounts.get(pk, {})
        if found.get("energy", 0.0) <= 0:
            continue
        for total, parts in SUMS.items():
            if any(part in found for part in parts):
                found[total] = sum(found.get(part, 0.0) for part in parts)
        rows.append(Row(pk, code, name_fr, name_en, group, subgroup, found))
    return rows


def most_grams(row: Row) -> float:
    """The most of a food in a day: by sub-group, then group, else the default."""
    return _MOST_BY_SUBGROUP.get(
        row.subgroup, _MOST_BY_GROUP.get(row.group, DEFAULT_MOST_GRAMS)
    )


# ----------------------------------------------------------------------------
# What they are
# ----------------------------------------------------------------------------
def measures_of(foods: Mapping[int, Row]) -> dict[int, dict[str, Measure]]:
    """What each food says of all its nutrients, with the intervals (see CIQUAL)."""
    derived = derived_nutrients()
    values: defaultdict[int, list[SourceFoodNutrient]] = defaultdict(list)
    for row in SourceFoodNutrient.objects.filter(food_id__in=foods).select_related(
        "nutrient"
    ):
        values[row.food_id].append(row)
    return {pk: food_composition(found, derived) for pk, found in values.items()}


def amounts_of(measures: Mapping[str, Measure]) -> dict[str, Amount]:
    """
    A food's measures as a day counts them. A trace is nothing with no upper end. A
    sum (omega-3, omega-6) adds the parts the food has, and is whole when it has them
    all, as for a product's own (see nutrient_estimation).
    """
    amounts = {
        code: Amount(
            amount=measure.amount or Decimal(0),
            low=measure.low or Decimal(0),
            high=measure.high,
            coverage=Decimal(100),
            declared=False,
        )
        for code, measure in measures.items()
    }
    for total, parts in SUMS.items():
        found = [amounts[part] for part in parts if part in amounts]
        if not found:
            continue
        every = len(found) == len(parts)
        highs = [part.high for part in found]
        amounts[total] = Amount(
            amount=sum((part.amount for part in found), Decimal(0)),
            low=sum((part.low for part in found), Decimal(0)),
            high=(
                sum((h for h in highs if h is not None), Decimal(0))
                if every and None not in highs
                else None
            ),
            coverage=Decimal(100 if every else 0),
            declared=False,
        )
    return amounts


def candidate_of(row: Row, measures: Mapping[str, Measure]) -> Candidate:
    """A food of the table as the optimiser counts it: new, in grams, in any meal."""
    most = most_grams(row)
    step = SMALL_STEP if most <= SMALL_MOST_GRAMS else STEP
    return Candidate(
        barcode=f"ciqual:{row.code}",
        name=_name(row),
        per_100g={
            code: float(found.amount) for code, found in amounts_of(measures).items()
        },
        step_grams=step,
        step_quantity=step,
        unit=MealItem.Unit.GRAM,
        max_grams=most,
        meals=frozenset(KINDS),
        new=True,
    )


def _name(row: Row) -> str:
    """The name of a food in the language served."""
    french = (get_language() or "").startswith("fr")
    return (row.name_fr if french else row.name_en) or row.name_fr or row.name_en


# ----------------------------------------------------------------------------
# What is suggested
# ----------------------------------------------------------------------------
def _once(plan: Plan) -> list[Pick]:
    """The picks of a plan, a food once: the choice has not decided its meal."""
    seen: set[str] = set()
    found: list[Pick] = []
    for pick in plan.picks:
        if pick.barcode not in seen:
            seen.add(pick.barcode)
            found.append(pick)
    return found


def _suggested(
    plan: Plan,
    foods: Mapping[int, Row],
    generic: Mapping[str, Mapping[str, Amount]],
    gaps: Iterable[Gap],
) -> list[Suggested]:
    """The new foods of a plan, each with where and how much, and what it closes."""
    by_key = {f"ciqual:{row.code}": row for row in foods.values()}
    in_meals: defaultdict[str, dict[str, Decimal]] = defaultdict(dict)
    for pick in plan.picks:
        if pick.barcode in by_key:
            in_meals[pick.barcode][pick.kind] = Decimal(str(round(pick.grams, 2)))
    gaps = list(gaps)
    found: list[Suggested] = []
    for key, meals in in_meals.items():
        row = by_key[key]
        grams = sum(meals.values(), Decimal(0))
        found.append(
            Suggested(
                food=GenericFood(
                    code=row.code,
                    name=_name(row),
                    group=row.group,
                    url=CIQUAL_FOOD_URL.format(code=row.code),
                ),
                grams=grams,
                picks=[(kind, meals[kind]) for kind in KINDS if kind in meals],
                helps=_helps(grams, generic[key], gaps),
            )
        )
    # The one that closes the most first.
    return sorted(
        found, key=lambda s: -max((h.share for h in s.helps), default=Decimal(0))
    )


def _helps(
    grams: Decimal, amounts: Mapping[str, Amount], gaps: Iterable[Gap]
) -> list[Help]:
    """The gaps a food closes a fifth of or more, the most closed first."""
    found: list[Help] = []
    for gap in gaps:
        raw = sum(
            (amounts[code].amount for code in gap.terms if code in amounts), Decimal(0)
        )
        weighted = sum(
            (
                Decimal(str(weight)) * amounts[code].amount
                for code, weight in gap.terms.items()
                if code in amounts
            ),
            Decimal(0),
        )
        share = weighted * grams / 100 / Decimal(str(gap.reference))
        if share >= Decimal(str(MIN_HELP)):
            found.append(
                Help(
                    gap.name,
                    gap.unit,
                    round(raw * grams / 100, 4),
                    round(share, 3),
                    gap.raised,
                )
            )
    # The need for EPA and the ratio of DHA over EPA are closed by the same grams of
    # EPA: said once, as the need.
    seen: set[tuple[Decimal, str]] = set()
    unique: list[Help] = []
    for help_ in sorted(found, key=lambda h: (-h.share, h.raised != "")):
        if (help_.amount, help_.unit) not in seen:
            seen.add((help_.amount, help_.unit))
            unique.append(help_)
    return unique[:4]
