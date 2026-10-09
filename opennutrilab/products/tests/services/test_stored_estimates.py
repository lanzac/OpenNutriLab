from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.core.management import call_command

from opennutrilab.products.models import EstimatedNutrient
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductEstimate
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services import stored_estimates
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.derived_nutrients import ensure_derivations
from opennutrilab.products.services.stored_estimates import compositions
from opennutrilab.products.services.stored_estimates import kept_estimates
from opennutrilab.products.services.stored_estimates import mark_stale

D = Decimal
CONSTITUENTS_FILE = Path(__file__).parents[1] / "data" / "ciqual_const_2025.xml"
MUESLI = "3229820794556"
BREAD = "3228857002245"


@pytest.fixture
def source(db: None) -> Source:
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    ensure_derivations()
    return Source.objects.create(code="ciqual-2025", name="Ciqual", version="2025")


def food(source: Source, code: str, **amounts: str) -> SourceFood:
    made = SourceFood.objects.create(
        source=source, code=code, name_fr=f"Aliment {code}"
    )
    values = {"fat": "0", "carbohydrates": "0", "proteins": "0", **amounts}
    for nutrient, amount in values.items():
        SourceFoodNutrient.objects.create(
            food=made,
            nutrient=Nutrient.objects.get(code=nutrient),
            amount=D(amount),
            confidence="A",
        )
    return made


def reference(source: Source, code: str, **amounts: str) -> ReferenceIngredient:
    ref = ReferenceIngredient.objects.create(
        name_en=f"reference {code}", name_fr=f"fiche {code}"
    )
    ref.source_foods.add(food(source, code, **amounts))
    return ref


def product_of(barcode: str, *refs: ReferenceIngredient) -> Product:
    product = Product.objects.create(barcode=barcode, name=f"Product {barcode}")
    for ref in refs:
        Ingredient.objects.create(product=product, reference=ref)
    return product


@pytest.fixture
def muesli(source: Source) -> Product:
    return product_of(
        MUESLI,
        reference(source, "1", proteins="20", vitamin_c="10"),
        reference(source, "2", proteins="10", vitamin_c="20"),
    )


@contextmanager
def counted() -> Iterator[MagicMock]:
    """validate_estimate, watched: how often an estimate is worked out."""
    with patch.object(
        stored_estimates,
        "validate_estimate",
        wraps=stored_estimates.validate_estimate,
    ) as watched:
        yield watched


# ----------------------------------------------------------------------------
# Kept, and worked out again when stale
# ----------------------------------------------------------------------------
def test_an_estimate_is_worked_out_once_and_read_back(muesli: Product):
    with counted() as worked_out:
        first = kept_estimates([muesli])[MUESLI]
        again = kept_estimates([muesli])[MUESLI]

    assert worked_out.call_count == 1
    assert first.keys() == again.keys()
    vitamin_c = again["vitamin_c"]
    assert vitamin_c.low <= vitamin_c.amount
    assert vitamin_c.coverage_point == D(100)
    assert vitamin_c.confidence is not None
    assert not ProductEstimate.objects.get(product=muesli).stale


def test_a_change_to_a_products_ingredients_or_label_makes_its_own_stale(
    source: Source, muesli: Product
):
    bread = product_of(BREAD, reference(source, "3", proteins="9"))
    kept_estimates([muesli, bread])

    Ingredient.objects.filter(product=muesli).first().delete()  # pyright: ignore[reportOptionalMemberAccess]

    assert ProductEstimate.objects.get(product=muesli).stale
    assert not ProductEstimate.objects.get(product=bread).stale

    kept_estimates([muesli])
    ProductNutrient.objects.create(
        product=muesli, nutrient=Nutrient.objects.get(code="proteins"), amount=15
    )
    assert ProductEstimate.objects.get(product=muesli).stale


def test_a_change_to_what_compositions_are_made_of_makes_every_one_stale(
    source: Source, muesli: Product
):
    bread = product_of(BREAD, reference(source, "3", proteins="9"))
    kept_estimates([muesli, bread])

    SourceFoodNutrient.objects.filter(nutrient_id="vitamin_c").update(amount=1)
    assert not ProductEstimate.objects.filter(stale=True).exists()  # update() is silent

    SourceFoodNutrient.objects.filter(nutrient_id="vitamin_c").first().save()  # pyright: ignore[reportOptionalMemberAccess]
    assert ProductEstimate.objects.filter(stale=True).count() == 2  # noqa: PLR2004

    kept_estimates([muesli, bread])
    ReferenceIngredient.objects.get(name_en="reference 3").source_foods.add(
        food(source, "4", proteins="1")
    )
    assert ProductEstimate.objects.filter(stale=True).count() == 2  # noqa: PLR2004


