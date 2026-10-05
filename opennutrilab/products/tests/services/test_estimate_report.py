from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.utils import translation

from opennutrilab.products.api.schemas.outbound import EstimateOut
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.derived_nutrients import ensure_derivations
from opennutrilab.products.services.estimate_report import build_estimate

D = Decimal
CONSTITUENTS_FILE = Path(__file__).parents[1] / "data" / "ciqual_const_2025.xml"
ATTRIBUTION = "Anses. Table Ciqual 2025. Licence Ouverte 2.0 (Etalab)."


@pytest.fixture
def source(db: None) -> Source:
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    ensure_derivations()
    return Source.objects.create(
        code="ciqual-2025",
        name="Ciqual",
        version="2025",
        url="https://ciqual.anses.fr",
        attribution=ATTRIBUTION,
    )


def reference(source: Source, code: str, **amounts: str) -> ReferenceIngredient:
    food = SourceFood.objects.create(
        source=source, code=code, name_fr=f"Aliment {code}"
    )
    values = {"fat": "0", "carbohydrates": "0", "proteins": "0", **amounts}
    for nutrient, amount in values.items():
        SourceFoodNutrient.objects.create(
            food=food,
            nutrient=Nutrient.objects.get(code=nutrient),
            amount=D(amount),
            confidence="A",
        )
    ref = ReferenceIngredient.objects.create(
        name_en=f"reference {code}", name_fr=f"fiche {code}"
    )
    ref.source_foods.add(food)
    return ref


def product_of(**declared: str) -> Product:
    product = Product.objects.create(barcode="3229820794556", name="Muesli")
    for code, amount in declared.items():
        ProductNutrient.objects.create(
            product=product, nutrient=Nutrient.objects.get(code=code), amount=D(amount)
        )
    return product


def add(
    product: Product,
    ref: ReferenceIngredient,
    percentage: str | None = None,
    parent: Ingredient | None = None,
) -> Ingredient:
    return Ingredient.objects.create(
        product=product,
        reference=ref,
        parent=parent,
        percentage=None if percentage is None else D(percentage),
    )


def nutrients_of(estimate: EstimateOut) -> dict[str, Any]:
    return {n.code: n for n in estimate.nutrients}


# ----------------------------------------------------------------------------
# The nutrients
# ----------------------------------------------------------------------------
def test_a_nutrient_has_its_estimate_its_coverage_its_label_and_its_check(
    source: Source,
):
    product = product_of(proteins="15", energy="1310")
    add(product, reference(source, "1", proteins="20", energy="1600"))
    add(product, reference(source, "2", proteins="10", energy="1000"))

    estimate = build_estimate(product)

    energy = nutrients_of(estimate)["energy"]
    assert (energy.name, energy.unit) == ("Energy", "kJ")
    assert energy.estimated is not None
    assert energy.estimated.low <= energy.estimated.point <= energy.estimated.high
    assert energy.coverage is not None
    assert energy.coverage.point == D(100)
    assert energy.declared is not None
    assert (energy.declared.amount, energy.declared.low, energy.declared.high) == (
        D("1310"),
        D("1309.5"),
        D("1310.5"),
    )
    assert energy.check is not None
    assert (energy.check.verdict, energy.check.constrained) == ("agrees", False)
    assert energy.confidence is not None
    assert D(0) <= energy.confidence.score <= D(1)
    # What the label's protein was used for says nothing more.
    assert nutrients_of(estimate)["proteins"].check.constrained  # type: ignore[union-attr]
    assert estimate.used_nutrition


def test_nutrients_come_in_catalogue_order(source: Source):
    product = product_of(proteins="15")
    add(product, reference(source, "1", proteins="20", vitamin_c="10"))

    codes = [n.code for n in build_estimate(product).nutrients]

    order = {n.code: (n.display_order, n.code) for n in Nutrient.objects.all()}
    assert codes == sorted(codes, key=lambda c: order[c])
    assert codes.index("fat") < codes.index("vitamin_c")


def test_a_declared_nutrient_no_ingredient_gives_is_listed_without_an_estimate(
    source: Source,
):
    product = product_of(vitamin_c="30")
    add(product, reference(source, "1"))

    vitamin = nutrients_of(build_estimate(product))["vitamin_c"]

    assert vitamin.estimated is None
    assert vitamin.coverage is None
    assert vitamin.confidence is None
    assert vitamin.declared is not None
    assert vitamin.check is not None
    assert vitamin.check.verdict == "not_estimated"


def test_a_label_the_ingredients_cannot_give_is_a_warning_with_its_nutrient(
    source: Source,
):
    product = product_of(proteins="15", energy="500")
    add(product, reference(source, "1", proteins="20", energy="1600"))
    add(product, reference(source, "2", proteins="10", energy="1000"))

    with translation.override("en"):
        estimate = build_estimate(product)

    (warning,) = estimate.warnings
    assert (warning.problem, warning.nutrients) == ("declared_below", ["energy"])
    assert warning.message.startswith("Energy: the label declares 500 kJ")
    energy = nutrients_of(estimate)["energy"]
    assert energy.check is not None
    assert energy.check.verdict == "declared_below"
    # Non-blocking: the estimate is still there.
    assert energy.estimated is not None


def test_names_follow_the_language_served(source: Source):
    product = product_of(proteins="15")
    add(product, reference(source, "1", proteins="20"))

    with translation.override("fr"):
        estimate = build_estimate(product)

    assert nutrients_of(estimate)["proteins"].name == "Protéines"


