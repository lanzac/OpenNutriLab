from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.custom_foods import CustomFoodError
from opennutrilab.products.services.custom_foods import create_custom_food
from opennutrilab.products.services.custom_foods import parse_spec
from opennutrilab.products.services.derived_nutrients import ensure_derivations
from opennutrilab.products.services.reference_composition import reference_composition

CONSTITUENTS_FILE = Path(__file__).parents[1] / "data" / "ciqual_const_2025.xml"
EXACT = SourceFoodNutrient.Qualifier.EXACT
LESS_THAN = SourceFoodNutrient.Qualifier.LESS_THAN
TRACES = SourceFoodNutrient.Qualifier.TRACES
D = Decimal
MAIN_COMPONENTS = ("water", "fat", "carbohydrates", "fiber", "proteins", "ash")


@pytest.fixture
def ciqual(db: None) -> Source:
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    ensure_derivations()
    return Source.objects.create(code="ciqual-2025", name="Ciqual", version="2025")


def food(source: Source, code: str, name_fr: str, **amounts: str) -> SourceFood:
    made = SourceFood.objects.create(source=source, code=code, name_fr=name_fr)
    for nutrient, amount in amounts.items():
        SourceFoodNutrient.objects.create(
            food=made,
            nutrient=Nutrient.objects.get(code=nutrient),
            amount=D(amount),
            confidence="A",
        )
    return made


def soy(source: Source) -> SourceFood:
    """Whole soybean, as the table gives it: figures with a single decimal."""
    return food(
        source,
        "20901",
        "Soja, graine entière",
        water="8.5",
        fat="19.9",
        carbohydrates="20.9",
        fiber="9.3",
        proteins="40.0",
        ash="5.0",
        energy="1840",
        vitamin_c="6.0",
    )


def spec(**changes: Any):
    data: dict[str, Any] = {
        "name_fr": "Flocons de soja",
        "name_en": "Soy flakes",
        "proxies": [{"source": "ciqual-2025", "code": "20901"}],
    }
    return parse_spec(data | changes)


