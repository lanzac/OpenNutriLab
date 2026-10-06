from typing import Any
from unittest.mock import patch

import pytest
from django.utils import translation

from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services import reference_services
from opennutrilab.products.services.reference_services import ReferenceNameError
from opennutrilab.products.services.reference_services import (
    create_reference_from_foods,
)
from opennutrilab.products.services.reference_services import existing_references
from opennutrilab.products.services.reference_services import find_references
from opennutrilab.products.services.reference_services import name_key
from opennutrilab.products.services.reference_services import resolve_references
from opennutrilab.products.services.reference_services import suggest_source_foods


def ingredient(name: str, **fields: Any) -> IngredientInput:
    return IngredientInput.model_validate({"name": name, **fields})


@pytest.fixture
def oat_flakes(db: None) -> SourceFood:
    ciqual = Source.objects.create(code="ciqual-2020", name="CIQUAL", version="2020")
    return SourceFood.objects.create(
        source=ciqual, code="9311", name_fr="Flocons d'avoine"
    )


# ----------------------------------------------------------------------------
# Finding
# ----------------------------------------------------------------------------
def test_names_are_compared_without_their_case_or_extra_spacing():
    assert name_key("  Flocons   d'Avoine ") == "flocons d'avoine"


@pytest.mark.django_db
def test_a_reference_is_found_by_either_of_its_names_whatever_the_case():
    carrot = ReferenceIngredient.objects.create(name_en="Carrot", name_fr="carotte")

    found = find_references(["CARROT", "Carotte ", "turnip"])

    assert found == {"carrot": carrot, "carotte": carrot}


@pytest.mark.django_db
def test_a_blank_name_finds_nothing():
    ReferenceIngredient.objects.create(name_en="carrot")

    assert find_references(["", "  "]) == {}


@pytest.mark.django_db
def test_an_english_name_wins_over_the_same_french_one():
    pasta = ReferenceIngredient.objects.create(name_en="pasta")
    ReferenceIngredient.objects.create(name_en="noodles", name_fr="pasta")

    assert find_references(["pasta"]) == {"pasta": pasta}


@pytest.mark.django_db
def test_a_preparation_is_found_by_either_of_its_names_and_in_the_plural():
    mozzarella = Preparation.objects.create(name_en="Mozzarella", name_fr="mozzarelle")

    found = find_references(["MOZZARELLA", "mozzarelles", "cheddar"])

    assert found == {"mozzarella": mozzarella, "mozzarelles": mozzarella}


@pytest.mark.django_db
def test_a_name_both_tables_have_in_two_languages_is_read_in_the_language_asked():
    """No clash: a reference's French name is a preparation's English one."""
    pasta = Preparation.objects.create(name_en="pasta")
    noodles = ReferenceIngredient.objects.create(name_en="noodles", name_fr="pasta")

    assert find_references(["pasta"]) == {"pasta": pasta}
    assert find_references(["pasta"], french_first=True) == {"pasta": noodles}


@pytest.mark.django_db
def test_finding_takes_one_query_a_table_however_many_names(
    django_assert_num_queries: Any,
):
    ReferenceIngredient.objects.create(name_en="carrot")

    with django_assert_num_queries(2):
        find_references(["carrot", "oat flakes", "sugar", "salt"])


# ----------------------------------------------------------------------------
# Resolving, and creating what is missing
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_an_existing_reference_is_used_not_created_again():
    carrot = ReferenceIngredient.objects.create(name_en="carrot")

    references = resolve_references([ingredient("Carrot")])

    assert references == {"carrot": carrot}
    assert ReferenceIngredient.objects.count() == 1


@pytest.mark.django_db
def test_a_missing_reference_is_created_to_review_under_the_name_given():
    references = resolve_references([ingredient("oat flakes")])

    created = references["oat flakes"]
    assert (created.name_en, created.name_fr) == ("oat flakes", "")
    assert created.status == ReferenceIngredient.Status.TO_REVIEW
    assert not created.source_foods.exists()


@pytest.mark.django_db
def test_a_preparation_is_used_and_no_reference_is_created_under_its_name():
    mozzarella = Preparation.objects.create(name_en="mozzarella")
    tree = [
        ingredient("Mozzarella", sub_ingredients=[{"name": "milk"}]),
        ingredient("tomato"),
    ]

    resolved = resolve_references(tree)

    assert resolved["mozzarella"] == mozzarella
    # What no reference or preparation has the name of is still a reference to
    # review, parts of a preparation included.
    assert set(ReferenceIngredient.objects.values_list("name_en", flat=True)) == {
        "milk",
        "tomato",
    }
    assert isinstance(resolved["milk"], ReferenceIngredient)
    assert resolved["tomato"].status == ReferenceIngredient.Status.TO_REVIEW
    assert Preparation.objects.get() == mozzarella


