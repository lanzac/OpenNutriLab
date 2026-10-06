from typing import Any
from unittest.mock import patch

import pytest
from pytest_django.fixtures import SettingsWrapper

from opennutrilab.products.models import Additive
from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import Preparation
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.english_names import MACHINE_LIMIT
from opennutrilab.products.services.english_names import NameSource
from opennutrilab.products.services.english_names import propose_english_names

pytestmark = pytest.mark.django_db

TRANSLATE = "opennutrilab.products.services.english_names.translate"


def french(name: str) -> ReferenceIngredient:
    return ReferenceIngredient.objects.create(name_fr=name)


def propose(*references: ReferenceIngredient) -> Any:
    return propose_english_names(list(references))


@pytest.fixture(autouse=True)
def translator(settings: SettingsWrapper) -> None:
    """A translator is set; what asks it is patched (see TRANSLATE)."""
    settings.TRANSLATION_URL = "http://translator:5000"


@pytest.fixture
def ciqual() -> Source:
    return Source.objects.create(code="ciqual-2025", name="Ciqual")


def test_the_taxonomys_english_name_is_proposed_first():
    IngredientTaxon.objects.create(
        off_id="en:oat-flakes", name_en="oat flakes", name_fr="flocons d'avoine"
    )

    with patch(TRANSLATE) as translate:
        (proposal,) = propose(french("flocons d'avoine")).proposals

    assert (proposal.name_en, proposal.source) == ("oat flakes", NameSource.TAXONOMY)
    translate.assert_not_called()


def test_a_plural_finds_the_taxonomys_singular():
    IngredientTaxon.objects.create(off_id="en:date", name_en="date", name_fr="datte")

    (proposal,) = propose(french("dattes")).proposals

    assert proposal.name_en == "date"


def test_the_english_name_of_the_one_source_food_is_proposed(ciqual: Source):
    oil = french("huile d'olive vierge extra")
    oil.source_foods.add(
        SourceFood.objects.create(
            source=ciqual, code="17270", name_en="Olive oil, extra virgin"
        )
    )

    (proposal,) = propose(oil).proposals

    assert (proposal.name_en, proposal.source) == (
        "Olive oil, extra virgin",
        NameSource.FOOD,
    )


def test_with_several_source_foods_there_is_no_telling_which_to_take(ciqual: Source):
    tomato = french("tomate cerise mi séchée")
    tomato.source_foods.add(
        SourceFood.objects.create(source=ciqual, code="1", name_en="Tomato, cherry"),
        SourceFood.objects.create(source=ciqual, code="2", name_en="Tomato, dried"),
    )

    (proposal,) = propose(tomato).proposals

    assert (proposal.name_en, proposal.source) == ("", None)


def test_a_machine_translation_is_proposed_when_nothing_else_is():
    with patch(TRANSLATE, return_value="grilled onion"):
        (proposal,) = propose(french("oignon grillé")).proposals

    assert (proposal.name_en, proposal.source) == ("grilled onion", NameSource.MACHINE)


def test_a_translation_that_is_the_french_name_again_is_no_proposal():
    """A translator gives back a word it does not know as it was written."""
    with patch(TRANSLATE, return_value="Pomme de terre déshydratée"):
        result = propose(french("pomme de terre déshydratée"))

    assert [(p.name_en, p.source) for p in result.proposals] == [("", None)]
    assert not result.translator_failed


def test_nothing_is_proposed_when_no_source_has_a_name():
    with patch(TRANSLATE, return_value=None):
        result = propose(french("oignon grillé"))

    assert [(p.name_en, p.source) for p in result.proposals] == [("", None)]


def test_a_translator_that_does_not_answer_is_asked_once_and_reported():
    with patch(TRANSLATE, return_value=None) as translate:
        result = propose(french("oignon grillé"), french("jus d'oignon"))

    assert result.translator_failed
    assert translate.call_count == 1


def test_no_translator_set_is_not_asked_and_not_reported_as_failing(
    settings: SettingsWrapper,
):
    settings.TRANSLATION_URL = ""

    with patch(TRANSLATE) as translate:
        result = propose(french("oignon grillé"))

    translate.assert_not_called()
    assert not result.translator_failed
    assert [(p.name_en, p.source) for p in result.proposals] == [("", None)]


def test_a_translator_that_answers_is_not_reported_as_failing():
    with patch(TRANSLATE, return_value="onion"):
        result = propose(french("oignon"))

    assert not result.translator_failed


def test_the_translator_is_asked_for_a_bounded_number_of_names():
    references = [french(f"ingrédient {n}") for n in range(MACHINE_LIMIT + 3)]

    with patch(TRANSLATE, return_value="something") as translate:
        result = propose(*references)

    assert translate.call_count == MACHINE_LIMIT
    assert [p.name_en for p in result.proposals[-3:]] == ["", "", ""]


def test_proposals_come_in_the_order_given():
    IngredientTaxon.objects.create(off_id="en:date", name_en="date", name_fr="datte")
    with patch(TRANSLATE, return_value="onion"):
        result = propose(french("oignon"), french("datte"))

    assert [p.name_en for p in result.proposals] == ["onion", "date"]


def test_a_name_another_reference_has_is_marked_as_taken():
    ReferenceIngredient.objects.create(name_en="Grilled onion")

    with patch(TRANSLATE, return_value="grilled onion"):
        (proposal,) = propose(french("oignon grillé")).proposals

    assert proposal.taken_by == "Grilled onion"


def test_a_name_a_preparation_has_is_marked_as_taken():
    Preparation.objects.create(name_en="gnocchi")

    with patch(TRANSLATE, return_value="gnocchi"):
        (proposal,) = propose(french("gnocchi à la pomme de terre")).proposals

    assert proposal.taken_by == "gnocchi"


def test_a_name_an_additive_has_is_marked_as_taken():
    Additive.objects.create(name_en="citric acid", code="E330")

    with patch(TRANSLATE, return_value="Citric acid"):
        (proposal,) = propose(french("acide citrique")).proposals

    assert proposal.taken_by == "citric acid"


def test_a_name_is_not_taken_by_the_reference_it_is_proposed_for():
    # It has no English name yet, so only others can have it.
    with patch(TRANSLATE, return_value="onion"):
        (proposal,) = propose(french("oignon")).proposals

    assert proposal.taken_by == ""