def figures(
    made: Any, code: str
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    row = made.food.nutrients.get(nutrient_id=code)
    return row.amount, row.minimum, row.maximum


# ----------------------------------------------------------------------------
# One proxy
# ----------------------------------------------------------------------------
def test_a_food_is_made_in_the_manual_source_and_says_what_it_comes_from(
    ciqual: Source,
):
    soy(ciqual)

    made = create_custom_food(spec())

    assert made.created
    assert made.food.source.code == "Manual"
    assert made.food.name_fr == (
        "Flocons de soja (estimé d'après Soja, graine entière Ciqual 20901)"
    )
    assert made.food.name_en == (
        "Soy flakes (estimated from Soja, graine entière Ciqual 20901)"
    )
    assert made.food.food_group == "Estimation manuelle"


def test_every_nutrient_of_the_proxy_is_kept_with_a_range_of_at_least_15_percent(
    ciqual: Source,
):
    soy(ciqual)

    made = create_custom_food(spec())

    assert set(made.worked_out.values) == {
        "water", "fat", "carbohydrates", "fiber", "proteins", "ash", "energy",
        "vitamin_c",
    }  # fmt: skip
    # 40.0 g has a rounding of 0.05, far under 15 %: the margin decides.
    assert figures(made, "proteins") == (D("40"), D("34"), D("46"))
    assert figures(made, "energy") == (D("1840"), D("1564"), D("2116"))
    row = made.food.nutrients.get(nutrient_id="proteins")
    assert (row.qualifier, row.confidence) == (EXACT, "D")


def test_the_range_the_source_gives_is_kept_when_it_is_wider_than_the_margin(
    ciqual: Source,
):
    proxy = soy(ciqual)
    SourceFoodNutrient.objects.filter(food=proxy, nutrient_id="fiber").update(
        minimum=D("5"), maximum=D("12")
    )

    made = create_custom_food(spec())

    assert figures(made, "fiber") == (D("9.3"), D("5"), D("12"))


def test_a_nutrient_in_grams_never_goes_over_100(ciqual: Source):
    food(ciqual, "1", "Sel", water="0.1", fat="0", carbohydrates="0", proteins="0.1",
         fiber="0", ash="99.9")  # fmt: skip
    only = parse_spec(
        {"name_fr": "Sel", "proxies": [{"source": "ciqual-2025", "code": "1"}]}
    )

    made = create_custom_food(only)

    assert figures(made, "ash")[2] == D("100")


def test_the_figures_are_what_a_reference_linked_to_the_food_is_made_of(ciqual: Source):
    soy(ciqual)
    flakes = ReferenceIngredient.objects.create(name_fr="flocons de soja")

    made = create_custom_food(spec(references=["Flocons de soja"]))

    assert [(linked.reference, linked.other_foods) for linked in made.linked] == [
        (flakes, 0)
    ]
    protein = reference_composition(flakes)["proteins"]
    assert (protein.amount, protein.low, protein.high) == (D("40"), D("34"), D("46"))
    assert protein.grades == ("D",)
    flakes.refresh_from_db()
    assert flakes.status == ReferenceIngredient.Status.TO_REVIEW


# ----------------------------------------------------------------------------
# Bringing the proxies to a water content
# ----------------------------------------------------------------------------
def test_water_keeps_the_dry_matter_and_sets_the_water(ciqual: Source):
    food(ciqual, "1", "Tomate", water="80", fat="0.4", carbohydrates="12", fiber="3",
         proteins="3.6", ash="1", vitamin_c="20")  # fmt: skip

    made = create_custom_food(
        parse_spec(
            {
                "name_fr": "Tomate concentrée",
                "proxies": [{"source": "ciqual-2025", "code": "1"}],
                "water": 60,
            }
        )
    )

    # 40 g of dry matter per 100 g instead of 20: twice as much of everything.
    assert figures(made, "proteins")[0] == D("7.2")
    assert figures(made, "vitamin_c")[0] == D("40")
    assert figures(made, "water")[0] == D("60")
    assert made.food.name_fr.endswith("Ciqual 1, à 60 % d'eau)")
    assert not made.worked_out.warnings


def test_a_proxy_that_does_not_say_its_water_cannot_be_brought_to_one(ciqual: Source):
    food(ciqual, "1", "Tomate", fat="0.4")

    with pytest.raises(CustomFoodError, match="does not say its water"):
        create_custom_food(
            parse_spec(
                {
                    "name_fr": "Tomate",
                    "proxies": [{"source": "ciqual-2025", "code": "1"}],
                    "water": 60,
                }
            )
        )


def test_more_than_the_food_weighs_is_refused(ciqual: Source):
    food(ciqual, "1", "Graines", water="50", fat="60", carbohydrates="5",
         proteins="3", fiber="1", ash="1")  # fmt: skip

    with pytest.raises(CustomFoodError, match=r"fat comes to 120\.000000 g"):
        create_custom_food(
            parse_spec(
                {
                    "name_fr": "Graines",
                    "proxies": [{"source": "ciqual-2025", "code": "1"}],
                    "water": 0,
                }
            )
        )


# ----------------------------------------------------------------------------
# Several proxies
# ----------------------------------------------------------------------------
def test_proxies_are_mixed_by_share_and_the_range_holds_them_all(ciqual: Source):
    food(ciqual, "1", "Groseille", fat="0.2", proteins="1.1", sugars="4")
    food(ciqual, "2", "Framboise", fat="0.6", proteins="1.5", sugars="5")

    made = create_custom_food(
        parse_spec(
            {
                "name_fr": "Fruits rouges",
                "proxies": [
                    {"source": "ciqual-2025", "code": "1", "weight": 1},
                    {"source": "ciqual-2025", "code": "2", "weight": 3},
                ],
            }
        )
    )

    # Mean 1:3 of 1.1 and 1.5; the range holds both foods' own (1.05 to 1.55) and
    # is widened to 15 % of the amount above.
    assert figures(made, "proteins") == (D("1.4"), D("1.05"), D("1.61"))
    assert made.food.name_fr.endswith("Groseille Ciqual 1 x1; Framboise Ciqual 2 x3)")


def test_a_nutrient_that_one_proxy_did_not_measure_is_left_out_and_said(
    ciqual: Source,
):
    food(ciqual, "1", "Groseille", fat="0.2", proteins="1.0", vitamin_c="40")
    food(ciqual, "2", "Framboise", fat="0.6", proteins="1.4")

    made = create_custom_food(
        parse_spec(
            {
                "name_fr": "Fruits rouges",
                "proxies": [
                    {"source": "ciqual-2025", "code": "1"},
                    {"source": "ciqual-2025", "code": "2"},
                ],
            }
        )
    )

    assert "vitamin_c" not in made.worked_out.values
    assert made.worked_out.left_out == {"vitamin_c": "not measured in 2"}


def test_below_the_detection_limit_in_every_proxy_stays_so_and_traces_are_not_mixed(
    ciqual: Source,
):
    one = food(ciqual, "1", "A", fat="1", proteins="1", carbohydrates="1")
    two = food(ciqual, "2", "B", fat="2", proteins="2", carbohydrates="2")
    for proxy, qualifier, amount in (
        (one, LESS_THAN, "0.4"),
        (two, LESS_THAN, "0.2"),
    ):
        SourceFoodNutrient.objects.create(
            food=proxy,
            nutrient=Nutrient.objects.get(code="vitamin_b12"),
            amount=D(amount),
            qualifier=qualifier,
        )
    SourceFoodNutrient.objects.create(
        food=one, nutrient=Nutrient.objects.get(code="iodine"), qualifier=TRACES
    )
    SourceFoodNutrient.objects.create(
        food=two, nutrient=Nutrient.objects.get(code="iodine"), amount=D("3")
    )

    made = create_custom_food(
        parse_spec(
            {
                "name_fr": "Mélange",
                "proxies": [
                    {"source": "ciqual-2025", "code": "1"},
                    {"source": "ciqual-2025", "code": "2"},
                ],
            }
        )
    )

    row = made.food.nutrients.get(nutrient_id="vitamin_b12")
    assert (row.qualifier, row.amount, row.minimum) == (LESS_THAN, D("0.3"), None)
    assert "iodine" in made.worked_out.left_out


# ----------------------------------------------------------------------------
# By hand
# ----------------------------------------------------------------------------
def test_nutrients_given_by_hand_replace_the_proxys_and_add_to_it(ciqual: Source):
    soy(ciqual)

    made = create_custom_food(
        spec(
            exclude=["vitamin_c"],
            nutrients={
                "fat": 3,
                "proteins": {"amount": 50, "min": 40, "max": 60},
                "sugars": 6,
            },
        )
    )

    assert figures(made, "fat") == (D("3"), D("2.55"), D("3.45"))
    assert figures(made, "proteins") == (D("50"), D("40"), D("60"))
    assert figures(made, "sugars")[0] == D("6")
    assert "vitamin_c" not in made.worked_out.values


def test_a_range_given_by_hand_is_kept_and_the_margin_only_fills_the_side_not_given(
    ciqual: Source,
):
    soy(ciqual)

    made = create_custom_food(
        spec(
            nutrients={
                "proteins": {"amount": 77.5, "min": 75, "max": 80},
                "fat": {"amount": 10, "max": 11},
            }
        )
    )

    assert figures(made, "proteins") == (D("77.5"), D("75"), D("80"))
    assert figures(made, "fat") == (D("10"), D("8.5"), D("11"))


def test_a_composition_known_only_by_its_bounds_is_a_food_of_ranges(db: None):
    """A flavouring is no food: all that is known is what it cannot be."""
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    flavouring = ReferenceIngredient.objects.create(name_fr="arôme naturel")
    bounds = {"min": 0, "max": 100}

    made = create_custom_food(
        parse_spec(
            {
                "name_fr": "Arôme",
                "basis_fr": "bornes physiques (un support et des composés aromatiques)",
                "nutrients": dict.fromkeys(MAIN_COMPONENTS, bounds),
                "references": ["arôme naturel"],
            }
        )
    )

    # The amount is the lower end: the least that is surely there.
    assert figures(made, "fat") == (D("0"), D("0"), D("100"))
    assert made.worked_out.bounded == set(MAIN_COMPONENTS)
    assert not made.worked_out.warnings  # the lower ends add up to 0 g: no matter
    fat = reference_composition(flavouring)["fat"]
    assert (fat.low, fat.high) == (D("0"), D("100"))


def test_bounds_that_cannot_add_up_to_100_g_are_warned_about(db: None):
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))

    made = create_custom_food(
        parse_spec(
            {
                "name_fr": "Enzyme",
                "basis_fr": "x",
                "nutrients": {c: {"min": 0, "max": 5} for c in MAIN_COMPONENTS},
            }
        )
    )

    [warning] = made.worked_out.warnings
    assert "cannot add up to 100 g within the ranges given (0.0 to 30.0 g)" in warning