@pytest.mark.django_db
def test_a_name_that_matches_nothing_is_never_made_a_preparation():
    resolved = resolve_references([ingredient("mozzarella")])

    assert isinstance(resolved["mozzarella"], ReferenceIngredient)
    assert not Preparation.objects.exists()


@pytest.mark.django_db
def test_a_name_in_a_preparations_plural_finds_it_and_creates_nothing():
    mozzarella = Preparation.objects.create(name_en="mozzarella")

    resolved = resolve_references([ingredient("mozzarellas")])

    assert resolved == {"mozzarellas": mozzarella}
    assert not ReferenceIngredient.objects.exists()


@pytest.mark.django_db
def test_a_name_in_a_sub_ingredient_or_twice_is_one_reference():
    tree = [
        ingredient(
            "dates", sub_ingredients=[{"name": "sugar"}, {"name": "rice flour"}]
        ),
        ingredient("Sugar"),
    ]

    references = resolve_references(tree)

    assert set(references) == {"dates", "sugar", "rice flour"}
    assert ReferenceIngredient.objects.count() == 3  # noqa: PLR2004


@pytest.mark.django_db
def test_a_created_reference_takes_the_taxonomys_french_name():
    IngredientTaxon.objects.create(
        off_id="en:oat-flakes", name_en="oat flakes", name_fr="flocons d'avoine"
    )

    created = resolve_references([ingredient("oat flakes", off_id="en:oat-flakes")])[
        "oat flakes"
    ]

    assert created.name_fr == "flocons d'avoine"
    assert "en:oat-flakes" in created.description


@pytest.mark.django_db
def test_a_reference_that_has_the_taxonomys_french_name_is_the_one_used():
    """The catalogue wins: its own French name is the correspondence."""
    mine = ReferenceIngredient.objects.create(
        name_en="oats", name_fr="flocons d'avoine"
    )
    IngredientTaxon.objects.create(
        off_id="en:oat-flakes", name_en="oat flakes", name_fr="Flocons d'avoine"
    )

    references = resolve_references([ingredient("oat flakes", off_id="en:oat-flakes")])

    assert references == {"oat flakes": mine}
    assert ReferenceIngredient.objects.count() == 1


@pytest.mark.django_db
def test_an_id_the_taxonomy_does_not_know_gives_no_french_name():
    created = resolve_references([ingredient("red fruits", off_id="en:red-fruits")])[
        "red fruits"
    ]

    assert created.name_fr == ""


@pytest.mark.django_db
def test_an_exact_ciqual_code_of_an_imported_food_links_it(oat_flakes: SourceFood):
    created = resolve_references(
        [ingredient("oat flakes", off_ciqual_food_code="9311")]
    )["oat flakes"]

    assert list(created.source_foods.all()) == [oat_flakes]
    assert created.status == ReferenceIngredient.Status.TO_REVIEW
    assert "9311 (linked)" in created.description


@pytest.mark.django_db
def test_a_ciqual_code_that_was_not_imported_links_nothing_and_is_noted():
    created = resolve_references(
        [ingredient("oat flakes", off_ciqual_food_code="9311")]
    )["oat flakes"]

    assert not created.source_foods.exists()
    assert "9311 (not among the imported foods)" in created.description


@pytest.mark.django_db
def test_a_proxy_code_never_links_a_food_and_is_noted(oat_flakes: SourceFood):
    created = resolve_references(
        [ingredient("oat flakes", off_ciqual_proxy_food_code="9311")]
    )["oat flakes"]

    assert not created.source_foods.exists()
    assert "proxy CIQUAL code: 9311 (not linked)" in created.description


@pytest.mark.django_db
def test_only_a_ciqual_food_is_linked_by_a_ciqual_code(oat_flakes: SourceFood):
    other = Source.objects.create(code="manual", name="Saisie manuelle")
    SourceFood.objects.create(source=other, code="1234", name_fr="Autre")

    created = resolve_references(
        [ingredient("something", off_ciqual_food_code="1234")]
    )["something"]

    assert not created.source_foods.exists()


