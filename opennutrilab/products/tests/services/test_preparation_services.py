from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import Product
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.preparation_services import (
    PreparationConversionError,
)
from opennutrilab.products.services.preparation_services import convert_to_preparation
from opennutrilab.products.services.preparation_services import (
    make_preparations_of_listed_parts,
)
from opennutrilab.products.services.preparation_services import parts_seen

if TYPE_CHECKING:
    from opennutrilab.products.services.reference_services import Item

pytestmark = pytest.mark.django_db


def product(barcode: str = "3017620422003") -> Product:
    return Product.objects.create(barcode=barcode, name=barcode)


def listed(
    reference: ReferenceIngredient, *parts: ReferenceIngredient, on: Product
) -> Ingredient:
    """The reference on a label, with the parts that label lists for it."""
    ingredient = Ingredient.objects.create(product=on, reference=reference)
    for part in parts:
        Ingredient.objects.create(product=on, parent=ingredient, reference=part)
    return ingredient


@pytest.fixture
def milk() -> ReferenceIngredient:
    return ReferenceIngredient.objects.create(name_en="milk", name_fr="lait")


@pytest.fixture
def salt() -> ReferenceIngredient:
    return ReferenceIngredient.objects.create(name_en="salt", name_fr="sel")


@pytest.fixture
def mozzarella() -> ReferenceIngredient:
    return ReferenceIngredient.objects.create(
        name_en="mozzarella", name_fr="mozzarelle", description="A cheese."
    )


# ----------------------------------------------------------------------------
# The parts seen
# ----------------------------------------------------------------------------
def test_the_parts_seen_are_the_references_listed_under_it_once_each(
    mozzarella: ReferenceIngredient,
    milk: ReferenceIngredient,
    salt: ReferenceIngredient,
):
    listed(mozzarella, milk, salt, on=product("1"))
    listed(mozzarella, salt, on=product("2"))
    listed(milk, salt, on=product("3"))  # Not under the mozzarella.

    assert parts_seen(mozzarella) == [milk, salt]


def test_a_part_that_is_a_preparation_is_one_but_not_an_additive_or_the_reference(
    mozzarella: ReferenceIngredient, milk: ReferenceIngredient
):
    brine = Preparation.objects.create(name_en="brine")
    citric = Additive.objects.create(name_en="citric acid", code="E330")
    label = product()
    parent = listed(mozzarella, milk, mozzarella, on=label)
    Ingredient.objects.create(product=label, parent=parent, preparation=brine)
    Ingredient.objects.create(product=label, parent=parent, additive=citric)

    assert parts_seen(mozzarella) == [milk, brine]


def test_a_reference_never_seen_with_parts_has_none(mozzarella: ReferenceIngredient):
    listed(mozzarella, on=product())

    assert parts_seen(mozzarella) == []


# ----------------------------------------------------------------------------
# Converting
# ----------------------------------------------------------------------------
def test_the_names_the_status_and_the_notes_move_to_the_preparation(
    mozzarella: ReferenceIngredient,
):
    mozzarella.status = ReferenceIngredient.Status.CURATED
    mozzarella.save()

    preparation = convert_to_preparation(mozzarella)

    assert (preparation.name_en, preparation.name_fr) == ("mozzarella", "mozzarelle")
    assert preparation.status == Preparation.Status.CURATED
    assert preparation.description == "A cheese."


def test_the_source_foods_become_the_preparations(mozzarella: ReferenceIngredient):
    ciqual = Source.objects.create(code="ciqual-2025", name="Ciqual")
    foods = [SourceFood.objects.create(source=ciqual, code=code) for code in ("1", "2")]
    mozzarella.source_foods.set(foods)

    preparation = convert_to_preparation(mozzarella)

    assert set(preparation.source_foods.all()) == set(foods)
    assert SourceFood.objects.count() == len(foods)


def test_the_components_are_the_parts_seen_and_the_curator_is_told_to_check(
    mozzarella: ReferenceIngredient,
    milk: ReferenceIngredient,
    salt: ReferenceIngredient,
):
    listed(mozzarella, milk, salt, on=product("1"))
    listed(mozzarella, milk, on=product("2"))

    preparation = convert_to_preparation(mozzarella)

    assert set(preparation.components.all()) == {milk, salt}
    assert preparation.description.startswith("A cheese.\n")
    assert "to check" in preparation.description


def test_the_preparations_among_the_parts_become_preparation_components(
    mozzarella: ReferenceIngredient, milk: ReferenceIngredient
):
    brine = Preparation.objects.create(name_en="brine")
    label = product()
    root = listed(mozzarella, milk, on=label)
    Ingredient.objects.create(product=label, parent=root, preparation=brine)

    preparation = convert_to_preparation(mozzarella)

    assert list(preparation.components.all()) == [milk]
    assert list(preparation.preparation_components.all()) == [brine]


