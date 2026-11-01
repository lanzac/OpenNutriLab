import importlib
from decimal import Decimal
from pathlib import Path

import pytest
from django.apps import apps
from django.utils import translation

from opennutrilab.crispy_bootstrap_extended.layouts import FoldableGroup
from opennutrilab.products.api.openfoodfacts.services import declared_nutrients_from_off
from opennutrilab.products.forms import ProductForm
from opennutrilab.products.forms import in_table_order
from opennutrilab.products.forms import nutrient_field
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductNutrient
from opennutrilab.products.services.ciqual_constituents import CONSTITUENTS
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.derived_nutrients import CREATED
from opennutrilab.products.services.derived_nutrients import SUMS
from opennutrilab.products.services.derived_nutrients import ensure_derivations
from opennutrilab.products.services.label_nutrients import LABEL_MORE
from opennutrilab.products.services.label_nutrients import LABEL_NUTRIENTS
from opennutrilab.products.services.label_nutrients import LABEL_ONLY
from opennutrilab.products.services.label_nutrients import LABEL_VITAMINS
from opennutrilab.products.services.label_nutrients import ensure_label_only
from opennutrilab.products.services.label_nutrients import label_fields

BARCODE = "3229820794556"
CONSTITUENTS_FILE = Path(__file__).parent / "data" / "ciqual_const_2025.xml"

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


def test_every_nutrient_of_a_label_is_one_the_catalogue_makes():
    made = {c.code for c in CONSTITUENTS.values()}
    made |= set(CREATED) | set(LABEL_ONLY)

    assert set(LABEL_NUTRIENTS) <= made
    keys = [key for key in LABEL_NUTRIENTS.values() if key is not None]
    # The key is unique in the catalogue, and a sum that OpenFoodFacts lacks has none.
    assert len(set(keys)) == len(keys)
    assert [code for code, key in LABEL_NUTRIENTS.items() if key is None] == ["epa_dha"]
    assert set(SUMS) >= {"epa_dha"}


def test_the_parts_of_a_label_are_made_in_the_group_that_tells_what_they_are():
    assert LABEL_ONLY["biotin"].group == Nutrient.Group.VITAMIN
    assert {
        LABEL_ONLY[code].group for code in ("fluoride", "chromium", "molybdenum")
    } == {Nutrient.Group.MINERAL}
    assert LABEL_ONLY["added_sugars"].parent == "sugars"
    assert LABEL_ONLY["trans_fat"].parent == "fat"
    assert CREATED["epa_dha"].parent == "omega_3"
    assert label_fields("epa_dha") == {"on_label": True}
    assert label_fields("calcium") == {"on_label": True, "off_key": "calcium"}
    assert label_fields("butyric_acid") == {}


def test_the_migration_that_puts_more_nutrients_on_the_label_agrees_with_the_module():
    migration = importlib.import_module(
        "opennutrilab.products.migrations.0029_more_label_nutrients"
    )

    assert migration.LABEL_MORE == LABEL_MORE
    assert {
        code: (new.name_en, new.name_fr, new.unit, new.group, new.display_order)
        for code, new in LABEL_ONLY.items()
    } == {
        code: row[:5] for code, row in migration.CREATED.items() if code in LABEL_ONLY
    }
    epa_dha = CREATED["epa_dha"]
    assert migration.CREATED["epa_dha"] == (
        epa_dha.name_en,
        epa_dha.name_fr,
        epa_dha.unit,
        epa_dha.group,
        epa_dha.display_order,
        epa_dha.parent,
    )