def test_a_food_may_be_only_what_is_given_by_hand_if_it_says_where_from(db: None):
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))

    made = create_custom_food(
        parse_spec(
            {
                "name_en": "Wheat gluten",
                "nutrients": {
                    "proteins": 75,
                    "fat": 1,
                    "carbohydrates": 14,
                    "water": 6,
                    "fiber": 2,
                    "ash": 1.5,
                },
                "basis_en": "a manufacturer's specification",
            }
        )
    )

    assert (
        made.food.name_en
        == "Wheat gluten (estimated from a manufacturer's specification)"
    )
    assert made.food.name_fr == ""
    assert not made.worked_out.warnings


def test_the_main_components_are_checked_against_the_100_g(db: None):
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))

    made = create_custom_food(
        parse_spec(
            {
                "name_en": "Wrong flour",
                "nutrients": {
                    "proteins": 40,
                    "fat": 20,
                    "carbohydrates": 40,
                    "water": 10,
                    "fiber": 5,
                    "ash": 2,
                },
                "basis_en": "a guess",
            }
        )
    )

    [warning] = made.worked_out.warnings
    assert "add up to 117.0 g" in warning


def test_a_food_without_fat_carbohydrates_or_proteins_is_warned_about(db: None):
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))

    made = create_custom_food(
        parse_spec(
            {"name_en": "Smoked salt", "nutrients": {"salt": 98}, "basis_en": "salt"}
        )
    )

    assert "No fat, carbohydrates, proteins" in made.worked_out.warnings[0]


