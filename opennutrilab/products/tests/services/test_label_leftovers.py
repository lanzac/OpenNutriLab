from typing import Any

import pytest

from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.api.schemas.inbound import ProductUpdate
from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.label_leftovers import discard_leftovers
from opennutrilab.products.services.label_leftovers import used_by
from opennutrilab.products.services.product_services import create_product
from opennutrilab.products.services.product_services import update_product

pytestmark = pytest.mark.django_db

BARCODE = "3276551080656"
OTHER_BARCODE = "3017620422003"


def made(model: type[Any], **fields: object) -> Any:
    """What a reading of a label makes: to review, with the note of its creation."""
    return model.objects.create(
        status="to_review",
        description="Created from an ingredient list. Language of the label: fr.",
        **fields,
    )


def product_of(*names: str, barcode: str = BARCODE) -> Product:
    """A product saved with ingredients that nothing had the names of."""
    data = ProductCreate.model_validate(
        {
            "barcode": barcode,
            "name": "Baguette",
            "ingredients": [{"name": name, "language": "fr"} for name in names],
        }
    )
    return create_product(data).product


def replace(product: Product, *names: str) -> None:
    update_product(
        product,
        ProductUpdate.model_validate(
            {"ingredients": [{"name": n, "language": "fr"} for n in names]}
        ),
    )


def names() -> set[str]:
    return set(ReferenceIngredient.objects.values_list("name_fr", flat=True))


def test_saving_names_nothing_has_makes_references_to_review():
    product_of("farine de blé", "le personnel manipule les")

    assert {"farine de blé", "le personnel manipule les"} <= names()
    assert set(ReferenceIngredient.objects.values_list("status", flat=True)) == {
        "to_review"
    }


def test_what_a_wrong_reading_made_goes_when_the_ingredients_are_corrected():
    product = product_of("farine de blé", "et diglycérides d'acides gras")

    replace(product, "farine de blé", "mono- et diglycérides d'acides gras")

    assert "et diglycérides d'acides gras" not in names()
    # What the corrected reading still has is kept, new or not.
    assert {"farine de blé", "mono- et diglycérides d'acides gras"} <= names()


def test_the_whole_reading_goes_when_it_is_replaced_by_nothing():
    product = product_of("le personnel manipule les", "baguette farine de blé")

    replace(product)

    assert names() == set()


def test_what_a_wrong_reading_made_goes_when_the_product_is_deleted():
    product = product_of("le personnel manipule les")
    assert "le personnel manipule les" in names()

    product.delete()

    assert names() == set()


def test_what_another_product_uses_stays():
    product = product_of("farine de blé", "sel")
    other = product_of("sel", barcode=OTHER_BARCODE)

    product.delete()

    assert names() == {"sel"}
    assert other.ingredients.count() == 1


def test_a_reference_a_curator_worked_on_stays():
    product = product_of("farine de blé", "levure", "sel", "eau")
    source = Source.objects.create(code="ciqual-2025", name="Ciqual", version="2025")
    food = SourceFood.objects.create(source=source, code="1", name_fr="Levure")
    ReferenceIngredient.objects.filter(name_fr="levure").first().source_foods.add(food)  # pyright: ignore[reportOptionalMemberAccess]
    ReferenceIngredient.objects.filter(name_fr="sel").update(
        status="curated", name_en="Salt"
    )
    ReferenceIngredient.objects.filter(name_fr="eau").update(
        description="Eau du robinet, vérifiée."
    )

    replace(product)

    assert names() == {"levure", "sel", "eau"}


def test_a_reference_with_a_density_stays():
    product = product_of("huile")
    ReferenceIngredient.objects.filter(name_fr="huile").update(
        density_low="0.9", density_high="0.92"
    )

    replace(product)

    assert names() == {"huile"}


def test_a_reference_that_was_not_made_from_a_label_stays():
    # By hand, in the admin: it has no note, and it is not used yet.
    ReferenceIngredient.objects.create(name_fr="à la main", status="to_review")
    product = product_of("sel")

    product.delete()

    assert names() == {"à la main"}


def test_only_what_the_product_used_is_looked_at():
    # Unused, made from a label, but not by this product: not its business.
    made(ReferenceIngredient, name_fr="orpheline")
    product = product_of("sel")

    product.delete()

    assert names() == {"orpheline"}


def test_a_preparation_goes_with_the_references_it_was_made_of():
    product = product_of("sel")
    flour = made(ReferenceIngredient, name_fr="farine")
    mix = made(Preparation, name_fr="mélange")
    mix.components.add(flour)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    Ingredient.objects.create(product=product, preparation=mix)
    Ingredient.objects.create(
        product=product, reference=flour, parent=Ingredient.objects.get(preparation=mix)
    )
    used = used_by(product)
    product.ingredients.all().delete()

    # The salt, the mix and the flour.
    assert discard_leftovers(used) == len(["sel", "mélange", "farine"])
    assert names() == set()
    assert not Preparation.objects.exists()


def test_a_preparation_used_by_another_product_keeps_its_parts():
    product = product_of("sel")
    other = product_of("eau", barcode=OTHER_BARCODE)
    flour = made(ReferenceIngredient, name_fr="farine")
    mix = made(Preparation, name_fr="mélange")
    mix.components.add(flour)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    Ingredient.objects.create(product=product, preparation=mix)
    Ingredient.objects.create(product=other, preparation=mix)
    used = used_by(product)
    product.ingredients.all().delete()

    discard_leftovers(used)

    assert Preparation.objects.filter(name_fr="mélange").exists()
    assert "farine" in names()


def test_an_additive_with_no_code_goes_but_one_with_a_code_stays():
    product = product_of("sel")
    nameless = made(Additive, name_fr="mono", function="emulsifier", code="")
    coded = made(Additive, name_fr="acide citrique", code="E330")
    Ingredient.objects.create(product=product, additive=nameless)
    Ingredient.objects.create(product=product, additive=coded)
    used = used_by(product)
    product.ingredients.all().delete()

    discard_leftovers(used)

    assert list(Additive.objects.values_list("code", flat=True)) == ["E330"]


def test_the_bad_reading_of_a_real_label_leaves_nothing_once_it_is_corrected():
    """The baguette of a bakery: its text was read badly, and then put right."""
    product = product_of(
        "baguette farine de blé",
        "eau",
        "le personnel manipule les",
        "et diglycérides d'acides gras",
    )
    assert len(names()) == len(product.ingredients.all())

    replace(product, "farine de blé", "eau")

    assert names() == {"farine de blé", "eau"}