@pytest.mark.django_db
def test_the_migration_makes_what_a_filled_catalogue_lacks_and_can_be_undone():
    migration = importlib.import_module(
        "opennutrilab.products.migrations.0029_more_label_nutrients"
    )
    for code, name, unit, group, parent in (
        ("vitamin_c", "Vitamine C", "mg", "vitamin", None),
        ("calcium", "Calcium", "mg", "mineral", None),
        ("polyunsaturated_fat", "AG polyinsaturés", "g", "fatty_acid", "fat"),
        ("omega_3", "Oméga-3", "g", "fatty_acid", "polyunsaturated_fat"),
        ("butyric_acid", "Acide butyrique", "g", "fatty_acid", "saturated_fat"),
    ):
        Nutrient.objects.create(
            code=code,
            name_en=name,
            name_fr=name,
            unit=unit,
            group=group,
            parent_id=parent,
        )

    migration.put_nutrients_on_label(apps, None)

    calcium = Nutrient.objects.get(code="calcium")
    assert (calcium.on_label, calcium.off_key) == (True, "calcium")
    butyric = Nutrient.objects.get(code="butyric_acid")
    assert (butyric.on_label, butyric.off_key) == (False, None)
    biotin = Nutrient.objects.get(code="biotin")
    assert (biotin.unit, biotin.group, biotin.on_label, biotin.off_key) == (
        "µg",
        "vitamin",
        True,
        "biotin",
    )
    epa_dha = Nutrient.objects.get(code="epa_dha")
    assert (epa_dha.parent_id, epa_dha.on_label, epa_dha.off_key) == (
        "omega_3",
        True,
        None,
    )
    assert Nutrient.objects.get(code="added_sugars").parent_id == "sugars"
    product = Product.objects.create(barcode=BARCODE, name="Fresubin")
    ProductNutrient.objects.create(product=product, nutrient=biotin, amount=9)
    ProductNutrient.objects.create(product=product, nutrient=calcium, amount=212)

    migration.take_nutrients_off_label(apps, None)

    assert not Nutrient.objects.filter(code__in=migration.CREATED).exists()
    # What was declared of the nutrients made here goes with them, the rest stays.
    assert list(product.declared_nutrients.values_list("nutrient_id", flat=True)) == [
        "calcium"
    ]
    calcium.refresh_from_db()
    assert (calcium.on_label, calcium.off_key) == (False, None)


@pytest.mark.django_db
def test_the_migration_leaves_a_catalogue_without_the_import_as_it_is():
    migration = importlib.import_module(
        "opennutrilab.products.migrations.0029_more_label_nutrients"
    )
    before = set(Nutrient.objects.values_list("code", flat=True))

    migration.put_nutrients_on_label(apps, None)

    assert set(Nutrient.objects.values_list("code", flat=True)) == before


@pytest.mark.django_db
def test_label_only_nutrients_are_made_once():
    first = ensure_label_only()
    second = ensure_label_only()

    assert (first, second) == (len(LABEL_ONLY), 0)
    added = Nutrient.objects.get(code="added_sugars")
    assert (added.parent_id, added.unit, added.on_label, added.off_key) == (
        "sugars",
        "g",
        True,
        "added-sugars",
    )


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
def test_the_form_asks_for_the_vitamins_in_a_group_after_the_other_nutrients():
    with translation.override("fr-fr"):
        form = ProductForm()
        layout = form._get_nutritional_values_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        names = {group.key: str(group.name) for group in layout}  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType, reportUnknownArgumentType]

    assert all(isinstance(group, FoldableGroup) for group in layout)
    fields = {
        group.key: [item.fields[0] for item in group.fields]  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        for group in layout
    }
    # The vitamins come last, as a group of their own.
    assert list(fields) == ["energy", "macronutrient", "other", "vitamin"]
    assert names["vitamin"] == "Vitamine"
    assert fields["vitamin"] == [nutrient_field(code) for code in VITAMINS]
    # A part of a nutrient is with it, in the order of the label's table.
    assert fields["macronutrient"] == [
        nutrient_field(code)
        for code in (
            "fat",
            "saturated_fat",
            "carbohydrates",
            "sugars",
            "fiber",
            "proteins",
        )
    ]
    assert fields["energy"] == [nutrient_field("energy")]
    assert fields["other"] == [nutrient_field("salt")]


