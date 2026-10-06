from decimal import Decimal
from unittest.mock import patch

import pytest

from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.additive_services import AdditiveConversionError
from opennutrilab.products.services.additive_services import additives_known_as
from opennutrilab.products.services.additive_services import convert_to_additive

pytestmark = pytest.mark.django_db


def product(barcode: str = "3017620422003") -> Product:
    return Product.objects.create(barcode=barcode, name=barcode)


@pytest.fixture
def citric() -> Additive:
    return Additive.objects.create(
        name_en="Citric acid", name_fr="Acide citrique", code="E330"
    )


# ----------------------------------------------------------------------------
# Which references are known as additives
# ----------------------------------------------------------------------------
def test_a_reference_with_the_name_of_an_additive_is_known_as_it(citric: Additive):
    by_french = ReferenceIngredient.objects.create(name_fr="ACIDE  citrique")
    by_english = ReferenceIngredient.objects.create(name_en="citric acid")
    other = ReferenceIngredient.objects.create(name_en="milk")

    known = additives_known_as([by_french, by_english, other])

    assert known[by_french.pk] == (citric, True)
    assert known[by_english.pk] == (citric, True)
    assert other.pk not in known


def test_a_plural_or_a_singular_is_a_likely_match_and_not_a_sure_one():
    lecithins = Additive.objects.create(name_fr="Lécithines", name_en="Lecithins")
    pectin = Additive.objects.create(name_en="pectin")
    singular = ReferenceIngredient.objects.create(name_fr="lécithine")
    plural = ReferenceIngredient.objects.create(name_en="pectins")

    known = additives_known_as([singular, plural])

    assert known[singular.pk] == (lecithins, False)
    assert known[plural.pk] == (pectin, False)


def test_a_name_is_compared_in_its_own_language_only():
    """ "Raisin" is a grape in French and a dried grape in English."""
    Additive.objects.create(name_fr="raisin", code="E999")
    dried = ReferenceIngredient.objects.create(name_en="raisin")

    assert additives_known_as([dried]) == {}


def test_a_sure_match_wins_over_a_likely_one(citric: Additive):
    Additive.objects.create(name_en="citric acids", code="E331")
    reference = ReferenceIngredient.objects.create(
        name_en="citric acid", name_fr="acide citriques"
    )

    assert additives_known_as([reference])[reference.pk] == (citric, True)


def test_nothing_is_known_with_no_additive_or_no_name(db: None):
    reference = ReferenceIngredient.objects.create(name_fr="lait")

    assert additives_known_as([reference]) == {}
    assert additives_known_as([]) == {}


# ----------------------------------------------------------------------------
# A new additive
# ----------------------------------------------------------------------------
def test_a_reference_that_is_not_known_becomes_a_new_additive():
    reference = ReferenceIngredient.objects.create(
        name_en="xanthan", name_fr="gomme xanthane", description="A gum."
    )
    reference.status = ReferenceIngredient.Status.CURATED
    reference.save()
    ciqual = Source.objects.create(code="ciqual-2025", name="Ciqual")
    food = SourceFood.objects.create(source=ciqual, code="1")
    reference.source_foods.add(food)

    additive, merged = convert_to_additive(reference)

    assert not merged
    assert (additive.name_en, additive.name_fr) == ("xanthan", "gomme xanthane")
    assert (additive.description, additive.status) == ("A gum.", "curated")
    assert additive.code == additive.function == ""
    assert list(additive.source_foods.all()) == [food]
    assert not ReferenceIngredient.objects.exists()


def test_the_ingredients_that_used_it_point_to_the_additive_in_place():
    reference = ReferenceIngredient.objects.create(name_fr="gomme xanthane")
    milk = ReferenceIngredient.objects.create(name_fr="lait")
    first, second = product("1"), product("2")
    root = Ingredient.objects.create(
        product=first, reference=reference, percentage=Decimal("0.5")
    )
    Ingredient.objects.create(product=first, parent=root, reference=milk)
    other_root = Ingredient.objects.create(product=second, reference=milk)
    nested = Ingredient.objects.create(
        product=second, parent=other_root, reference=reference
    )
    before = Ingredient.objects.count()

    additive, _merged = convert_to_additive(reference)

    assert Ingredient.objects.count() == before
    root.refresh_from_db()
    nested.refresh_from_db()
    assert (root.additive, root.reference, root.percentage) == (
        additive,
        None,
        Decimal("0.50"),
    )
    assert (nested.additive, nested.parent) == (additive, other_root)
    # What the label lists for it is still its children.
    assert [c.reference for c in root.sub_ingredients.all()] == [milk]
    assert additive.usages.count() == 2  # noqa: PLR2004


def test_a_reference_nobody_used_is_converted_too():
    reference = ReferenceIngredient.objects.create(name_fr="gomme xanthane")

    additive, _merged = convert_to_additive(reference)

    assert not additive.usages.exists()
    assert not ReferenceIngredient.objects.exists()