def test_a_stale_estimate_is_worked_out_again_with_what_changed(muesli: Product):
    before = kept_estimates([muesli])[MUESLI]["vitamin_c"].amount

    SourceFoodNutrient.objects.filter(nutrient_id="vitamin_c").update(amount=D(50))
    mark_stale(MUESLI)

    assert kept_estimates([muesli])[MUESLI]["vitamin_c"].amount == D(50) != before


def test_an_estimate_the_solver_fails_on_is_kept_empty_and_logged(
    muesli: Product, caplog: pytest.LogCaptureFixture
):
    with patch.object(
        stored_estimates, "validate_estimate", side_effect=RuntimeError("HiGHS")
    ):
        found = kept_estimates([muesli])

    assert found == {MUESLI: {}}
    assert not ProductEstimate.objects.get(product=muesli).stale
    assert "could not be worked out" in caplog.text


def test_a_product_deleted_takes_its_estimate_with_it(muesli: Product):
    kept_estimates([muesli])

    muesli.delete()

    assert not ProductEstimate.objects.exists()
    assert not EstimatedNutrient.objects.exists()


# ----------------------------------------------------------------------------
# A product's composition
# ----------------------------------------------------------------------------
def test_the_label_gives_what_it_declares_and_the_estimate_the_rest(muesli: Product):
    ProductNutrient.objects.create(
        product=muesli, nutrient=Nutrient.objects.get(code="proteins"), amount=D("15")
    )

    composition = compositions([muesli])[MUESLI]

    # Declared: the label's figure, within its rounding, for the whole product.
    assert composition["proteins"] == (D(15), D("14.5"), D("15.5"), D(100), True)
    vitamin_c = composition["vitamin_c"]
    assert not vitamin_c.declared
    assert D("14.5") <= vitamin_c.amount <= D("15.5")


def test_a_product_with_no_ingredient_has_its_label_only(source: Source):
    product = product_of(BREAD)
    ProductNutrient.objects.create(
        product=product, nutrient=Nutrient.objects.get(code="fat"), amount=D(0)
    )

    assert compositions([product]) == {BREAD: {"fat": (D(0), D(0), D(0), D(100), True)}}


def declare(product: Product, **amounts: str) -> None:
    for code, amount in amounts.items():
        ProductNutrient.objects.create(
            product=product, nutrient=Nutrient.objects.get(code=code), amount=D(amount)
        )


def test_the_sodium_of_a_declared_salt_is_the_labels_with_its_rounding(source: Source):
    product = product_of(BREAD)
    declare(product, salt="1.2")

    sodium = compositions([product])[BREAD]["sodium"]

    # Salt is sodium in mg times 0.0025: 1.2 g of salt is 480 mg of sodium, and the
    # rounding of 1.2 (1.15 to 1.25) carries over.
    assert sodium.amount == D(480)
    assert (sodium.low, sodium.high) == (D(460), D(500))
    assert (sodium.coverage, sodium.declared) == (D(100), True)


def test_a_sodium_the_label_declares_is_not_replaced_by_the_one_of_its_salt(
    source: Source,
):
    product = product_of(BREAD)
    declare(product, salt="1.2", sodium="420")

    assert compositions([product])[BREAD]["sodium"].amount == D(420)


def test_the_sodium_of_a_salt_the_label_does_not_declare_is_the_estimates(
    source: Source,
):
    ingredient = reference(source, "7", sodium="500")
    product = product_of(BREAD, ingredient)

    sodium = compositions([product])[BREAD]["sodium"]

    assert sodium.declared is False
    assert sodium.amount == D(500)


def test_a_declared_salt_gives_the_sodium_over_the_estimate_of_the_ingredients(
    source: Source,
):
    product = product_of(BREAD, reference(source, "7", sodium="2800"))
    declare(product, salt="0.6")

    sodium = compositions([product])[BREAD]["sodium"]

    # What the ingredients could give is not the label's 0.6 g of salt.
    assert sodium.amount == D(240)
    assert sodium.declared is True


# ----------------------------------------------------------------------------
# The command
# ----------------------------------------------------------------------------
def test_the_command_works_out_the_stale_and_the_missing_or_with_all_every_one(
    source: Source, muesli: Product
):
    bread = product_of(BREAD, reference(source, "3", proteins="9"))
    kept_estimates([bread])

    with counted() as worked_out:
        call_command("refresh_estimates")
    assert [c.args[0].pk for c in worked_out.call_args_list] == [MUESLI]

    with counted() as worked_out:
        call_command("refresh_estimates", "--all")
    assert worked_out.call_count == 2  # noqa: PLR2004