@pytest.fixture
def catalogue(db: None) -> None:
    """The catalogue the CIQUAL import leaves, with what only a label gives."""
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    ensure_derivations()
    ensure_label_only()


@pytest.mark.usefixtures("catalogue")
def test_the_form_asks_for_every_nutrient_of_a_label_in_the_group_that_it_belongs_to():
    with translation.override("fr-fr"):
        form = ProductForm()
        layout = form._get_nutritional_values_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        names = {group.key: str(group.name) for group in layout}  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType, reportUnknownArgumentType]
        labels = {
            code: str(form.fields[nutrient_field(code)].label)
            for code in ("saturated_fat", "monounsaturated_fat", "epa_dha", "calcium")
        }

    fields = {
        group.key: [item.fields[0] for item in group.fields]  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        for group in layout
    }
    assert list(fields) == [
        "energy",
        "macronutrient",
        "fatty_acid",
        "mineral",
        "other",
        "vitamin",
    ]
    assert names["fatty_acid"] == "Acide gras"
    assert names["mineral"] == "Minéral"
    # The label's table: fat and the fats under it, carbohydrates and their parts.
    assert fields["macronutrient"] == [
        nutrient_field(code)
        for code in (
            "fat",
            "saturated_fat",
            "monounsaturated_fat",
            "polyunsaturated_fat",
            "trans_fat",
            "carbohydrates",
            "sugars",
            "lactose",
            "added_sugars",
            "starch",
            "polyols",
            "fiber",
            "proteins",
        )
    ]
    # The other fatty acids are a group of their own, EPA + DHA after the omega-3.
    assert fields["fatty_acid"] == [
        nutrient_field(code)
        for code in (
            "oleic_acid",
            "omega_6",
            "omega_3",
            "epa_dha",
            "linoleic_acid",
            "alpha_linolenic_acid",
            "arachidonic_acid",
            "epa",
            "dha",
        )
    ]
    assert fields["mineral"] == [
        nutrient_field(code)
        for code in (
            "sodium",
            "magnesium",
            "phosphorus",
            "chloride",
            "potassium",
            "calcium",
            "manganese",
            "iron",
            "copper",
            "fluoride",
            "zinc",
            "selenium",
            "chromium",
            "molybdenum",
            "iodine",
        )
    ]
    assert fields["other"] == [nutrient_field("salt"), nutrient_field("cholesterol")]
    assert nutrient_field("biotin") in fields["vitamin"]
    assert nutrient_field("beta_carotene") in fields["vitamin"]
    assert labels == {
        "saturated_fat": "dont acides gras saturés",
        "monounsaturated_fat": "dont acides gras monoinsaturés",
        "epa_dha": "dont EPA + DHA",
        "calcium": "Calcium",
    }


def test_a_part_is_listed_right_after_the_nutrient_it_is_part_of():
    def nutrient(code: str, parent: str | None = None) -> Nutrient:
        return Nutrient(code=code, parent_id=parent)

    given = [
        nutrient("fat"),
        nutrient("carbohydrates"),
        nutrient("sugars", "carbohydrates"),
        nutrient("fiber"),
        nutrient("saturated_fat", "fat"),
        nutrient("lactose", "sugars"),
        nutrient("trans_fat", "fat"),
        nutrient("oleic_acid", "monounsaturated_fat"),
    ]

    assert [n.code for n in in_table_order(given)] == [
        "fat",
        "saturated_fat",
        "trans_fat",
        "carbohydrates",
        "sugars",
        "lactose",
        "fiber",
        # Part of a nutrient that is not here: on its own.
        "oleic_acid",
    ]


