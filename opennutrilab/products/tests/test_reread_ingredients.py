from io import StringIO

import pytest
from django.core.management import call_command

from opennutrilab.products.models import Additive
from opennutrilab.products.models import Ingredient
from opennutrilab.products.models import Product
from opennutrilab.products.models import ReferenceIngredient

pytestmark = pytest.mark.django_db

LABEL = "Gnocchi, mozzarella [lait, sel, acidifiant : acide citrique]"


def product(barcode: str, text: str = LABEL) -> Product:
    return Product.objects.create(
        barcode=barcode, name=f"Product {barcode}", ingredients_text=text
    )


def old_tree(label: Product) -> None:
    """What was saved when the label was read the old way."""
    mozzarella = ReferenceIngredient.objects.create(name_fr="mozzarella")
    root = Ingredient.objects.create(product=label, reference=mozzarella)
    for name in ("lait", "sel", "acidifiant"):
        part = ReferenceIngredient.objects.create(name_fr=name)
        Ingredient.objects.create(product=label, parent=root, reference=part)


def reread(*args: str) -> str:
    out = StringIO()
    call_command("reread_ingredients", *args, stdout=out)
    return out.getvalue()


def test_a_product_is_read_again_from_its_stored_label_with_the_present_rules():
    label = product("3017620422003")
    old_tree(label)

    output = reread()

    names = [i.item.name for i in label.ingredients.order_by("id")]
    assert names == ["gnocchi", "mozzarella", "lait", "sel", "acide citrique"]
    assert Additive.objects.get().function == "acid"
    assert "4 -> 5 ingredients" in output
    assert "1 product(s) read again, 0 left as they were" in output
    assert "1 additive(s) made" in output


def test_the_names_of_what_is_new_go_where_the_language_says():
    french = product("3017620422003", "Gnocchi, sel")
    english = product("3229820794556", "Sugar, flour")

    reread("--barcode", french.barcode)
    reread("--language", "en", "--barcode", english.barcode)

    assert ReferenceIngredient.objects.get(name_fr="gnocchi").name_en == ""
    assert ReferenceIngredient.objects.get(name_en="sugar").name_fr == ""


def test_a_product_with_no_stored_text_is_left_as_it_is():
    label = product("3017620422003", "")
    old_tree(label)
    before = list(label.ingredients.values_list("pk", flat=True))

    output = reread()

    assert list(label.ingredients.values_list("pk", flat=True)) == before
    assert "left as it is (no stored label text)" in output
    assert "0 product(s) read again, 1 left as they were" in output


def test_a_text_that_looks_badly_read_leaves_the_ingredients_alone_and_says_why():
    label = product("3017620422003", "Sucre, émulsifiants : lécithines [SOJA), sel")
    old_tree(label)
    before = list(label.ingredients.values_list("pk", flat=True))

    output = reread()

    assert list(label.ingredients.values_list("pk", flat=True)) == before
    assert "left as it is" in output
    assert "[SOJA)" in output


def test_a_dry_run_says_what_would_change_and_keeps_nothing():
    label = product("3017620422003")
    old_tree(label)
    before = list(label.ingredients.values_list("pk", flat=True))
    references = ReferenceIngredient.objects.count()

    output = reread("--dry-run")

    assert list(label.ingredients.values_list("pk", flat=True)) == before
    assert ReferenceIngredient.objects.count() == references
    assert not Additive.objects.exists()
    assert "Dry run, nothing kept" in output
    assert "1 additive(s) made" in output


def test_only_the_products_asked_for_are_read_again():
    one = product("3017620422003")
    other = product("3229820794556")

    reread("--barcode", one.barcode)

    assert one.ingredients.exists()
    assert not other.ingredients.exists()


def test_what_a_person_left_out_of_the_text_is_left_out_again():
    text = "Gnocchi, mozzarella [lait, sel], zone de pêche (FAO 67), eau"
    start = text.index("zone")
    label = product("3017620422003", text)
    label.ingredients_ignored = [[start, text.index(", eau")]]
    label.save()

    reread()

    names = [i.item.name for i in label.ingredients.order_by("id")]
    assert names == ["gnocchi", "mozzarella", "lait", "sel", "eau"]


def test_the_language_stored_with_the_text_is_the_one_a_product_is_read_in():
    english = product("3229820794556", "Sugar, flour")
    english.ingredients_language = "en"
    english.save()
    french = product("3017620422003", "Gnocchi, sel")

    reread()

    assert ReferenceIngredient.objects.get(name_en="sugar").name_fr == ""
    assert ReferenceIngredient.objects.get(name_fr="gnocchi").name_en == ""
    assert french.ingredients.exists()


def test_a_language_given_wins_over_the_ones_stored():
    english = product("3229820794556", "Sugar, flour")
    english.ingredients_language = "en"
    english.save()

    reread("--language", "fr")

    assert ReferenceIngredient.objects.get(name_fr="sugar").name_en == ""