def test_the_parts_of_the_label_being_read_are_components_each_once(
    mozzarella: ReferenceIngredient,
    milk: ReferenceIngredient,
    salt: ReferenceIngredient,
):
    listed(mozzarella, milk, on=product())
    brine = Preparation.objects.create(name_en="brine")

    preparation = convert_to_preparation(mozzarella, [salt, milk, brine, mozzarella])

    assert set(preparation.components.all()) == {milk, salt}
    assert list(preparation.preparation_components.all()) == [brine]


def test_without_parts_seen_there_is_no_component_and_no_note(
    mozzarella: ReferenceIngredient,
):
    listed(mozzarella, on=product())

    preparation = convert_to_preparation(mozzarella)

    assert not preparation.components.exists()
    assert preparation.description == "A cheese."


def test_every_ingredient_that_used_it_points_to_the_preparation_in_place(
    mozzarella: ReferenceIngredient,
    milk: ReferenceIngredient,
    salt: ReferenceIngredient,
):
    """Same rows: percentage, product, parent and the label's parts are kept."""
    first, second = product("1"), product("2")
    root = listed(mozzarella, milk, salt, on=first)
    root.percentage = Decimal("6.00")
    root.save()
    pizza = Ingredient.objects.create(product=second, reference=salt)
    nested = Ingredient.objects.create(
        product=second, parent=pizza, reference=mozzarella
    )
    before = Ingredient.objects.count()

    preparation = convert_to_preparation(mozzarella)

    assert Ingredient.objects.count() == before
    root.refresh_from_db()
    nested.refresh_from_db()
    assert (root.preparation, root.reference) == (preparation, None)
    assert root.percentage == Decimal("6.00")
    assert (nested.preparation, nested.reference) == (preparation, None)
    assert nested.parent == pizza
    # What the label lists for it is still its children.
    assert [(c.reference, c.preparation) for c in root.sub_ingredients.all()] == [
        (milk, None),
        (salt, None),
    ]
    assert preparation.usages.count() == 2  # noqa: PLR2004


def test_the_reference_is_deleted_and_nothing_else_is_touched(
    mozzarella: ReferenceIngredient, milk: ReferenceIngredient
):
    listed(mozzarella, milk, on=product())

    convert_to_preparation(mozzarella)

    assert not ReferenceIngredient.objects.filter(name_en="mozzarella").exists()
    assert list(ReferenceIngredient.objects.all()) == [milk]
    assert Preparation.objects.count() == 1


def test_a_preparation_made_of_the_reference_is_made_of_the_preparation(
    mozzarella: ReferenceIngredient, salt: ReferenceIngredient
):
    pizza = Preparation.objects.create(name_en="pizza")
    pizza.components.add(mozzarella, salt)

    preparation = convert_to_preparation(mozzarella)

    assert list(pizza.components.all()) == [salt]
    assert list(pizza.preparation_components.all()) == [preparation]


def test_a_reference_nobody_used_is_converted_too(mozzarella: ReferenceIngredient):
    preparation = convert_to_preparation(mozzarella)

    assert not preparation.usages.exists()
    assert not ReferenceIngredient.objects.exists()


# ----------------------------------------------------------------------------
# What is refused, and leaves everything as it was
# ----------------------------------------------------------------------------
def test_a_name_a_preparation_has_is_refused(
    mozzarella: ReferenceIngredient, milk: ReferenceIngredient
):
    listed(mozzarella, milk, on=product())
    # The same English name, whatever its case.
    other = Preparation.objects.create(name_en="Mozzarella")

    with pytest.raises(PreparationConversionError, match="already has the name"):
        convert_to_preparation(mozzarella)

    assert list(Preparation.objects.all()) == [other]
    assert ReferenceIngredient.objects.filter(pk=mozzarella.pk).exists()
    assert mozzarella.usages.count() == 1


def test_the_same_word_in_the_other_language_is_not_a_name_in_use(
    mozzarella: ReferenceIngredient,
):
    Preparation.objects.create(name_en="mozzarelle")

    preparation = convert_to_preparation(mozzarella)

    assert preparation.name_fr == "mozzarelle"


def test_a_name_taken_between_the_check_and_the_write_is_refused_cleanly(
    mozzarella: ReferenceIngredient, milk: ReferenceIngredient
):
    """Another request can create the preparation after the lookup."""
    listed(mozzarella, milk, on=product())
    Preparation.objects.create(name_en="mozzarella")

    with (
        patch("opennutrilab.products.services.preparation_services.ensure_convertible"),
        pytest.raises(PreparationConversionError, match="already has the name"),
    ):
        convert_to_preparation(mozzarella)

    assert mozzarella.usages.count() == 1
    assert ReferenceIngredient.objects.filter(pk=mozzarella.pk).exists()


# ----------------------------------------------------------------------------
# The rule: what a label lists the parts of is a preparation
# ----------------------------------------------------------------------------
def label_of(*items: IngredientInput) -> list[IngredientInput]:
    return list(items)


