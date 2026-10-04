import pytest

from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.services.reference_proposals import Confidence
from opennutrilab.products.services.reference_proposals import Reason
from opennutrilab.products.services.reference_proposals import propose_foods

pytestmark = pytest.mark.django_db


@pytest.fixture
def ciqual(db: None) -> Source:
    return Source.objects.create(code="ciqual-2025", name="Ciqual", version="2025")


def food(source: Source, code: str, name_fr: str, name_en: str = "") -> SourceFood:
    return SourceFood.objects.create(
        source=source, code=code, name_fr=name_fr, name_en=name_en
    )


def taxon(off_id: str, en: str, fr: str, code: str = "", proxy: str = "") -> None:
    IngredientTaxon.objects.create(
        off_id=off_id,
        name_en=en,
        name_fr=fr,
        ciqual_food_code=code,
        ciqual_proxy_food_code=proxy,
    )


def propose(**names: str) -> tuple[list[str], Confidence, list[tuple[Reason, ...]]]:
    reference = ReferenceIngredient.objects.create(**names)
    [proposal] = propose_foods([reference])
    return (
        [c.food.code for c in proposal.candidates],
        proposal.confidence,
        [c.reasons for c in proposal.candidates],
    )


# ----------------------------------------------------------------------------
# When the name and OpenFoodFacts agree
# ----------------------------------------------------------------------------
def test_the_plain_food_both_signals_point_to_is_a_high_confidence_proposal(
    ciqual: Source,
):
    food(ciqual, "13007", "Cassis, cru", "Blackcurrant, raw")
    food(ciqual, "1021", "Crème de cassis", "Blackcurrant liqueur")
    food(
        ciqual, "13997", "Fruits rouges, crus (framboises, fraises, groseilles, cassis)"
    )
    taxon("en:blackcurrant", "blackcurrant", "cassis", code="13007")

    codes, confidence, reasons = propose(name_en="blackcurrant", name_fr="cassis")

    assert (codes[0], confidence) == ("13007", Confidence.HIGH)
    assert reasons[0] == (Reason.NAME, Reason.OFF)


def test_a_cooked_food_comes_after_the_raw_one_the_reference_is(ciqual: Source):
    food(ciqual, "32140", "Flocons d'avoine", "Oat flakes")
    food(
        ciqual,
        "9313",
        "Flocons d'avoine bouillis/cuits à l'eau",
        "Oat flakes, boiled/cooked in water",
    )

    codes, _confidence, reasons = propose(
        name_en="oat flakes", name_fr="flocons d'avoine"
    )

    assert codes == ["32140", "9313"]
    assert Reason.PREPARED in reasons[1]
    assert Reason.PREPARED not in reasons[0]


def test_a_reference_that_is_cooked_does_not_count_that_against_a_food(
    ciqual: Source,
):
    food(ciqual, "4", "Pomme de terre, cuite", "Potato, boiled")
    food(ciqual, "5", "Pomme de terre, crue", "Potato, raw")

    _codes, _confidence, reasons = propose(name_fr="pomme de terre cuite")

    assert all(Reason.PREPARED not in r for r in reasons)


def test_the_shortest_of_several_plain_foods_comes_first_and_the_code_breaks_ties(
    ciqual: Source,
):
    food(ciqual, "13136", "Framboise, surgelée, crue")
    food(ciqual, "13015", "Framboise, crue")
    taxon("en:raspberry", "raspberry", "framboise", code="13136")

    codes, confidence, _reasons = propose(name_en="raspberry", name_fr="framboise")

    # Both are plain; OpenFoodFacts' code settles which.
    assert (codes[0], confidence) == ("13136", Confidence.HIGH)


# ----------------------------------------------------------------------------
# When only one signal speaks
# ----------------------------------------------------------------------------
def test_a_single_plain_food_by_name_is_a_medium_confidence_proposal(ciqual: Source):
    food(ciqual, "20901", "Soja, graine entière", "Soybean, whole")
    food(ciqual, "20915", "Farine de soja complète")
    food(ciqual, "17420", "Huile de soja")

    codes, confidence, _reasons = propose(name_en="soya", name_fr="soja")

    assert (codes[0], confidence) == ("20901", Confidence.MEDIUM)


def test_a_code_that_is_not_in_the_table_is_ignored(ciqual: Source):
    """9311 was oat flakes in an older CIQUAL: it is not trusted on its own."""
    food(ciqual, "32140", "Flocons d'avoine", "Oat flakes")
    taxon("en:oat-flakes", "oat flakes", "flocons d'avoine", code="9311")

    codes, confidence, reasons = propose(
        name_en="oat flakes", name_fr="flocons d'avoine"
    )

    assert codes == ["32140"]
    assert Reason.OFF not in reasons[0]
    assert confidence == Confidence.MEDIUM


def test_a_proxy_code_is_never_a_hint(ciqual: Source):
    food(ciqual, "9410", "Blé complet, cru")
    taxon("en:wheat-flakes", "wheat flakes", "flocons de blé", proxy="9410")

    codes, confidence, _reasons = propose(
        name_en="wheat flakes", name_fr="flocons de blé"
    )

    assert (codes, confidence) == ([], Confidence.NONE)


