from decimal import Decimal
from pathlib import Path

import pytest

from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import ReferenceIngredient
from opennutrilab.products.models import Source
from opennutrilab.products.models import SourceFood
from opennutrilab.products.models import SourceFoodNutrient
from opennutrilab.products.services.ciqual_import import ensure_nutrients
from opennutrilab.products.services.ciqual_import import read_constituents
from opennutrilab.products.services.reference_proposals import Confidence
from opennutrilab.products.services.reference_proposals import Reason
from opennutrilab.products.services.reference_proposals import link_confident_foods
from opennutrilab.products.services.reference_proposals import propose_foods

pytestmark = pytest.mark.django_db


@pytest.fixture
def ciqual(db: None) -> Source:
    return Source.objects.create(code="ciqual-2025", name="Ciqual", version="2025")


def food(
    source: Source, code: str, name_fr: str, name_en: str = "", subgroup: str = ""
) -> SourceFood:
    return SourceFood.objects.create(
        source=source,
        code=code,
        name_fr=name_fr,
        name_en=name_en,
        food_subgroup=subgroup,
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


def test_a_dish_made_of_the_food_comes_after_it_and_is_marked_prepared(
    ciqual: Source,
):
    food(ciqual, "32140", "Flocons d'avoine", "Oat flakes")
    food(ciqual, "9313", "Bouillie de flocons d'avoine, cuite", "Oat porridge")

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


# ----------------------------------------------------------------------------
# A name that does not say the form
# ----------------------------------------------------------------------------
PULSES = "légumineuses"


@pytest.fixture
def red_beans(ciqual: Source) -> None:
    food(ciqual, "20525", "Haricot rouge, sec", "Red kidney bean, dried", PULSES)
    food(
        ciqual,
        "20503",
        "Haricot rouge, bouilli/cuit à l'eau",
        "Red kidney bean, boiled/cooked in water",
        PULSES,
    )
    food(
        ciqual,
        "20524",
        "Haricot rouge, appertisé, égoutté",
        "Red kidney bean, canned, drained",
        PULSES,
    )
    food(ciqual, "20999", "Haricot rouge, sec, farine", "Red kidney bean flour", PULSES)


def propose_one(**names: str):
    [proposal] = propose_foods([ReferenceIngredient.objects.create(**names)])
    return proposal


def test_a_name_with_no_form_holds_the_forms_of_the_food_with_a_default(
    red_beans: None,
):
    proposal = propose_one(name_en="red kidney bean", name_fr="haricot rouge")

    # A pulse comes dried: that is the food a bare name means.
    assert [c.food.code for c in proposal.candidates] == ["20525", "20503", "20524"]
    assert proposal.default is not None
    assert proposal.default.code == "20525"
    assert all(Reason.FORM in c.reasons for c in proposal.candidates)
    assert [Reason.DEFAULT in c.reasons for c in proposal.candidates] == [
        True,
        False,
        False,
    ]


def test_the_forms_are_never_a_high_confidence_proposal(
    red_beans: None,
):
    taxon("en:red-kidney-bean", "red kidney bean", "haricot rouge", code="20503")

    proposal = propose_one(name_en="red kidney bean", name_fr="haricot rouge")

    assert proposal.confidence == Confidence.MEDIUM


def test_a_cooked_form_is_not_marked_as_prepared_when_it_is_one_of_the_forms(
    red_beans: None,
):
    proposal = propose_one(name_fr="haricot rouge")

    assert all(Reason.PREPARED not in c.reasons for c in proposal.candidates)


def test_the_default_is_the_raw_form_outside_vegetables_and_pulses(ciqual: Source):
    food(ciqual, "1", "Poulet, cuit", "Chicken, cooked", "viandes cuites")
    food(ciqual, "2", "Poulet, cru", "Chicken, raw", "viandes crues")

    proposal = propose_one(name_fr="poulet")

    assert proposal.default is not None
    assert proposal.default.code == "2"


def test_the_default_is_the_raw_form_for_a_vegetable(ciqual: Source):
    food(ciqual, "1", "Betterave rouge, crue", "Beetroot, raw", "légumes")
    food(ciqual, "2", "Betterave rouge, cuite", "Beetroot, cooked", "légumes")

    proposal = propose_one(name_en="beetroot", name_fr="betterave")

    # A label says "cuite" when it was used cooked.
    assert proposal.default is not None
    assert proposal.default.code == "1"


def test_the_boiled_food_is_taken_before_the_other_cooked_ones(ciqual: Source):
    food(ciqual, "1", "Épinard, cuit", "Spinach, cooked", "légumes")
    food(
        ciqual,
        "2",
        "Épinard, bouilli/cuit à l'eau",
        "Spinach, boiled/cooked in water",
        "légumes",
    )

    proposal = propose_one(name_fr="épinard")

    assert proposal.default is not None
    assert proposal.default.code == "2"


def test_a_food_that_is_frozen_is_the_same_form_as_the_fresh_one(ciqual: Source):
    food(ciqual, "13015", "Framboise, crue", "Raspberry, raw", "fruits")
    food(
        ciqual, "13136", "Framboise, surgelée, crue", "Raspberry, frozen, raw", "fruits"
    )

    assert propose_one(name_en="raspberry", name_fr="framboise").default is None


def test_a_dried_vegetable_is_shown_among_the_forms_but_not_ticked(ciqual: Source):
    food(ciqual, "1", "Tomate, crue", "Tomato, raw", "légumes")
    food(ciqual, "2", "Tomate, séchée", "Tomato, dried", "légumes")

    proposal = propose_one(name_en="tomato", name_fr="tomate")

    assert proposal.default is not None
    assert proposal.default.code == "1"
    # A label says "tomates séchées" when it means them.
    assert [(c.food.code, c.unlikely) for c in proposal.candidates] == [
        ("1", False),
        ("2", True),
    ]


@pytest.mark.parametrize("subgroup", ["herbes", "épices", "légumineuses"])
def test_a_dried_form_is_ticked_where_the_bare_name_usually_means_it(
    ciqual: Source, subgroup: str
):
    food(ciqual, "1", "Basilic, frais", "Basil, fresh", subgroup)
    food(ciqual, "2", "Basilic, séché", "Basil, dried", subgroup)

    proposal = propose_one(name_en="basil", name_fr="basilic")

    assert sorted((c.food.code, c.unlikely) for c in proposal.candidates) == [
        ("1", False),
        ("2", False),
    ]


def test_a_dried_form_is_never_the_default_where_a_label_names_it_apart(
    ciqual: Source,
):
    food(ciqual, "1", "Abricot, séché", "Apricot, dried", "fruits")
    food(ciqual, "2", "Abricot, cuit", "Apricot, cooked", "fruits")

    proposal = propose_one(name_en="apricot", name_fr="abricot")

    assert proposal.default is not None
    assert proposal.default.code == "2"


def test_another_food_with_the_same_start_is_not_a_form_of_it(ciqual: Source):
    food(ciqual, "1", "Tomate, crue", "Tomato, raw", "légumes")
    food(ciqual, "2", "Tomate verte, crue", "Tomato, green, raw", "légumes")
    food(ciqual, "3", "Tomate, cuite", "Tomato, cooked", "légumes")

    proposal = propose_one(name_en="tomato", name_fr="tomate")

    assert {c.food.code for c in proposal.candidates} == {"1", "3"}


def test_no_added_salt_does_not_make_another_food(ciqual: Source):
    food(
        ciqual,
        "9321",
        "Orge perlée, crue",
        "Pearl barley, raw",
        "pâtes, riz et céréales",
    )
    food(
        ciqual,
        "9322",
        "Orge perlée, bouillie/cuite à l'eau, sans sel ajouté",
        "Pearl barley, boiled/cooked in water, no added salt",
        "pâtes, riz et céréales",
    )

    proposal = propose_one(name_en="pearl barley", name_fr="orge perlée")

    assert {c.food.code for c in proposal.candidates} == {"9321", "9322"}
    assert proposal.default is not None
    assert proposal.default.code == "9321"


def test_a_reference_that_says_its_form_has_no_forms_to_choose_from(ciqual: Source):
    food(ciqual, "1", "Betterave rouge, crue", "Beetroot, raw", "légumes")
    food(ciqual, "2", "Betterave rouge, cuite", "Beetroot, cooked", "légumes")

    assert propose_one(name_fr="betterave cuite").default is None


def test_one_food_alone_is_not_a_choice(ciqual: Source):
    food(ciqual, "1", "Betterave rouge, crue", "Beetroot, raw", "légumes")

    assert propose_one(name_en="beetroot", name_fr="betterave").default is None


# ----------------------------------------------------------------------------
# Linking without a curator: only what is certain
# ----------------------------------------------------------------------------
def test_a_high_confidence_food_is_linked_and_the_reference_stays_to_review(
    ciqual: Source,
):
    cassis = food(ciqual, "13007", "Cassis, cru", "Blackcurrant, raw")
    taxon("en:blackcurrant", "blackcurrant", "cassis", code="13007")
    reference = ReferenceIngredient.objects.create(
        name_en="blackcurrant", name_fr="cassis", description="Created."
    )

    assert link_confident_foods([reference]) == [cassis]

    reference.refresh_from_db()
    assert list(reference.source_foods.all()) == [cassis]
    assert reference.status == ReferenceIngredient.Status.TO_REVIEW
    assert reference.description.startswith("Created. Linked to ciqual-2025 13007")


def test_a_medium_confidence_food_is_left_to_the_curator(ciqual: Source):
    food(ciqual, "20901", "Soja, graine entière", "Soybean, whole")
    reference = ReferenceIngredient.objects.create(name_en="soya", name_fr="soja")

    assert link_confident_foods([reference]) == []
    assert not reference.source_foods.exists()


def test_forms_are_left_to_the_curator_even_when_openfoodfacts_agrees(
    red_beans: None,
):
    taxon("en:red-kidney-bean", "red kidney bean", "haricot rouge", code="20503")
    reference = ReferenceIngredient.objects.create(
        name_en="red kidney bean", name_fr="haricot rouge"
    )

    assert link_confident_foods([reference]) == []
    assert not reference.source_foods.exists()


def test_a_reference_that_already_has_a_food_is_not_touched(ciqual: Source):
    mine = food(ciqual, "1", "Cassis, surgelé, cru")
    food(ciqual, "13007", "Cassis, cru", "Blackcurrant, raw")
    taxon("en:blackcurrant", "blackcurrant", "cassis", code="13007")
    reference = ReferenceIngredient.objects.create(
        name_en="blackcurrant", name_fr="cassis"
    )
    reference.source_foods.add(mine)

    assert link_confident_foods([reference]) == []
    assert list(reference.source_foods.all()) == [mine]


# ----------------------------------------------------------------------------
# Foods that differ though no word of state says so
# ----------------------------------------------------------------------------
CONSTITUENTS_FILE = Path(__file__).parents[1] / "data" / "ciqual_const_2025.xml"


def measured(food: SourceFood, energy: str, water: str) -> None:
    for code, amount in (("energy", energy), ("water", water)):
        SourceFoodNutrient.objects.create(
            food=food, nutrient=Nutrient.objects.get(code=code), amount=Decimal(amount)
        )


@pytest.fixture
def catalogue(ciqual: Source) -> Source:
    ensure_nutrients(read_constituents(CONSTITUENTS_FILE))
    return ciqual


def test_foods_of_a_name_that_differ_a_lot_are_alternatives_with_a_default(
    catalogue: Source,
):
    leaf = food(catalogue, "11094", "Coriandre, fraiche", "Coriander, fresh", "épices")
    seed = food(catalogue, "11026", "Coriandre, graine", "Coriander, seed", "épices")
    measured(leaf, energy="95", water="88")
    measured(seed, energy="1470", water="9")

    proposal = propose_one(name_en="coriander", name_fr="coriandre")

    # The one whose name says its state comes first, though the seed's is shorter.
    assert [c.food.code for c in proposal.candidates] == ["11094", "11026"]
    assert proposal.default == leaf
    assert all(Reason.DIFFERS in c.reasons for c in proposal.candidates)
    # A seed is not the leaf in another form: the default is a guess.
    assert proposal.confidence == Confidence.LOW


def test_foods_of_a_name_that_are_alike_are_not_a_choice(catalogue: Source):
    chasselas = food(catalogue, "1", "Raisin Chasselas, cru", "Grape, Chasselas, raw")
    muscat = food(catalogue, "2", "Raisin Muscat, cru", "Grape, Muscat, raw")
    measured(chasselas, energy="290", water="80")
    measured(muscat, energy="300", water="79")

    assert propose_one(name_en="grape", name_fr="raisin").default is None


def test_a_difference_of_water_alone_is_enough(catalogue: Source):
    fresh = food(catalogue, "1", "Gingembre, racine fraîche", "Ginger, fresh root")
    ground = food(catalogue, "2", "Gingembre, poudre", "Ginger, ground")
    measured(fresh, energy="320", water="80")
    measured(ground, energy="330", water="9")

    assert propose_one(name_fr="gingembre").default is not None


def test_foods_with_no_measure_are_not_told_apart(catalogue: Source):
    food(catalogue, "1", "Coriandre, fraiche")
    food(catalogue, "2", "Coriandre, graine")

    assert propose_one(name_fr="coriandre").default is None


def test_too_many_foods_under_one_name_are_a_family_to_choose_from(
    catalogue: Source,
):
    for index in range(9):
        measured(
            food(
                catalogue, str(index), f"Lait, variété {index}", f"Milk, kind {index}"
            ),
            energy=str(100 + 100 * index),
            water="88",
        )

    assert propose_one(name_en="milk", name_fr="lait").default is None


def test_the_words_of_state_still_find_what_the_figures_do_not(catalogue: Source):
    """Raw and cooked beetroot: the same energy and water, a ninth of the folates."""
    raw = food(catalogue, "1", "Betterave rouge, crue", "Beetroot, raw", "légumes")
    cooked = food(
        catalogue, "2", "Betterave rouge, cuite", "Beetroot, cooked", "légumes"
    )
    measured(raw, energy="170", water="87.6")
    measured(cooked, energy="180", water="88.3")

    proposal = propose_one(name_en="beetroot", name_fr="betterave")
    assert {c.food for c in proposal.candidates} == {raw, cooked}
    assert proposal.default == raw


def give(food: SourceFood, **amounts: str) -> None:
    for code, amount in amounts.items():
        SourceFoodNutrient.objects.create(
            food=food, nutrient=Nutrient.objects.get(code=code), amount=Decimal(amount)
        )


def test_wheat_flours_that_differ_in_vitamins_and_fibre_are_alternatives(
    catalogue: Source,
):
    """White and wholemeal flour have the same energy and water."""
    white = food(catalogue, "9440", "Farine de blé T45", "Wheat flour, type 45")
    whole = food(catalogue, "9415", "Farine de blé T150", "Wheat flour, type 150")
    give(white, energy="1480", water="13", fiber="3.5", zinc="0.8", vitamin_b9_dfe="18")
    give(
        whole, energy="1450", water="13", fiber="10.2", zinc="2.5", vitamin_b9_dfe="52"
    )

    proposal = propose_one(name_en="wheat flour", name_fr="farine de blé")

    assert {c.food.code for c in proposal.candidates} == {"9440", "9415"}
    assert all(Reason.DIFFERS in c.reasons for c in proposal.candidates)


def test_one_nutrient_that_differs_is_not_a_choice(catalogue: Source):
    one = food(catalogue, "1", "Farine de blé T45", "Wheat flour, type 45")
    other = food(catalogue, "2", "Farine de blé T55", "Wheat flour, type 55")
    give(one, energy="1480", water="13", zinc="0.8")
    give(other, energy="1470", water="13", zinc="2.5")

    assert propose_one(name_en="wheat flour", name_fr="farine de blé").default is None


def test_a_difference_too_small_to_matter_in_a_label_is_not_a_choice(
    catalogue: Source,
):
    """Twice as much, but of a vitamin the food has almost none of."""
    one = food(catalogue, "1", "Farine de blé T45", "Wheat flour, type 45")
    other = food(catalogue, "2", "Farine de blé T55", "Wheat flour, type 55")
    give(one, energy="1480", water="13", vitamin_b1="0.01", vitamin_b2="0.01")
    give(other, energy="1470", water="13", vitamin_b1="0.02", vitamin_b2="0.02")

    assert propose_one(name_en="wheat flour", name_fr="farine de blé").default is None


def test_selenium_is_not_counted_for_it_swings_without_a_reason(catalogue: Source):
    one = food(catalogue, "1", "Farine de blé T45", "Wheat flour, type 45")
    other = food(catalogue, "2", "Farine de blé T55", "Wheat flour, type 55")
    give(one, energy="1480", water="13", selenium="0.2", iodine="1")
    give(other, energy="1470", water="13", selenium="20", iodine="50")

    assert propose_one(name_en="wheat flour", name_fr="farine de blé").default is None


def test_what_a_name_says_besides_its_state_does_not_split_the_forms(
    catalogue: Source,
):
    food(
        catalogue,
        "20066",
        "Maïs doux, appertisé, égoutté",
        "Corn, sweet, canned, drained",
        "légumes",
    )
    food(
        catalogue,
        "20049",
        "Maïs doux, en épis, cuit",
        "Corn, on the cob, cooked",
        "légumes",
    )
    food(catalogue, "20233", "Maïs doux, surgelé, cru", "Corn, frozen, raw", "légumes")
    food(
        catalogue,
        "20108",
        "Maïs doux, en épis, surgelé, cru",
        "Corn, on the cob, frozen, raw",
        "légumes",
    )

    proposal = propose_one(name_en="corn", name_fr="maïs")

    # One food for each of the three forms, the plainer of the two raw ones.
    assert {c.food.code for c in proposal.candidates} == {"20066", "20049", "20233"}
    assert proposal.default is not None
    assert proposal.default.code == "20233"


def test_forms_of_one_food_are_medium_confidence_and_other_foods_are_low(
    ciqual: Source,
):
    food(ciqual, "1", "Champignon, cèpe, cru", "Mushroom, cep, raw", "légumes")
    food(
        ciqual,
        "2",
        "Champignon, shiitaké, cuit",
        "Mushroom, shiitake, cooked",
        "légumes",
    )
    food(ciqual, "3", "Aubergine, crue", "Eggplant, raw", "légumes")
    food(ciqual, "4", "Aubergine, cuite", "Eggplant, cooked", "légumes")

    assert (
        propose_one(name_en="mushroom", name_fr="champignon").confidence
        == Confidence.LOW
    )
    assert (
        propose_one(name_en="eggplant", name_fr="aubergine").confidence
        == Confidence.MEDIUM
    )


def test_a_dried_pulse_is_the_default_and_a_fresh_herb_is_too(ciqual: Source):
    """A bare name is the food as it comes: dry for a pulse, fresh for a herb."""
    food(ciqual, "1", "Lentille, sèche", "Lentil, dried", "légumineuses")
    food(
        ciqual,
        "2",
        "Lentille, bouillie/cuite à l'eau",
        "Lentil, boiled",
        "légumineuses",
    )
    food(ciqual, "3", "Persil, frais", "Parsley, fresh", "herbes")
    food(ciqual, "4", "Persil, séché", "Parsley, dried", "herbes")

    lentils = propose_one(name_en="lentil", name_fr="lentille")
    parsley = propose_one(name_en="parsley", name_fr="persil")

    assert lentils.default is not None
    assert lentils.default.code == "1"
    assert parsley.default is not None
    assert parsley.default.code == "3"