@pytest.mark.usefixtures("catalogue")
def test_every_nutrient_openfoodfacts_gives_for_a_drink_is_read():
    # Fresubin DB 2 kcal Drink (4051895056838): OpenFoodFacts has every mass in grams.
    nutriments = {
        "energy_100g": 835,
        "fat_100g": 9.3,
        "saturated-fat_100g": 1.6,
        "monounsaturated-fat_100g": 5.4,
        "polyunsaturated-fat_100g": 2.4,
        "carbohydrates_100g": 17.4,
        "sugars_100g": 6.3,
        "added-sugars_100g": 3.96,
        "lactose_100g": 0.45,
        "fiber_100g": 3,
        "proteins_100g": 10,
        "salt_100g": 0.15,
        "sodium_100g": 0.06,
        "calcium_100g": 0.212,
        "chloride_100g": 0.06,
        "chromium_100g": 2.5e-05,
        "copper_100g": 0.00032,
        "fluoride_100g": 0.00026,
        "iodine_100g": 2.8e-05,
        "iron_100g": 0.003,
        "magnesium_100g": 0.016,
        "manganese_100g": 0.00073,
        "molybdenum_100g": 1.9e-05,
        "phosphorus_100g": 0.132,
        "potassium_100g": 0.162,
        "selenium_100g": 1.44e-05,
        "zinc_100g": 0.0022,
        "biotin_100g": 9e-06,
        "beta-carotene_100g": 4.4e-05,
        "vitamin-b12_100g": 6.8e-07,
        # Not nutrients of the catalogue.
        "fruits-vegetables-nuts-estimate-from-ingredients_100g": 7.88,
        "caffeine_100g": 0.01,
    }

    values = declared_nutrients_from_off(nutriments)

    assert values == {
        "energy": Decimal(835),
        "fat": Decimal("9.3"),
        "saturated_fat": Decimal("1.6"),
        "monounsaturated_fat": Decimal("5.4"),
        "polyunsaturated_fat": Decimal("2.4"),
        "carbohydrates": Decimal("17.4"),
        "sugars": Decimal("6.3"),
        "added_sugars": Decimal("3.96"),
        "lactose": Decimal("0.45"),
        "fiber": Decimal(3),
        "proteins": Decimal(10),
        "salt": Decimal("0.15"),
        # Minerals in the catalogue's unit: mg, and µg for the traces.
        "sodium": Decimal(60),
        "calcium": Decimal(212),
        "chloride": Decimal(60),
        "chromium": Decimal(25),
        "copper": Decimal("0.32"),
        "fluoride": Decimal("0.26"),
        "iodine": Decimal(28),
        "iron": Decimal(3),
        "magnesium": Decimal(16),
        "manganese": Decimal("0.73"),
        "molybdenum": Decimal(19),
        "phosphorus": Decimal(132),
        "potassium": Decimal(162),
        "selenium": Decimal("14.4"),
        "zinc": Decimal("2.2"),
        "biotin": Decimal(9),
        "beta_carotene": Decimal(44),
        "vitamin_b12": Decimal("0.68"),
    }


@pytest.mark.usefixtures("catalogue")
def test_save_stores_what_the_label_declares_beyond_the_vitamins():
    form = ProductForm(
        data={
            "barcode": BARCODE,
            "name": "Boisson",
            "nutrition_unit": "ml",
            nutrient_field("monounsaturated_fat"): "5.4",
            nutrient_field("calcium"): "212",
            nutrient_field("epa_dha"): "0.25",
            nutrient_field("biotin"): "9",
        }
    )
    assert form.is_valid(), form.errors

    product = form.save()

    assert dict(
        ProductNutrient.objects.filter(product=product).values_list(
            "nutrient_id", "amount"
        )
    ) == {
        "monounsaturated_fat": Decimal("5.4"),
        "calcium": Decimal(212),
        "epa_dha": Decimal("0.25"),
        "biotin": Decimal(9),
    }


@pytest.mark.django_db
def test_without_the_vitamins_the_form_has_no_group_for_them():
    form = ProductForm()

    layout = form._get_nutritional_values_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert not any(group.key == "vitamin" for group in layout)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]


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