# ----------------------------------------------------------------------------
# Names, codes and links
# ----------------------------------------------------------------------------
def test_the_basis_leaves_the_state_of_the_proxies_out_so_the_name_keeps_its_own(
    ciqual: Source,
):
    food(ciqual, "1", "Oignon, cuit", water="90", fat="0.2", carbohydrates="6",
         proteins="1", fiber="2", ash="0.5")  # fmt: skip

    made = create_custom_food(
        parse_spec(
            {
                "name_fr": "Oignon, séché",
                "proxies": [{"source": "ciqual-2025", "code": "1"}],
                "water": 5,
            }
        )
    )

    assert (
        made.food.name_fr
        == "Oignon, séché (estimé d'après Oignon Ciqual 1, à 5 % d'eau)"
    )


def test_a_basis_that_changes_the_state_the_name_reads_as_is_refused(ciqual: Source):
    soy(ciqual)

    with pytest.raises(CustomFoodError, match="changes the state"):
        create_custom_food(
            spec(name_fr="Soja, séché", basis_fr="Soja, cuit", basis_en="Soy")
        )


def test_the_code_comes_from_the_english_name_when_not_given(ciqual: Source):
    soy(ciqual)

    assert create_custom_food(spec()).food.code == "soy-flakes"


def test_a_food_of_that_code_is_refused_unless_it_is_replaced(ciqual: Source):
    soy(ciqual)
    first = create_custom_food(spec())

    with pytest.raises(CustomFoodError, match="already has a food 'soy-flakes'"):
        create_custom_food(spec())

    again = create_custom_food(spec(exclude=["vitamin_c"]), replace=True)
    assert not again.created
    assert again.food.pk == first.food.pk
    assert not again.food.nutrients.filter(nutrient_id="vitamin_c").exists()
    assert again.food.nutrients.count() == len(first.worked_out.values) - 1