# ----------------------------------------------------------------------------
# Merged into the additive that has the name
# ----------------------------------------------------------------------------
def test_a_reference_known_as_an_additive_is_merged_into_it(citric: Additive):
    reference = ReferenceIngredient.objects.create(
        name_en="citric acid", name_fr="acide citrique"
    )
    root = Ingredient.objects.create(product=product(), reference=reference)

    additive, merged = convert_to_additive(reference)

    assert merged
    assert additive == citric
    assert Additive.objects.count() == 1
    root.refresh_from_db()
    assert (root.additive, root.reference) == (citric, None)
    assert not ReferenceIngredient.objects.exists()


def test_the_additive_keeps_what_it_has_and_is_completed_from_the_reference(
    citric: Additive,
):
    citric.status = Additive.Status.CURATED
    citric.function = Additive.Function.ACID
    citric.description = "Imported."
    citric.save()
    Additive.objects.filter(pk=citric.pk).update(name_fr="")
    ciqual = Source.objects.create(code="ciqual-2025", name="Ciqual")
    food = SourceFood.objects.create(source=ciqual, code="1")
    reference = ReferenceIngredient.objects.create(
        name_en="citric acid", name_fr="acide citrique", description="Seen on a label."
    )
    reference.source_foods.add(food)

    convert_to_additive(reference)

    citric.refresh_from_db()
    # Its own: the code, the class, the status. Completed: the French name, the
    # notes and the foods.
    assert (citric.code, citric.function, citric.status) == ("E330", "acid", "curated")
    assert citric.name_fr == "acide citrique"
    assert citric.description == "Imported.\nSeen on a label."
    assert list(citric.source_foods.all()) == [food]


def test_a_name_another_additive_has_is_not_copied_to_the_one_merged_into():
    Additive.objects.create(name_fr="gomme xanthane", code="E415")
    target = Additive.objects.create(name_en="xanthan gum", code="E999")
    reference = ReferenceIngredient.objects.create(
        name_en="xanthan gum", name_fr="gomme xanthane"
    )

    convert_to_additive(reference)

    target.refresh_from_db()
    assert target.name_fr == ""


def test_a_likely_match_is_merged_too_when_it_is_asked_for():
    lecithins = Additive.objects.create(name_fr="Lécithines", code="E322")
    reference = ReferenceIngredient.objects.create(name_fr="lécithine")
    Ingredient.objects.create(product=product(), reference=reference)

    additive, merged = convert_to_additive(reference)

    assert (additive, merged) == (lecithins, True)


# ----------------------------------------------------------------------------
# What is refused, and leaves everything as it was
# ----------------------------------------------------------------------------
def test_a_reference_that_is_a_component_of_a_preparation_is_refused():
    reference = ReferenceIngredient.objects.create(name_fr="gomme xanthane")
    sauce = Preparation.objects.create(name_en="sauce")
    sauce.components.add(reference)

    with pytest.raises(AdditiveConversionError, match="component of sauce"):
        convert_to_additive(reference)

    assert ReferenceIngredient.objects.filter(pk=reference.pk).exists()
    assert not Additive.objects.exists()


def test_a_name_a_preparation_has_is_refused_for_a_new_additive():
    reference = ReferenceIngredient.objects.create(name_en="gnocchi")
    Preparation.objects.create(name_en="Gnocchi")

    with pytest.raises(AdditiveConversionError, match="preparation already has"):
        convert_to_additive(reference)

    assert ReferenceIngredient.objects.filter(pk=reference.pk).exists()


def test_two_ingredients_that_would_become_one_are_refused(citric: Additive):
    """The label lists the reference and the additive under one parent."""
    reference = ReferenceIngredient.objects.create(name_en="citric acid")
    label = product()
    Ingredient.objects.create(product=label, reference=reference)
    Ingredient.objects.create(product=label, additive=citric)

    with pytest.raises(AdditiveConversionError, match="both listed"):
        convert_to_additive(reference)

    assert ReferenceIngredient.objects.filter(pk=reference.pk).exists()
    assert Ingredient.objects.filter(reference=reference).count() == 1


def test_a_name_taken_between_the_check_and_the_write_is_refused_cleanly():
    """Another request can create the additive after the lookup."""
    reference = ReferenceIngredient.objects.create(name_en="xanthan gum")
    Ingredient.objects.create(product=product(), reference=reference)
    Additive.objects.create(name_en="Xanthan gum", code="E415")

    with (
        patch(
            "opennutrilab.products.services.additive_services.additives_known_as",
            return_value={},
        ),
        pytest.raises(AdditiveConversionError, match="already has the name"),
    ):
        convert_to_additive(reference)

    assert ReferenceIngredient.objects.filter(pk=reference.pk).exists()
    assert Ingredient.objects.filter(reference=reference).count() == 1
