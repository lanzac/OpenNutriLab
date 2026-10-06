from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import translation

from opennutrilab.products.models import Additive
from opennutrilab.products.models import AdditiveNutrient
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Preparation
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
    dates = Ingredient.objects.create(
        product=product,
        reference=ReferenceIngredient.objects.create(name_en="dates"),
        percentage=7,
    )
    Ingredient.objects.create(
        product=product,
        parent=dates,
        reference=ReferenceIngredient.objects.create(name_en="rice flour"),
    )

    assert [str(i) for i in dates.sub_ingredients.all()] == ["rice flour"]
    assert str(dates) == "dates"


@pytest.mark.django_db
def test_an_ingredient_has_no_name_of_its_own(product: Product):
    """It is its reference: the name is the reference's, in the language served."""
    oats = ReferenceIngredient.objects.create(
        name_en="oat flakes", name_fr="flocons d'avoine"
    )
    ingredient = Ingredient.objects.create(product=product, reference=oats)

    with translation.override("fr-fr"):
        assert str(ingredient) == "flocons d'avoine"
    with translation.override("en-us"):
        assert str(ingredient) == "oat flakes"


@pytest.mark.django_db
def test_a_reference_ingredient_in_use_cannot_be_removed(product: Product):
    oats = ReferenceIngredient.objects.create(name_fr="flocons d'avoine")
    ingredient = Ingredient.objects.create(product=product, reference=oats)

    with pytest.raises(ProtectedError):
        oats.delete()

    ingredient.refresh_from_db()
    assert ingredient.reference == oats


@pytest.mark.django_db
def test_a_product_lists_a_reference_once_per_parent(product: Product):
    sugar = ReferenceIngredient.objects.create(name_en="sugar")
    cocoa = ReferenceIngredient.objects.create(name_en="cocoa")
    Ingredient.objects.create(product=product, reference=sugar)
    chocolate = Ingredient.objects.create(product=product, reference=cocoa)
    # The same reference under another parent is a different ingredient.
    Ingredient.objects.create(product=product, parent=chocolate, reference=sugar)

    with transaction.atomic(), pytest.raises(IntegrityError):
        Ingredient.objects.create(product=product, reference=sugar)
    with transaction.atomic(), pytest.raises(IntegrityError):
        Ingredient.objects.create(product=product, parent=chocolate, reference=sugar)


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


@pytest.mark.django_db
def test_a_reference_ingredient_is_to_review_until_curated():
    assert (
        ReferenceIngredient.objects.create(name_en="carrot").status
        == ReferenceIngredient.Status.TO_REVIEW
    )


@pytest.mark.django_db
def test_a_reference_ingredient_name_is_unique_whatever_its_case():
    ReferenceIngredient.objects.create(name_en="Carrot", name_fr="Carotte")

    with transaction.atomic(), pytest.raises(IntegrityError):
        ReferenceIngredient.objects.create(name_en="carrot")
    with transaction.atomic(), pytest.raises(IntegrityError):
        ReferenceIngredient.objects.create(name_en="grated carrot", name_fr="carotte")


@pytest.mark.django_db
def test_a_reference_ingredient_may_lack_one_of_its_names():
    """A name OpenFoodFacts has no French for: blank names do not collide."""
    ReferenceIngredient.objects.create(name_en="carrot")
    ReferenceIngredient.objects.create(name_en="oat flakes")
    ReferenceIngredient.objects.create(name_fr="flocons")
    ReferenceIngredient.objects.create(name_fr="sucre")

    assert ReferenceIngredient.objects.count() == 4  # noqa: PLR2004


@pytest.mark.django_db
def test_a_reference_ingredient_needs_a_name():
    with transaction.atomic(), pytest.raises(IntegrityError):
        ReferenceIngredient.objects.create()


@pytest.mark.django_db
def test_a_reference_ingredient_is_named_in_the_language_served():
    both = ReferenceIngredient.objects.create(name_en="carrot", name_fr="carotte")
    only_english = ReferenceIngredient.objects.create(name_en="oat flakes")
    only_french = ReferenceIngredient.objects.create(name_fr="sucre")

    with translation.override("fr-fr"):
        assert [r.name for r in (both, only_english, only_french)] == [
            "carotte",
            "oat flakes",
            "sucre",
        ]
    with translation.override("en-us"):
        assert [r.name for r in (both, only_english, only_french)] == [
            "carrot",
            "oat flakes",
            "sucre",
        ]