@pytest.mark.django_db
def test_a_reference_created_meanwhile_by_another_request_is_used():
    """The lookup said none, then another request created it first."""
    other_request = ReferenceIngredient.objects.create(name_en="sugar")

    with patch.object(reference_services, "existing_references", return_value={}):
        references = resolve_references([ingredient("sugar")])

    assert references == {"sugar": other_request}
    assert ReferenceIngredient.objects.count() == 1


# ----------------------------------------------------------------------------
# Through the English correspondence
# ----------------------------------------------------------------------------
@pytest.fixture
def oat_taxon(db: None) -> IngredientTaxon:
    return IngredientTaxon.objects.create(
        off_id="en:oat-flakes", name_en="oat flakes", name_fr="flocons d'avoine"
    )


@pytest.mark.django_db
def test_a_french_name_typed_by_hand_finds_the_reference_by_its_english_name(
    oat_taxon: IngredientTaxon,
):
    oats = ReferenceIngredient.objects.create(name_en="oat flakes")

    references = resolve_references([ingredient("Flocons d'avoine")])

    assert references == {"flocons d'avoine": oats}
    assert ReferenceIngredient.objects.count() == 1


@pytest.mark.django_db
def test_an_english_name_typed_by_hand_finds_the_reference_by_its_french_name(
    oat_taxon: IngredientTaxon,
):
    oats = ReferenceIngredient.objects.create(name_fr="flocons d'avoine")

    assert resolve_references([ingredient("oat flakes")]) == {"oat flakes": oats}
    assert ReferenceIngredient.objects.count() == 1


@pytest.mark.django_db
def test_a_french_name_typed_by_hand_creates_a_reference_keyed_by_its_english_name(
    oat_taxon: IngredientTaxon,
):
    created = resolve_references([ingredient("flocons d'avoine")])["flocons d'avoine"]

    assert (created.name_en, created.name_fr) == ("oat flakes", "flocons d'avoine")


@pytest.mark.django_db
def test_two_names_for_one_ingredient_make_one_reference(
    oat_taxon: IngredientTaxon,
):
    references = resolve_references(
        [ingredient("oat flakes"), ingredient("Flocons d'avoine")]
    )

    assert references["oat flakes"] == references["flocons d'avoine"]
    assert ReferenceIngredient.objects.count() == 1


@pytest.mark.django_db
def test_an_ambiguous_name_is_not_translated():
    IngredientTaxon.objects.create(off_id="en:a", name_en="shallot", name_fr="échalote")
    IngredientTaxon.objects.create(
        off_id="en:b", name_en="eschalot", name_fr="échalote"
    )

    created = resolve_references([ingredient("échalote")])["échalote"]

    assert (created.name_en, created.name_fr) == ("échalote", "")


@pytest.mark.django_db
def test_a_name_the_taxonomy_does_not_know_goes_where_its_language_says():
    with translation.override("en-us"):
        english = resolve_references([ingredient("tonka bean")])["tonka bean"]
    with translation.override("fr-fr"):
        french = resolve_references([ingredient("fève tonka")])["fève tonka"]

    assert (english.name_en, english.name_fr) == ("tonka bean", "")
    assert (french.name_en, french.name_fr) == ("", "fève tonka")


@pytest.mark.django_db
def test_an_off_id_prefix_gives_the_language_of_a_label_wording():
    with translation.override("en-us"):
        created = resolve_references(
            [ingredient("oignon et ail en poudre", off_id="fr:oignon-et-ail")]
        )["oignon et ail en poudre"]

    assert (created.name_en, created.name_fr) == ("", "oignon et ail en poudre")


@pytest.mark.django_db
def test_a_taxon_with_one_name_only_gives_that_one(db: None):
    IngredientTaxon.objects.create(off_id="en:ail-rose", name_fr="ail rose")

    created = resolve_references([ingredient("pink garlic", off_id="en:ail-rose")])[
        "pink garlic"
    ]

    assert (created.name_en, created.name_fr) == ("", "ail rose")


@pytest.mark.django_db
def test_a_preparation_is_found_through_the_english_correspondence():
    IngredientTaxon.objects.create(
        off_id="en:mozzarella", name_en="mozzarella", name_fr="mozzarelle"
    )
    mozzarella = Preparation.objects.create(name_en="mozzarella")

    resolved = resolve_references([ingredient("mozzarelle")])

    assert resolved == {"mozzarelle": mozzarella}
    assert not ReferenceIngredient.objects.exists()


