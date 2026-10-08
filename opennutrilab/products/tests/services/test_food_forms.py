import pytest

from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.food_forms import COOKED_WORDS
from opennutrilab.products.services.food_forms import Form
from opennutrilab.products.services.food_forms import form_of_food
from opennutrilab.products.services.food_forms import has_a_word_of
from opennutrilab.products.services.food_forms import split_states

pytestmark = pytest.mark.django_db


def food_named(fr: str, en: str = "") -> SourceFood:
    source = Source.objects.get_or_create(code="ciqual-2025", name="Ciqual")[0]
    return SourceFood.objects.create(
        source=source, code=str(SourceFood.objects.count()), name_fr=fr, name_en=en
    )


@pytest.mark.parametrize(
    ("fr", "en", "form"),
    [
        ("Haricot rouge, sec", "Red kidney bean, dried", Form.DRIED),
        ("Haricot rouge, bouilli/cuit à l'eau", "", Form.BOILED),
        ("Maïs doux, en épis, cuit", "Corn, on the cob, cooked", Form.COOKED),
        ("Haricot rouge, appertisé, égoutté", "Red kidney bean, canned", Form.CANNED),
        ("Betterave rouge, crue", "Beetroot, raw", Form.RAW),
        # Frozen, fresh, or nothing said is the food as it is.
        ("Framboise, surgelée, crue", "Raspberry, frozen, raw", Form.RAW),
        ("Coriandre, graine", "Coriander, seed", Form.RAW),
        # The English name says it when the French one does not.
        ("Aliment", "Thing, cooked", Form.COOKED),
    ],
)
def test_the_form_of_a_food_is_read_from_its_names(fr: str, en: str, form: Form):
    assert form_of_food(food_named(fr, en)) == form


def test_a_word_of_state_is_a_whole_word_only():
    """ "Cru" is not in "crustacés"."""
    assert split_states("crevette, crustaces") == ("crevette, crustaces", set())


def test_what_a_segment_says_besides_the_state_stays_in_the_name():
    assert split_states("orge perlee, bouilli/cuite a l'eau, sans sel ajoute") == (
        "orge perlee",
        {"bouilli", "cuite"},
    )
    assert split_states("mais doux, en epis, cuit") == ("mais doux, en epis", {"cuit"})


def test_a_name_is_searched_for_whole_words_without_accents():
    assert has_a_word_of("Petit épeautre et orge perlée cuits", COOKED_WORDS)
    assert has_a_word_of("small spelt and beaded barley cooked", COOKED_WORDS)
    assert not has_a_word_of("Biscuits crus", COOKED_WORDS)
    assert not has_a_word_of("Crème cuisinée", COOKED_WORDS)