def ingredient(name: str, *parts: IngredientInput) -> IngredientInput:
    return IngredientInput(name=name, sub_ingredients=list(parts))


def test_a_reference_whose_parts_the_label_lists_is_made_a_preparation(
    mozzarella: ReferenceIngredient,
    milk: ReferenceIngredient,
    salt: ReferenceIngredient,
):
    items = label_of(ingredient("mozzarella", ingredient("lait"), ingredient("sel")))
    linked: dict[str, Item] = {"mozzarella": mozzarella, "lait": milk, "sel": salt}

    result = make_preparations_of_listed_parts(items, linked)

    preparation = Preparation.objects.get()
    assert result["mozzarella"] == preparation
    assert (result["lait"], result["sel"]) == (milk, salt)
    assert set(preparation.components.all()) == {milk, salt}
    assert not ReferenceIngredient.objects.filter(pk=mozzarella.pk).exists()


def test_a_reference_without_parts_stays_one(mozzarella: ReferenceIngredient):
    items = label_of(ingredient("mozzarella"))

    result = make_preparations_of_listed_parts(items, {"mozzarella": mozzarella})

    assert result["mozzarella"] == mozzarella
    assert not Preparation.objects.exists()


def test_a_preparation_and_an_additive_with_parts_are_left_as_they_are(
    milk: ReferenceIngredient,
):
    brine = Preparation.objects.create(name_en="brine")
    citric = Additive.objects.create(name_en="citric acid", code="E330")
    items = label_of(
        ingredient("brine", ingredient("lait")), ingredient("E330", ingredient("lait"))
    )

    result = make_preparations_of_listed_parts(
        items, {"brine": brine, "e330": citric, "lait": milk}
    )

    assert (result["brine"], result["e330"]) == (brine, citric)
    assert Preparation.objects.get() == brine
    assert not brine.components.exists()


def test_the_parts_come_first_so_a_part_with_parts_is_a_preparation_in_its_parent(
    milk: ReferenceIngredient,
):
    meatball = ReferenceIngredient.objects.create(name_en="meatball")
    beans = ReferenceIngredient.objects.create(name_en="cooked beans")
    items = label_of(
        ingredient(
            "meatball",
            ingredient("cooked beans", ingredient("milk")),
            ingredient("milk"),
        )
    )

    result = make_preparations_of_listed_parts(
        items, {"meatball": meatball, "cooked beans": beans, "milk": milk}
    )

    meatball_preparation = Preparation.objects.get(name_en="meatball")
    beans_preparation = Preparation.objects.get(name_en="cooked beans")
    assert (result["meatball"], result["cooked beans"]) == (
        meatball_preparation,
        beans_preparation,
    )
    assert list(meatball_preparation.preparation_components.all()) == [
        beans_preparation
    ]
    assert list(meatball_preparation.components.all()) == [milk]
    assert list(beans_preparation.components.all()) == [milk]
    assert not ReferenceIngredient.objects.filter(
        name_en__in=["meatball", "cooked beans"]
    )


def test_a_name_listed_twice_is_a_preparation_wherever_it_is_listed(
    mozzarella: ReferenceIngredient, milk: ReferenceIngredient
):
    items = label_of(
        ingredient("mozzarella"),
        ingredient("pizza", ingredient("mozzarella", ingredient("lait"))),
    )
    pizza = ReferenceIngredient.objects.create(name_en="pizza")
    linked: dict[str, Item] = {"mozzarella": mozzarella, "pizza": pizza, "lait": milk}

    result = make_preparations_of_listed_parts(items, linked)

    assert isinstance(result["mozzarella"], Preparation)
    assert isinstance(result["pizza"], Preparation)


def test_a_part_that_is_the_name_of_its_whole_is_not_its_own_component(
    mozzarella: ReferenceIngredient, salt: ReferenceIngredient
):
    # "Dattes (dattes, farine de riz)": the dates are in the dates' recipe.
    items = label_of(
        ingredient("mozzarella", ingredient("mozzarella"), ingredient("sel"))
    )

    linked: dict[str, Item] = {"mozzarella": mozzarella, "sel": salt}

    dates = make_preparations_of_listed_parts(items, linked)["mozzarella"]

    assert isinstance(dates, Preparation)
    assert list(dates.components.all()) == [salt]


def test_a_reference_that_cannot_be_converted_stays_a_reference(
    mozzarella: ReferenceIngredient, milk: ReferenceIngredient
):
    Preparation.objects.create(name_en="mozzarella")
    items = label_of(ingredient("mozzarella", ingredient("lait")))

    result = make_preparations_of_listed_parts(
        items, {"mozzarella": mozzarella, "lait": milk}
    )

    assert result["mozzarella"] == mozzarella
    assert ReferenceIngredient.objects.filter(pk=mozzarella.pk).exists()