@pytest.mark.django_db
def test_a_curated_reference_needs_its_english_name():
    """It is the key: a reference to review may lack it, a curated one not."""
    to_review = ReferenceIngredient.objects.create(name_fr="carotte")
    curated = ReferenceIngredient.Status.CURATED

    with transaction.atomic(), pytest.raises(IntegrityError):
        ReferenceIngredient.objects.create(name_fr="sucre", status=curated)
    with pytest.raises(ValidationError, match="English name"):
        ReferenceIngredient(name_fr="sucre", status=curated).full_clean()

    to_review.name_en = "carrot"
    to_review.status = curated
    to_review.save()
    to_review.refresh_from_db()
    assert to_review.status == curated


# ----------------------------------------------------------------------------
# Preparations
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_preparation_is_named_like_a_reference():
    mozzarella = Preparation.objects.create(name_en="mozzarella", name_fr="mozzarella")
    only_english = Preparation.objects.create(name_en="gnocchi")

    with translation.override("fr-fr"):
        assert (str(mozzarella), str(only_english)) == ("mozzarella", "gnocchi")
    assert Preparation.Status(mozzarella.status) is Preparation.Status.TO_REVIEW


@pytest.mark.django_db
def test_a_preparation_name_is_unique_whatever_its_case():
    Preparation.objects.create(name_en="Mozzarella", name_fr="Mozzarella")

    with transaction.atomic(), pytest.raises(IntegrityError):
        Preparation.objects.create(name_en="mozzarella")
    with transaction.atomic(), pytest.raises(IntegrityError):
        Preparation.objects.create(name_en="fresh mozzarella", name_fr="mozzarella")


@pytest.mark.django_db
def test_a_preparation_needs_a_name_and_a_curated_one_its_english_name():
    curated = Preparation.Status.CURATED

    with transaction.atomic(), pytest.raises(IntegrityError):
        Preparation.objects.create()
    with transaction.atomic(), pytest.raises(IntegrityError):
        Preparation.objects.create(name_fr="gnocchi", status=curated)
    with pytest.raises(ValidationError, match="curated preparation needs"):
        Preparation(name_fr="gnocchi", status=curated).full_clean()


@pytest.mark.django_db
def test_a_preparation_points_to_the_references_it_is_made_of():
    milk = ReferenceIngredient.objects.create(name_en="milk")
    salt = ReferenceIngredient.objects.create(name_en="salt")
    mozzarella = Preparation.objects.create(name_en="mozzarella")

    mozzarella.components.set([milk, salt])

    assert set(mozzarella.components.all()) == {milk, salt}
    assert list(milk.used_in_preparations.all()) == [mozzarella]


@pytest.mark.django_db
def test_a_preparation_draws_on_source_foods_as_a_reference_does(
    ciqual_carrot: SourceFood,
):
    gnocchi = Preparation.objects.create(name_en="gnocchi")

    gnocchi.source_foods.add(ciqual_carrot)

    assert list(Preparation.objects.filter(source_foods=ciqual_carrot)) == [gnocchi]
    # The foods of a reference and those of a preparation are not mixed up.
    assert not ReferenceIngredient.objects.filter(source_foods=ciqual_carrot).exists()


@pytest.mark.django_db
def test_a_name_is_a_reference_or_a_preparation_not_both():
    Preparation.objects.create(name_en="Mozzarella", name_fr="Mozzarella")
    ReferenceIngredient.objects.create(name_en="Milk", name_fr="Lait")

    with pytest.raises(ValidationError) as as_a_reference:
        ReferenceIngredient(name_en="mozzarella").full_clean()
    with pytest.raises(ValidationError) as as_a_preparation:
        Preparation(name_fr="lait").full_clean()

    assert (
        "A preparation already has this name."
        in as_a_reference.value.message_dict["name_en"]
    )
    assert (
        "A reference ingredient already has this name."
        in (as_a_preparation.value.message_dict["name_fr"])
    )


@pytest.mark.django_db
def test_the_same_word_in_another_language_is_not_a_clash():
    """ "Raisin" is a grape in French and a dried grape in English."""
    Preparation.objects.create(name_fr="raisin")

    ReferenceIngredient(name_en="raisin").full_clean()


@pytest.mark.django_db
def test_a_name_does_not_clash_with_itself_when_it_is_edited():
    mozzarella = Preparation.objects.create(name_en="mozzarella")

    mozzarella.description = "Cheese."
    mozzarella.full_clean()