@pytest.mark.django_db
def test_looking_up_creates_nothing(oat_taxon: IngredientTaxon):
    oats = ReferenceIngredient.objects.create(name_en="oat flakes")

    found = existing_references([ingredient("Flocons d'avoine"), ingredient("soya")])

    assert found == {"flocons d'avoine": oats}
    assert ReferenceIngredient.objects.count() == 1


# ----------------------------------------------------------------------------
# Curating
# ----------------------------------------------------------------------------
@pytest.fixture
def carrots(db: None) -> list[SourceFood]:
    ciqual = Source.objects.create(code="ciqual-2025", name="Ciqual", version="2025")
    return [
        SourceFood.objects.create(
            source=ciqual, code=code, name_fr=name_fr, name_en=name_en
        )
        for code, name_fr, name_en in [
            ("20009", "Carotte, crue", "Carrot, raw"),
            ("20010", "Carotte, râpée, crue", "Carrot, grated, raw"),
            ("20011", "Carotte, cuite", "Carrot, boiled"),
            ("20100", "Chou, cru", "Cabbage, raw"),
        ]
    ]


@pytest.mark.django_db
def test_foods_are_suggested_when_their_name_has_every_word_of_the_reference(
    carrots: list[SourceFood],
):
    reference = ReferenceIngredient.objects.create(name_fr="carotte râpée")

    assert [f.code for f in suggest_source_foods(reference)] == ["20010"]


@pytest.mark.django_db
def test_foods_are_suggested_by_either_name_and_in_either_language(
    carrots: list[SourceFood],
):
    reference = ReferenceIngredient.objects.create(name_en="cabbage", name_fr="carotte")

    assert {f.code for f in suggest_source_foods(reference)} == {
        "20009",
        "20010",
        "20011",
        "20100",
    }


@pytest.mark.django_db
def test_the_plainest_foods_are_suggested_first(db: None):
    ciqual = Source.objects.create(code="ciqual-2025", name="Ciqual", version="2025")
    for code, name in [
        ("1", "Biscuit sec au soja, enrichi en vitamines"),
        ("2", "Boisson au soja"),
        ("3", "Soja, graine, sèche"),
        ("4", "Soja, pousses"),
    ]:
        SourceFood.objects.create(source=ciqual, code=code, name_fr=name)
    reference = ReferenceIngredient.objects.create(name_fr="soja")

    assert [f.code for f in suggest_source_foods(reference)] == ["4", "3", "2", "1"]


@pytest.mark.django_db
def test_short_words_say_nothing_about_which_food_is_meant(
    carrots: list[SourceFood],
):
    reference = ReferenceIngredient.objects.create(name_fr="de la")

    assert suggest_source_foods(reference) == []


@pytest.mark.django_db
def test_a_food_the_reference_already_draws_on_is_not_suggested(
    carrots: list[SourceFood],
):
    reference = ReferenceIngredient.objects.create(name_fr="carotte")
    reference.source_foods.add(carrots[0])

    assert {f.code for f in suggest_source_foods(reference)} == {"20010", "20011"}


@pytest.mark.django_db
def test_suggestions_are_limited(carrots: list[SourceFood]):
    reference = ReferenceIngredient.objects.create(name_fr="carotte")

    assert len(suggest_source_foods(reference, limit=2)) == 2  # noqa: PLR2004


@pytest.mark.django_db
def test_a_reference_is_created_from_foods_and_named_after_the_first(
    carrots: list[SourceFood],
):
    created = create_reference_from_foods(carrots[:2])

    assert (created.name_en, created.name_fr) == ("Carrot, raw", "Carotte, crue")
    assert created.status == ReferenceIngredient.Status.TO_REVIEW
    assert set(created.source_foods.all()) == set(carrots[:2])
    assert "20009" in created.description


@pytest.mark.django_db
def test_a_reference_is_not_created_when_one_has_the_name(
    carrots: list[SourceFood],
):
    ReferenceIngredient.objects.create(name_en="carrot, raw")

    with pytest.raises(ReferenceNameError, match="already has the name"):
        create_reference_from_foods(carrots)

    assert ReferenceIngredient.objects.count() == 1


@pytest.mark.django_db
def test_a_reference_is_not_created_when_a_preparation_has_the_name(
    carrots: list[SourceFood],
):
    Preparation.objects.create(name_fr="Carotte, crue")

    with pytest.raises(ReferenceNameError, match="preparation already has the name"):
        create_reference_from_foods(carrots)

    assert not ReferenceIngredient.objects.exists()