def test_a_reference_is_found_by_id_or_by_a_name_in_either_language(ciqual: Source):
    soy(ciqual)
    by_french = ReferenceIngredient.objects.create(name_fr="flocons de soja")
    by_english = ReferenceIngredient.objects.create(name_en="soya flakes")
    by_id = ReferenceIngredient.objects.create(name_en="flakes of soy")

    made = create_custom_food(
        spec(references=["Flocons de SOJA", "soya flakes", by_id.pk])
    )

    assert [linked.reference for linked in made.linked] == [
        by_french,
        by_english,
        by_id,
    ]
    assert by_english.source_foods.get() == made.food


def test_a_reference_that_already_draws_on_a_food_is_told_so(ciqual: Source):
    soy(ciqual)
    other = food(ciqual, "9", "Tofu", fat="5")
    reference = ReferenceIngredient.objects.create(name_fr="soja")
    reference.source_foods.add(other)

    made = create_custom_food(spec(references=["soja"]))

    assert made.linked[0].other_foods == 1
    assert set(reference.source_foods.all()) == {other, made.food}


def test_nothing_is_kept_when_a_reference_is_not_found(ciqual: Source):
    soy(ciqual)

    with pytest.raises(CustomFoodError, match="No reference ingredient is 'nope'"):
        create_custom_food(spec(references=["nope"]))

    assert not SourceFood.objects.filter(source__code="Manual").exists()
    assert not Source.objects.filter(code="Manual").exists()


def test_a_proxy_that_is_not_there_is_refused(ciqual: Source):
    with pytest.raises(CustomFoodError, match="No food '20901' in the source"):
        create_custom_food(spec())


# ----------------------------------------------------------------------------
# The spec
# ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "must be a JSON object"),
        ({"name_fr": "x", "proxy": []}, "Unknown key"),
        ({}, "needs a name"),
        ({"name_fr": "x"}, "Without proxies"),
        (
            {"name_fr": "x", "water": 5, "nutrients": {"fat": 1}, "basis_fr": "y"},
            "it needs proxies",
        ),
        (
            {"name_fr": "x", "nutrients": {"fat": -1}, "basis_fr": "y"},
            "cannot be negative",
        ),
        (
            {"name_fr": "x", "nutrients": {"fat": "much"}, "basis_fr": "y"},
            "must be a number",
        ),
        (
            {"name_fr": "x", "nutrients": {"fat": {"max": 2}}, "basis_fr": "y"},
            "or both a min and a max",
        ),
        (
            {
                "name_fr": "x",
                "nutrients": {"fat": {"amount": 5, "max": 2}},
                "basis_fr": "y",
            },
            "between its min and its max",
        ),
        (
            {"name_fr": "x", "margin": 2, "nutrients": {"fat": 1}, "basis_fr": "y"},
            "margin",
        ),
        (
            {
                "name_fr": "x",
                "exclude": ["fat"],
                "nutrients": {"fat": 1},
                "basis_fr": "y",
            },
            "Both excluded and given",
        ),
        ({"name_fr": "x", "proxies": [{"source": "s"}]}, 'needs its "source"'),
        (
            {"name_fr": "x", "proxies": [{"source": "s", "code": "1", "weight": 0}]},
            "above 0",
        ),
        (
            {"name_fr": "x", "proxies": [{"source": "s", "code": "1"}] * 2},
            "listed twice",
        ),
    ],
)
def test_a_spec_that_makes_no_sense_is_refused_with_what_to_change(
    data: Any, message: str
):
    with pytest.raises(CustomFoodError, match=message):
        parse_spec(data)


def test_a_nutrient_the_catalogue_does_not_have_is_refused(ciqual: Source):
    soy(ciqual)

    with pytest.raises(
        CustomFoodError, match="Not in the catalogue of nutrients: vit_z"
    ):
        create_custom_food(spec(nutrients={"vit_z": 1}))