@pytest.mark.django_db
def test_an_ingredient_is_a_reference_a_preparation_or_an_additive(product: Product):
    salt = ReferenceIngredient.objects.create(name_en="salt")
    mozzarella = Preparation.objects.create(name_en="mozzarella")
    citric = Additive.objects.create(name_en="citric acid", code="E330")

    as_reference = Ingredient.objects.create(product=product, reference=salt)
    as_preparation = Ingredient.objects.create(product=product, preparation=mozzarella)
    as_additive = Ingredient.objects.create(product=product, additive=citric)

    assert as_reference.item == salt
    assert as_preparation.item == mozzarella
    assert as_additive.item == citric
    assert (str(as_reference), str(as_preparation), str(as_additive)) == (
        "salt",
        "mozzarella",
        "citric acid (E330)",
    )
    # Two of them, or none: the database refuses it.
    with transaction.atomic(), pytest.raises(IntegrityError):
        Ingredient.objects.create(
            product=product, reference=salt, preparation=mozzarella, parent=as_reference
        )
    with transaction.atomic(), pytest.raises(IntegrityError):
        Ingredient.objects.create(
            product=product, reference=salt, additive=citric, parent=as_reference
        )
    with transaction.atomic(), pytest.raises(IntegrityError):
        Ingredient.objects.create(product=product, parent=as_reference)
    with pytest.raises(ValidationError, match="and only one of them"):
        Ingredient(
            product=product, preparation=mozzarella, additive=citric
        ).full_clean()


@pytest.mark.django_db
def test_a_product_lists_an_additive_once_per_parent(product: Product):
    citric = Additive.objects.create(name_en="citric acid")
    mozzarella = Preparation.objects.create(name_en="mozzarella")
    Ingredient.objects.create(product=product, additive=citric)
    parent = Ingredient.objects.create(product=product, preparation=mozzarella)
    # Under another parent it is a different ingredient.
    Ingredient.objects.create(product=product, parent=parent, additive=citric)

    with transaction.atomic(), pytest.raises(IntegrityError):
        Ingredient.objects.create(product=product, additive=citric)
    with transaction.atomic(), pytest.raises(IntegrityError):
        Ingredient.objects.create(product=product, parent=parent, additive=citric)


@pytest.mark.django_db
def test_a_product_lists_a_preparation_once_per_parent(product: Product):
    mozzarella = Preparation.objects.create(name_en="mozzarella")
    pizza = Preparation.objects.create(name_en="pizza")
    Ingredient.objects.create(product=product, preparation=mozzarella)
    parent = Ingredient.objects.create(product=product, preparation=pizza)
    # Under another parent it is a different ingredient.
    Ingredient.objects.create(product=product, parent=parent, preparation=mozzarella)

    with transaction.atomic(), pytest.raises(IntegrityError):
        Ingredient.objects.create(product=product, preparation=mozzarella)
    with transaction.atomic(), pytest.raises(IntegrityError):
        Ingredient.objects.create(
            product=product, parent=parent, preparation=mozzarella
        )


@pytest.mark.django_db
def test_a_reference_and_a_preparation_do_not_make_each_other_a_duplicate(
    product: Product,
):
    """Two rows with a null reference, or a null preparation, are not equal."""
    salt = ReferenceIngredient.objects.create(name_en="salt")
    sugar = ReferenceIngredient.objects.create(name_en="sugar")
    mozzarella = Preparation.objects.create(name_en="mozzarella")
    gnocchi = Preparation.objects.create(name_en="gnocchi")

    for item in (salt, sugar, mozzarella, gnocchi):
        Ingredient.objects.create(
            product=product,
            **{
                "reference"
                if isinstance(item, ReferenceIngredient)
                else "preparation": item
            },
        )

    assert product.ingredients.count() == 4  # noqa: PLR2004


@pytest.mark.django_db
def test_a_preparation_in_use_cannot_be_removed(product: Product):
    mozzarella = Preparation.objects.create(name_en="mozzarella")
    Ingredient.objects.create(product=product, preparation=mozzarella)

    with pytest.raises(ProtectedError):
        mozzarella.delete()


# ----------------------------------------------------------------------------
# Additives
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_an_additive_is_named_like_a_reference_and_has_a_code_and_a_function():
    citric = Additive.objects.create(
        name_en="citric acid",
        name_fr="acide citrique",
        code="E330",
        function=Additive.Function.ACID,
    )

    with translation.override("fr-fr"):
        assert str(citric) == "acide citrique (E330)"
    assert Additive.Status(citric.status) is Additive.Status.TO_REVIEW
    assert Additive.Function(citric.function).label == "Acid"
    assert str(Additive.objects.create(name_en="carmine")) == "carmine"


@pytest.mark.django_db
def test_an_additive_name_is_unique_whatever_its_case():
    Additive.objects.create(name_en="Citric acid", name_fr="Acide citrique")

    with transaction.atomic(), pytest.raises(IntegrityError):
        Additive.objects.create(name_en="citric acid")
    with transaction.atomic(), pytest.raises(IntegrityError):
        Additive.objects.create(name_en="sour", name_fr="acide citrique")


@pytest.mark.django_db
def test_an_additive_code_is_unique_whatever_its_case_and_may_be_blank():
    Additive.objects.create(name_en="citric acid", code="E330")
    Additive.objects.create(name_en="carmine")
    Additive.objects.create(name_en="annatto")

    with transaction.atomic(), pytest.raises(IntegrityError):
        Additive.objects.create(name_en="other", code="e330")
    with pytest.raises(ValidationError, match="already has this E number"):
        Additive(name_en="other", code="e330").full_clean()