@pytest.mark.django_db
def test_a_food_without_a_name_gives_no_reference(carrots: list[SourceFood]):
    nameless = SourceFood.objects.create(source=carrots[0].source, code="1")

    with pytest.raises(ReferenceNameError, match="no name"):
        create_reference_from_foods([nameless])


# ----------------------------------------------------------------------------
# A label writes the plural
# ----------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_name_in_the_plural_finds_the_reference_in_the_singular():
    date = ReferenceIngredient.objects.create(name_en="date", name_fr="datte")

    references = resolve_references([ingredient("Dattes"), ingredient("raisins secs")])

    assert references["dattes"] == date
    assert ReferenceIngredient.objects.filter(name_fr="dattes").count() == 0
    # Nothing is called "raisin sec" yet: that one is new, and not a duplicate.
    assert ReferenceIngredient.objects.count() == 2  # noqa: PLR2004


@pytest.mark.django_db
def test_the_name_as_written_is_tried_before_its_singular():
    """ "Cassis" must not be read as "cassi"."""
    ReferenceIngredient.objects.create(name_fr="cassi")
    cassis = ReferenceIngredient.objects.create(name_fr="cassis")

    assert find_references(["cassis"]) == {"cassis": cassis}


@pytest.mark.django_db
def test_a_plural_name_is_translated_through_the_taxonomy_by_its_singular():
    IngredientTaxon.objects.create(off_id="en:date", name_en="date", name_fr="datte")

    created = resolve_references([ingredient("dattes", language="fr")])["dattes"]

    # Named as the taxonomy names it, not "dattes".
    assert (created.name_en, created.name_fr) == ("date", "datte")


@pytest.mark.django_db
def test_the_plural_and_the_singular_of_a_name_make_one_reference():
    references = resolve_references([ingredient("dattes"), ingredient("datte")])

    assert references["dattes"] == references["datte"]
    assert ReferenceIngredient.objects.count() == 1


@pytest.mark.django_db
def test_a_name_with_the_language_it_is_in_goes_where_that_says():
    with translation.override("en-us"):
        created = resolve_references([ingredient("flocons de soja", language="fr")])[
            "flocons de soja"
        ]

    assert (created.name_en, created.name_fr) == ("", "flocons de soja")


# ----------------------------------------------------------------------------
# "Raisin": a grape in French, a dried grape in English
# ----------------------------------------------------------------------------
@pytest.fixture
def grapes(db: None) -> tuple[ReferenceIngredient, ReferenceIngredient]:
    grape = ReferenceIngredient.objects.create(name_en="grape", name_fr="raisin")
    dried = ReferenceIngredient.objects.create(name_en="raisin", name_fr="raisin sec")
    return grape, dried


@pytest.mark.django_db
def test_a_french_label_reads_raisin_as_the_grape(
    grapes: tuple[ReferenceIngredient, ReferenceIngredient],
):
    grape, dried = grapes

    references = resolve_references(
        [
            ingredient("raisins secs", language="fr"),
            ingredient("raisins", language="fr"),
        ]
    )

    assert references["raisins"] == grape
    assert references["raisins secs"] == dried


@pytest.mark.django_db
def test_an_english_label_reads_raisin_as_the_dried_grape(
    grapes: tuple[ReferenceIngredient, ReferenceIngredient],
):
    _grape, dried = grapes

    assert (
        resolve_references([ingredient("raisins", language="en")])["raisins"] == dried
    )


@pytest.mark.django_db
def test_without_a_language_english_wins_as_it_always_did(
    grapes: tuple[ReferenceIngredient, ReferenceIngredient],
):
    _grape, dried = grapes

    assert find_references(["raisin"])["raisin"] == dried


@pytest.mark.django_db
def test_a_french_wording_is_translated_through_the_french_names_of_the_taxonomy():
    IngredientTaxon.objects.create(off_id="en:grape", name_en="grape", name_fr="raisin")
    IngredientTaxon.objects.create(
        off_id="en:raisin", name_en="raisin", name_fr="raisin sec"
    )

    created = resolve_references([ingredient("raisins", language="fr")])["raisins"]

    # Not ambiguous in French, where only the grape is called "raisin".
    assert (created.name_en, created.name_fr) == ("grape", "raisin")