# ----------------------------------------------------------------------------
# Vitamin A is one nutrient read two ways
# ----------------------------------------------------------------------------
def test_the_second_reading_of_vitamin_a_is_in_its_entry_and_not_an_entry(
    source: Source,
):
    product = product_of(vitamin_a="19")
    add(product, reference(source, "1", retinol="10", beta_carotene="60"))

    estimate = build_estimate(product)

    entries = nutrients_of(estimate)
    assert "vitamin_a_sixth" not in entries
    vitamin_a = entries["vitamin_a"]
    assert vitamin_a.estimated is not None
    assert vitamin_a.estimated.high is not None
    assert vitamin_a.estimated.high < D("18.5")
    (reading,) = vitamin_a.other_readings
    assert reading.name == "Vitamin A (retinol + beta-carotene / 6)"
    assert reading.estimated.low > vitamin_a.estimated.high
    # The label is compared with both, and agrees with the second.
    assert vitamin_a.check is not None
    assert vitamin_a.check.verdict == "agrees"
    assert vitamin_a.check.compared_high is not None
    assert vitamin_a.check.compared_high >= reading.estimated.low


def test_a_nutrient_read_one_way_has_no_other_readings(source: Source):
    product = product_of(proteins="15")
    add(product, reference(source, "1", proteins="20"))

    assert nutrients_of(build_estimate(product))["proteins"].other_readings == []


# ----------------------------------------------------------------------------
# The ingredients
# ----------------------------------------------------------------------------
def test_ingredients_are_a_tree_in_the_order_of_the_label(source: Source):
    product = product_of()
    dates = add(product, reference(source, "1"), "60")
    add(product, reference(source, "2"), None, parent=dates)
    add(product, reference(source, "3"), "40")

    estimate = build_estimate(product)

    first, second = estimate.ingredients
    assert [i.reference.name for i in (first, second)] == [
        "reference 1",
        "reference 3",
    ]
    (child,) = first.sub_ingredients
    assert child.reference.name == "reference 2"
    assert child.sub_ingredients == []


def test_a_declared_percentage_and_its_estimate_are_separate_fields(source: Source):
    product = product_of()
    add(product, reference(source, "1"), "60")
    add(product, reference(source, "2"))

    declared, undeclared = build_estimate(product).ingredients

    # The label's own figure, and the interval it makes with its rounding.
    assert declared.declared == D("60")
    assert declared.estimated is not None
    assert D("59.5") <= declared.estimated.low <= declared.estimated.point
    assert declared.estimated.point == D("60")
    # Nothing declared: nothing in `declared`, and an estimate all the same.
    assert undeclared.declared is None
    assert undeclared.estimated is not None
    assert undeclared.estimated.high is not None
    assert undeclared.estimated.high >= D("39")


def test_the_reference_is_given_with_its_status(source: Source):
    product = product_of()
    ref = reference(source, "1")
    ReferenceIngredient.objects.filter(pk=ref.pk).update(
        status=ReferenceIngredient.Status.CURATED
    )
    add(product, ref)

    (ingredient,) = build_estimate(product).ingredients

    served = ingredient.reference.model_dump()
    assert (served["id"], served["status"]) == (ref.pk, "curated")


def test_contradicting_percentages_have_no_estimate_and_say_so(source: Source):
    product = product_of()
    add(product, reference(source, "1"), "70")
    add(product, reference(source, "2"), "50")
    add(product, reference(source, "3"))

    estimate = build_estimate(product)

    assert [i.estimated for i in estimate.ingredients] == [None, None, None]
    assert [i.declared for i in estimate.ingredients] == [D("70"), D("50"), None]
    assert estimate.nutrients == []
    assert "impossible" in [w.problem for w in estimate.warnings]


def test_a_product_without_ingredients_has_an_empty_estimate(source: Source):
    estimate = build_estimate(product_of(energy="500"))

    assert estimate.ingredients == []
    # Its declaration is still listed.
    assert [(n.code, n.estimated) for n in estimate.nutrients] == [("energy", None)]


# ----------------------------------------------------------------------------
# Where it comes from
# ----------------------------------------------------------------------------
def test_the_sources_the_estimate_draws_on_come_with_their_attribution(source: Source):
    product = product_of()
    add(product, reference(source, "1"))
    # A source nothing in the product draws on is not credited.
    unused = Source.objects.create(code="other", name="Other", attribution="Other.")
    SourceFood.objects.create(source=unused, code="x")

    (credited,) = build_estimate(product).sources

    assert credited.code == "ciqual-2025"
    assert credited.attribution == ATTRIBUTION
    assert (credited.name, credited.version) == ("Ciqual", "2025")


def test_a_source_used_by_several_ingredients_is_credited_once(source: Source):
    product = product_of()
    add(product, reference(source, "1"))
    add(product, reference(source, "2"))

    assert len(build_estimate(product).sources) == 1


def test_the_caveat_on_processing_is_always_there(source: Source):
    estimate = build_estimate(product_of())

    assert "not modelled" in estimate.caveat


# ----------------------------------------------------------------------------
# The cost
# ----------------------------------------------------------------------------
def test_an_estimate_is_served_in_a_few_queries_however_many_ingredients(
    source: Source, django_assert_max_num_queries: Any
):
    product = product_of(proteins="15", energy="500")
    for i in range(6):
        add(product, reference(source, str(i), vitamin_c=str(i + 1)))

    # What the estimate takes (5 + 6 + 1), the catalogue, the ingredients and the
    # sources.
    with django_assert_max_num_queries(5 + 6 + 1 + 3):
        build_estimate(product)
