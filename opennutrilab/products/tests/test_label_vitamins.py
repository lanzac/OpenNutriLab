import importlib
from decimal import Decimal

import pytest
from crispy_forms.layout import Fieldset
from django.apps import apps
from django.utils import translation

from opennutrilab.products.api.openfoodfacts.services import declared_nutrients_from_off
from opennutrilab.products.forms import ProductForm
from opennutrilab.products.forms import nutrient_field
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.services.ciqual_constituents import CONSTITUENTS
from opennutrilab.products.services.derived_nutrients import CREATED
from opennutrilab.products.services.label_vitamins import LABEL_VITAMINS
from opennutrilab.products.services.label_vitamins import label_fields

BARCODE = "3229820794556"

# The vitamins of the catalogue, as the CIQUAL import makes them.
VITAMINS = {
    "vitamin_a": ("Vitamine A", "µg"),
    "vitamin_b3": ("Vitamine B3 ou PP ou Niacine", "mg"),
    "vitamin_b12": ("Vitamine B12", "µg"),
    "vitamin_c": ("Vitamine C", "mg"),
    "vitamin_d": ("Vitamine D", "µg"),
}


@pytest.fixture
def vitamins(db: None) -> None:
    for order, (code, (name, unit)) in enumerate(VITAMINS.items()):
        Nutrient.objects.create(
            code=code,
            name_en=name,
            name_fr=name,
            unit=unit,
            group=Nutrient.Group.VITAMIN,
            display_order=600 + order,
            **label_fields(code),
        )


def test_every_vitamin_of_a_label_is_one_the_catalogue_makes_in_its_group():
    vitamin = Nutrient.Group.VITAMIN
    made = {c.code for c in CONSTITUENTS.values() if c.group == vitamin}
    made |= {code for code, new in CREATED.items() if new.group == vitamin}

    assert set(LABEL_VITAMINS) <= made
    # The key is unique in the catalogue, and the eight of every label keep theirs.
    assert len(set(LABEL_VITAMINS.values())) == len(LABEL_VITAMINS)


def test_only_the_vitamins_of_a_label_are_made_for_it():
    assert label_fields("vitamin_c") == {"on_label": True, "off_key": "vitamin-c"}
    assert label_fields("vitamin_b3") == {"on_label": True, "off_key": "vitamin-pp"}
    assert label_fields("retinol") == {}
    assert label_fields("fructose") == {}


def test_the_migration_that_puts_the_vitamins_on_the_label_agrees_with_the_module():
    migration = importlib.import_module(
        "opennutrilab.products.migrations.0027_vitamins_on_label"
    )

    assert migration.LABEL_VITAMINS == LABEL_VITAMINS


@pytest.mark.django_db
def test_the_migration_sets_the_vitamins_a_catalogue_has_and_can_be_undone():
    migration = importlib.import_module(
        "opennutrilab.products.migrations.0027_vitamins_on_label"
    )
    Nutrient.objects.create(
        code="vitamin_c",
        name_en="Vitamin C",
        name_fr="Vitamine C",
        unit="mg",
        group="vitamin",
    )
    Nutrient.objects.create(
        code="retinol", name_en="Retinol", name_fr="Rétinol", unit="µg", group="vitamin"
    )

    migration.put_vitamins_on_label(apps, None)

    vitamin_c = Nutrient.objects.get(code="vitamin_c")
    assert (vitamin_c.on_label, vitamin_c.off_key) == (True, "vitamin-c")
    retinol = Nutrient.objects.get(code="retinol")
    assert (retinol.on_label, retinol.off_key) == (False, None)

    migration.take_vitamins_off_label(apps, None)

    vitamin_c.refresh_from_db()
    assert (vitamin_c.on_label, vitamin_c.off_key) == (False, None)


@pytest.mark.usefixtures("vitamins")
def test_the_vitamins_of_an_openfoodfacts_product_are_read_in_the_catalogue_unit():
    # OpenFoodFacts gives every mass in grams.
    nutriments = {
        "vitamin-c_100g": 0.028,
        "vitamin-a_100g": 0.000312,
        "vitamin-b12_100g": 1.88e-07,
        "vitamin-pp_100g": "0.0035",
        "vitamin-d_100g": 0,
        "vitamin-e_100g": 0.0005,
    }

    values = declared_nutrients_from_off(nutriments)

    assert values == {
        "vitamin_c": Decimal(28),
        "vitamin_a": Decimal(312),
        "vitamin_b12": Decimal("0.188"),
        "vitamin_b3": Decimal("3.5"),
        # A zero is a measurement. Vitamin E is not in this catalogue.
        "vitamin_d": Decimal(0),
    }


@pytest.mark.usefixtures("vitamins")
def test_the_form_asks_for_the_vitamins_after_the_other_nutrients_in_a_group():
    with translation.override("fr-fr"):
        form = ProductForm()
        layout = form._get_nutritional_values_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        legend = str(layout[-1].legend)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownArgumentType, reportUnknownMemberType]

    others, group = layout[:-1], layout[-1]
    assert [item.fields[0] for item in others] == [  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        nutrient_field(code)
        for code in (
            "energy",
            "fat",
            "saturated_fat",
            "carbohydrates",
            "sugars",
            "fiber",
            "proteins",
            "salt",
        )
    ]
    assert isinstance(group, Fieldset)
    assert legend == "Vitamines"
    assert [item.fields[0] for item in group.fields] == [  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        nutrient_field(code) for code in VITAMINS
    ]


@pytest.mark.django_db
def test_without_the_vitamins_the_form_has_no_group_for_them():
    form = ProductForm()

    layout = form._get_nutritional_values_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert not any(isinstance(item, Fieldset) for item in layout)


@pytest.mark.usefixtures("vitamins")
def test_save_stores_the_vitamins_the_label_declares():
    form = ProductForm(
        data={
            "barcode": BARCODE,
            "name": "Muesli",
            nutrient_field("vitamin_c"): "28",
            nutrient_field("vitamin_b12"): "0.188",
            nutrient_field("vitamin_d"): "0",
            nutrient_field("vitamin_a"): "",
        }
    )
    assert form.is_valid(), form.errors

    product = form.save()

    assert dict(
        ProductNutrient.objects.filter(product=product).values_list(
            "nutrient_id", "amount"
        )
    ) == {
        "vitamin_c": Decimal(28),
        "vitamin_b12": Decimal("0.188"),
        "vitamin_d": Decimal(0),
    }