@pytest.mark.django_db
def test_an_additive_code_is_written_the_one_way():
    additive = Additive(name_en="citric acid", code=" e 330 ")

    additive.full_clean()

    assert additive.code == "E330"


@pytest.mark.django_db
def test_an_additive_needs_a_name_and_a_curated_one_its_english_name():
    curated = Additive.Status.CURATED

    with transaction.atomic(), pytest.raises(IntegrityError):
        Additive.objects.create(code="E330")
    with transaction.atomic(), pytest.raises(IntegrityError):
        Additive.objects.create(name_fr="acide citrique", status=curated)
    with pytest.raises(ValidationError, match="curated additive needs"):
        Additive(name_fr="acide citrique", status=curated).full_clean()


@pytest.mark.django_db
def test_an_additive_function_is_one_of_the_closed_list():
    with pytest.raises(ValidationError):
        Additive(name_en="citric acid", function="a_made_up_class").full_clean()
    Additive(name_en="citric acid", function="").full_clean()


@pytest.mark.django_db
def test_an_additive_brings_a_nutrient_once():
    ascorbic = Additive.objects.create(name_en="ascorbic acid", code="E300")
    vitamin_c = Nutrient.objects.create(
        code="vitamin_c",
        name_en="Vitamin C",
        name_fr="Vitamine C",
        unit=Nutrient.Unit.MILLIGRAM,
        group=Nutrient.Group.VITAMIN,
    )

    brought = AdditiveNutrient.objects.create(
        additive=ascorbic,
        nutrient=vitamin_c,
        amount=Decimal(100000),
        note="Pure ascorbic acid is vitamin C.",
    )

    assert list(ascorbic.nutrients.all()) == [brought]
    assert str(brought).startswith("ascorbic acid (E300): 100000")
    with transaction.atomic(), pytest.raises(IntegrityError):
        AdditiveNutrient.objects.create(
            additive=ascorbic, nutrient=vitamin_c, amount=Decimal(1)
        )
    with pytest.raises(ValidationError):
        AdditiveNutrient(
            additive=ascorbic,
            nutrient=Nutrient.objects.get(code="fat"),
            amount=Decimal(-1),
        ).full_clean()


@pytest.mark.django_db
def test_an_additive_draws_on_source_foods_apart_from_the_other_kinds(
    ciqual_carrot: SourceFood,
):
    lecithin = Additive.objects.create(name_en="soy lecithin", code="E322")

    lecithin.source_foods.add(ciqual_carrot)

    assert list(Additive.objects.filter(source_foods=ciqual_carrot)) == [lecithin]
    assert not ReferenceIngredient.objects.filter(source_foods=ciqual_carrot).exists()
    assert not Preparation.objects.filter(source_foods=ciqual_carrot).exists()


@pytest.mark.django_db
def test_an_additive_in_use_cannot_be_deleted(product: Product):
    citric = Additive.objects.create(name_en="citric acid")
    Ingredient.objects.create(product=product, additive=citric)

    with pytest.raises(ProtectedError):
        citric.delete()


@pytest.mark.django_db
def test_a_name_is_one_of_the_three_kinds_only():
    Additive.objects.create(name_en="Citric acid", name_fr="Acide citrique")
    Preparation.objects.create(name_en="Mozzarella")
    ReferenceIngredient.objects.create(name_en="Milk")

    errors = {}
    for label, item in {
        "reference": ReferenceIngredient(name_en="citric acid"),
        "preparation": Preparation(name_fr="acide citrique"),
        "additive_as_preparation": Additive(name_en="mozzarella"),
        "additive_as_reference": Additive(name_en="milk"),
        "reference_as_preparation": ReferenceIngredient(name_en="mozzarella"),
    }.items():
        with pytest.raises(ValidationError) as caught:
            item.full_clean()
        errors[label] = caught.value.message_dict

    assert errors["reference"]["name_en"] == ["An additive already has this name."]
    assert errors["preparation"]["name_fr"] == ["An additive already has this name."]
    assert errors["additive_as_preparation"]["name_en"] == [
        "A preparation already has this name."
    ]
    assert errors["additive_as_reference"]["name_en"] == [
        "A reference ingredient already has this name."
    ]
    assert errors["reference_as_preparation"]["name_en"] == [
        "A preparation already has this name."
    ]


@pytest.mark.django_db
def test_an_additive_name_does_not_clash_with_itself_when_it_is_edited():
    citric = Additive.objects.create(name_en="citric acid", code="E330")

    citric.description = "An acid."
    citric.full_clean()
