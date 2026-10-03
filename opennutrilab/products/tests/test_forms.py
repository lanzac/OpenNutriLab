import json
from decimal import Decimal
from typing import Any

import pytest
from crispy_forms.bootstrap import FieldWithButtons
from django.utils import translation

from opennutrilab.products.api.schemas.inbound import ProductCreate
from opennutrilab.products.forms import ProductForm
from opennutrilab.products.forms import nutrient_field
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ProductNutrient

BARCODE = "3229820794556"


def declared(product: Product) -> dict[str, Decimal]:
    return dict(
        ProductNutrient.objects.filter(product=product).values_list(
            "nutrient_id", "amount"
        )
    )


def form_data(**nutrients: str) -> dict[str, Any]:
    data: dict[str, Any] = {"barcode": BARCODE, "name": "Muesli"}
    data.update({nutrient_field(code): value for code, value in nutrients.items()})
    return data


@pytest.mark.django_db
class TestBuildBarcodeField:
    def test_create_mode_returns_fieldwithbuttons(self):
        form = ProductForm(instance=Product())  # no pk
        field: FieldWithButtons = form._get_barcode_field_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        assert isinstance(field, FieldWithButtons)

    def test_edit_mode_disables_the_barcode(self):
        product = Product.objects.create(name="Apple", barcode="1234567890123")
        form = ProductForm(instance=product)
        field: FieldWithButtons = form._get_barcode_field_layout()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        assert isinstance(field, FieldWithButtons)

        # The barcode is the primary key: Django ignores it once saved.
        assert form.fields["barcode"].disabled is True


# ----------------------------------------------------------------------------
# Declared nutrient fields
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_one_field_per_label_nutrient_named_in_the_language_served():
    with translation.override("fr-fr"):
        form = ProductForm()

    codes = list(Nutrient.objects.filter(on_label=True).values_list("code", flat=True))
    assert [name for name in form.fields if name.startswith("nutrient_")] == [
        nutrient_field(code) for code in codes
    ]
    assert form.fields[nutrient_field("salt")].label == "Sel"


@pytest.mark.django_db
def test_fields_show_the_stored_values_without_trailing_zeros():
    product = Product.objects.create(barcode=BARCODE, name="Muesli")
    ProductNutrient.objects.create(
        product=product,
        nutrient=Nutrient.objects.get(code="fat"),
        amount=Decimal("9.4"),
    )
    ProductNutrient.objects.create(
        product=product, nutrient=Nutrient.objects.get(code="energy"), amount=1532
    )

    form = ProductForm(instance=product)

    assert form.fields[nutrient_field("fat")].initial == "9.4"
    assert form.fields[nutrient_field("energy")].initial == "1532"
    assert form.fields[nutrient_field("salt")].initial is None


@pytest.mark.django_db
def test_save_stores_the_declared_values_given():
    form = ProductForm(data=form_data(energy="1532", fat="9.4", sugars="0", salt=""))
    assert form.is_valid(), form.errors

    product = form.save()

    # 0 is a measurement and is kept; an empty field is "unknown".
    assert declared(product) == {
        "energy": Decimal(1532),
        "fat": Decimal("9.4"),
        "sugars": Decimal(0),
    }


@pytest.mark.django_db
def test_emptying_a_field_clears_the_stored_value():
    product = Product.objects.create(barcode=BARCODE, name="Muesli")
    ProductNutrient.objects.create(
        product=product, nutrient=Nutrient.objects.get(code="fat"), amount=5
    )

    form = ProductForm(data=form_data(fat="", proteins="21"), instance=product)
    assert form.is_valid(), form.errors
    form.save()

    assert declared(product) == {"proteins": Decimal(21)}


@pytest.mark.django_db
def test_editing_leaves_declared_values_off_the_form_alone():
    """Values outside the label declaration (a vitamin) have no field here."""
    vitamin_c = Nutrient.objects.create(
        code="vitamin_c",
        name_en="Vitamin C",
        name_fr="Vitamine C",
        unit="mg",
        group="vitamin",
    )
    product = Product.objects.create(barcode=BARCODE, name="Muesli")
    ProductNutrient.objects.create(product=product, nutrient=vitamin_c, amount=12)

    form = ProductForm(data=form_data(fat="1"), instance=product)
    assert form.is_valid(), form.errors
    form.save()

    assert declared(product)["vitamin_c"] == Decimal(12)


@pytest.mark.django_db
def test_inconsistent_values_are_saved_with_a_warning():
    """The label is the reference: inconsistencies warn, they never block."""
    form = ProductForm(data=form_data(carbohydrates="9.9", sugars="10"))
    assert form.is_valid(), form.errors

    product = form.save()

    assert declared(product)["sugars"] == Decimal(10)
    assert len(form.declared_value_warnings) == 1


@pytest.mark.django_db
def test_a_negative_amount_is_refused():
    form = ProductForm(data=form_data(fat="-1"))

    assert not form.is_valid()
    assert nutrient_field("fat") in form.errors


# ----------------------------------------------------------------------------
# Data carried from an OpenFoodFacts lookup
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_off_fields_only_apply_to_the_barcode_they_were_fetched_for():
    off_ingredients = json.dumps([{"name": "Sucre", "off_id": "en:sugar"}])
    base = {"name": "Nutella", "off_ingredients": off_ingredients}

    matching = ProductForm(
        data={**base, "barcode": "3017620422003", "off_barcode": "3017620422003"}
    )
    other = ProductForm(
        data={**base, "barcode": "3229820794556", "off_barcode": "3017620422003"}
    )

    assert matching.is_valid(), matching.errors
    assert other.is_valid(), other.errors
    assert isinstance(matching.write_data, ProductCreate)
    assert isinstance(other.write_data, ProductCreate)
    assert [(i.name, i.off_id) for i in matching.write_data.ingredients] == [
        ("Sucre", "en:sugar")
    ]
    assert other.write_data.ingredients == []


@pytest.mark.django_db
def test_save_cannot_defer_the_write():
    """The services write the product; there is no unsaved instance to hand back."""
    form = ProductForm(data=form_data())
    assert form.is_valid(), form.errors

    with pytest.raises(ValueError, match="cannot defer"):
        form.save(commit=False)

    assert not Product.objects.exists()
