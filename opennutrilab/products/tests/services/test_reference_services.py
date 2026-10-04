from typing import Any
from unittest.mock import patch

import pytest

from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services import reference_services
from opennutrilab.products.services.reference_services import find_references
from opennutrilab.products.services.reference_services import name_key
from opennutrilab.products.services.reference_services import resolve_references


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
def test_finding_takes_one_query_however_many_names(
    django_assert_num_queries: Any,
):
    ReferenceIngredient.objects.create(name_en="carrot")

    with django_assert_num_queries(1):
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
def test_a_french_name_another_reference_has_is_left_blank():
    ReferenceIngredient.objects.create(name_en="oats", name_fr="flocons d'avoine")
    IngredientTaxon.objects.create(
        off_id="en:oat-flakes", name_en="oat flakes", name_fr="Flocons d'avoine"
    )

    created = resolve_references([ingredient("oat flakes", off_id="en:oat-flakes")])[
        "oat flakes"
    ]

    assert created.name_fr == ""
    assert ReferenceIngredient.objects.count() == 2  # noqa: PLR2004


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
    lookups = [{}, {"sugar": other_request}]

    with patch.object(reference_services, "find_references", side_effect=lookups):
        references = resolve_references([ingredient("sugar")])

    assert references == {"sugar": other_request}
    assert ReferenceIngredient.objects.count() == 1