def test_a_food_only_openfoodfacts_names_is_a_low_confidence_proposal(
    ciqual: Source,
):
    food(ciqual, "9520", "Riz complet, cru")
    taxon("en:rice-flour", "rice flour", "farine de riz", code="9520")

    codes, confidence, reasons = propose(name_en="rice flour", name_fr="farine de riz")

    assert (codes, confidence, reasons) == (["9520"], Confidence.LOW, [(Reason.OFF,)])


def test_several_plain_foods_with_the_reference_name_make_a_low_confidence_one(
    ciqual: Source,
):
    food(ciqual, "13101", "Raisin Chasselas, cru")
    food(ciqual, "13621", "Raisin noir Muscat, cru")

    codes, confidence, _reasons = propose(name_fr="raisin")

    assert len(codes) == 2  # noqa: PLR2004
    assert confidence == Confidence.LOW


def test_nothing_is_proposed_when_nothing_fits(ciqual: Source):
    food(ciqual, "20100", "Chou, cru")

    assert propose(name_en="unobtainium") == ([], Confidence.NONE, [])


def test_two_codes_for_one_name_are_not_enough_for_high_confidence(ciqual: Source):
    food(ciqual, "1", "Échalote, crue")
    food(ciqual, "2", "Échalote, séchée")
    taxon("en:a", "shallot", "échalote", code="1")
    taxon("en:b", "shallot", "échalote", code="2")

    _codes, confidence, _reasons = propose(name_en="shallot", name_fr="échalote")

    assert confidence != Confidence.HIGH


# ----------------------------------------------------------------------------
# What is left out, and how many are shown
# ----------------------------------------------------------------------------
def test_a_food_the_reference_already_draws_on_is_not_proposed_again(
    ciqual: Source,
):
    linked = food(ciqual, "13007", "Cassis, cru")
    food(ciqual, "13008", "Cassis, surgelé, cru")
    reference = ReferenceIngredient.objects.create(name_fr="cassis")
    reference.source_foods.add(linked)

    [proposal] = propose_foods([reference])

    assert [c.food.code for c in proposal.candidates] == ["13008"]


def test_only_a_few_candidates_are_shown(ciqual: Source):
    for index in range(12):
        food(ciqual, str(index), f"Cassis, variété {index}")

    codes, _confidence, _reasons = propose(name_fr="cassis")

    assert len(codes) == 5  # noqa: PLR2004


def test_a_proposal_comes_for_each_reference_in_order(ciqual: Source):
    food(ciqual, "1", "Cassis, cru")
    food(ciqual, "2", "Groseille, crue")
    cassis = ReferenceIngredient.objects.create(name_fr="cassis")
    nothing = ReferenceIngredient.objects.create(name_en="unobtainium")
    groseille = ReferenceIngredient.objects.create(name_fr="groseille")

    proposals = propose_foods([cassis, nothing, groseille])

    assert [p.reference for p in proposals] == [cassis, nothing, groseille]
    assert [p.confidence for p in proposals] == [
        Confidence.MEDIUM,
        Confidence.NONE,
        Confidence.MEDIUM,
    ]


# ----------------------------------------------------------------------------
# Two traps found on the muesli
# ----------------------------------------------------------------------------
def test_a_name_is_compared_with_the_same_language_not_the_other(ciqual: Source):
    """ "Raisin" is the French for a grape and the English for a dried one."""
    food(ciqual, "13046", "Raisin sec", "Raisin")
    food(ciqual, "13045", "Raisin noir, cru", "Grape, black, raw")

    codes, _confidence, reasons = propose(name_en="grape", name_fr="raisin")

    assert codes[0] == "13045"
    assert Reason.NAME in reasons[0]
    assert Reason.NAME not in reasons[codes.index("13046")]


def test_the_hints_of_references_not_saved_yet_are_not_mixed_up(ciqual: Source):
    food(ciqual, "1", "Cassis, cru")
    food(ciqual, "2", "Groseille, crue")
    taxon("en:blackcurrant", "blackcurrant", "cassis", code="1")
    taxon("en:redcurrant", "redcurrant", "groseille", code="2")
    unsaved = [
        ReferenceIngredient(name_en="blackcurrant", name_fr="cassis"),
        ReferenceIngredient(name_en="redcurrant", name_fr="groseille"),
    ]

    first, second = propose_foods(unsaved)

    assert [first.candidates[0].food.code, second.candidates[0].food.code] == ["1", "2"]
    assert first.confidence == second.confidence == Confidence.HIGH


def test_a_code_given_for_the_same_word_in_the_other_language_is_not_a_hint(
    ciqual: Source,
):
    """Dried raisins (en:raisin) must not hint a code for the grape's French name."""
    food(ciqual, "13046", "Raisin sec", "Raisin")
    food(ciqual, "13045", "Raisin noir, cru", "Grape, black, raw")
    taxon("en:raisin", "raisin", "raisin sec", code="13046")
    taxon("en:grape", "grape", "raisin", code="99999")

    # The dried one: only its own code is a hint, so the two signals agree.
    codes, confidence, _reasons = propose(name_en="raisin", name_fr="raisin sec")

    assert (codes[0], confidence) == ("13046", Confidence.HIGH)
