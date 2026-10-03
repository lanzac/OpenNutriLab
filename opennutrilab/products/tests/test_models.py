from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import translation

from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient

BARCODE = "3229820794556"


@pytest.fixture
def product(db: None) -> Product:
    return Product.objects.create(barcode=BARCODE, name="muesli protéines")


@pytest.fixture
def ciqual_carrot(db: None) -> SourceFood:
    ciqual = Source.objects.create(code="ciqual-2020", name="CIQUAL", version="2020")
    return SourceFood.objects.create(
        source=ciqual, code="20009", name_fr="Carotte, crue", name_en="Carrot, raw"
    )


# ----------------------------------------------------------------------------
# Nutrient catalogue
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_label_declaration_is_in_the_catalogue():
    """The eight nutrients of the EU nutrition declaration, seeded by migration."""
    label = Nutrient.objects.filter(on_label=True)

    assert [(n.code, n.unit, n.parent_id) for n in label] == [
        ("energy", "kJ", None),
        ("fat", "g", None),
        ("saturated_fat", "g", "fat"),
        ("carbohydrates", "g", None),
        ("sugars", "g", "carbohydrates"),
        ("fiber", "g", None),
        ("proteins", "g", None),
        ("salt", "g", None),
    ]
    # Protein as labels compute it (nitrogen x 6.25), not CIQUAL's default.
    assert Nutrient.objects.get(code="proteins").ciqual_code == "25003"


@pytest.mark.django_db
def test_a_nutrient_is_named_in_the_language_served():
    salt = Nutrient.objects.get(code="salt")

    with translation.override("fr-fr"):
        assert salt.name == "Sel"
        assert str(salt) == "Sel (g)"
    with translation.override("en-us"):
        assert salt.name == "Salt"


@pytest.mark.django_db
def test_a_parent_nutrient_cannot_be_deleted_from_under_its_children():
    with pytest.raises(ProtectedError):
        Nutrient.objects.get(code="fat").delete()


# ----------------------------------------------------------------------------
# Products and their declared values
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_product_str(product: Product):
    assert str(product) == "Muesli Protéines"


@pytest.mark.django_db
def test_a_nutrient_is_declared_once_per_product(product: Product):
    salt = Nutrient.objects.get(code="salt")
    ProductNutrient.objects.create(
        product=product, nutrient=salt, amount=Decimal("0.03")
    )

    with transaction.atomic(), pytest.raises(IntegrityError):
        ProductNutrient.objects.create(product=product, nutrient=salt, amount=1)


@pytest.mark.django_db
def test_declared_values_go_with_their_product(product: Product):
    ProductNutrient.objects.create(
        product=product, nutrient=Nutrient.objects.get(code="fat"), amount=9
    )

    product.delete()

    assert not ProductNutrient.objects.exists()


# ----------------------------------------------------------------------------
# Ingredients
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_ingredients_form_a_tree(product: Product):
    dates = Ingredient.objects.create(product=product, name="Dattes", percentage=7)
    Ingredient.objects.create(product=product, parent=dates, name="farine de riz")

    assert [i.name for i in dates.sub_ingredients.all()] == ["farine de riz"]
    assert str(dates) == "Dattes"


@pytest.mark.django_db
def test_removing_a_reference_ingredient_keeps_the_ingredient(product: Product):
    oats = ReferenceIngredient.objects.create(name_fr="flocons d'avoine")
    ingredient = Ingredient.objects.create(
        product=product, name="Flocons d'avoine", reference=oats
    )

    oats.delete()

    ingredient.refresh_from_db()
    assert ingredient.reference is None


# ----------------------------------------------------------------------------
# Sources and reference ingredients
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_source_lists_each_of_its_foods_once(ciqual_carrot: SourceFood):
    with transaction.atomic(), pytest.raises(IntegrityError):
        SourceFood.objects.create(source=ciqual_carrot.source, code="20009")


@pytest.mark.django_db
def test_a_source_value_keeps_how_the_source_published_it(ciqual_carrot: SourceFood):
    """CIQUAL "-" (not measured), "< 0,5" and "traces" all have to survive."""
    vitamin_d = Nutrient.objects.create(
        code="vitamin_d",
        name_en="Vitamin D",
        name_fr="Vitamine D",
        unit="µg",
        group="vitamin",
    )
    not_measured = SourceFoodNutrient.objects.create(
        food=ciqual_carrot, nutrient=vitamin_d, amount=None
    )
    below_limit = SourceFoodNutrient.objects.create(
        food=ciqual_carrot,
        nutrient=Nutrient.objects.get(code="salt"),
        amount=Decimal("0.5"),
        qualifier=SourceFoodNutrient.Qualifier.LESS_THAN,
        confidence="B",
    )

    assert not_measured.amount is None
    assert not_measured.qualifier == SourceFoodNutrient.Qualifier.EXACT
    below_limit.refresh_from_db()
    assert (below_limit.qualifier, below_limit.confidence) == ("less_than", "B")


@pytest.mark.django_db
def test_a_reference_ingredient_draws_on_several_source_foods(
    ciqual_carrot: SourceFood,
):
    other = Source.objects.create(code="manual", name="Saisie manuelle")
    measured = SourceFood.objects.create(source=other, code="1", name_fr="Carotte")
    carrot = ReferenceIngredient.objects.create(name_fr="carotte crue")

    carrot.source_foods.add(ciqual_carrot, measured)

    assert set(carrot.source_foods.all()) == {ciqual_carrot, measured}
    assert str(carrot) == "carotte crue"
