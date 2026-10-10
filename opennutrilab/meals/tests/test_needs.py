from decimal import Decimal

import pytest
from django.utils import translation

from opennutrilab.meals.services.energy import KCAL_PER_MJ
from opennutrilab.meals.services.energy import KJ_PER_KCAL
from opennutrilab.meals.services.energy import Person
from opennutrilab.meals.services.needs import Kind
from opennutrilab.meals.services.needs import Need
from opennutrilab.meals.services.needs import Needs
from opennutrilab.meals.services.needs import NoReferenceError
from opennutrilab.meals.services.needs import (
    _merged,  # pyright: ignore[reportPrivateUsage]
)
from opennutrilab.meals.services.needs import need_name
from opennutrilab.meals.services.needs import needs_for
from opennutrilab.meals.services.needs import references
from opennutrilab.products.models import Nutrient

D = Decimal
MAN = Person("male", 31, D(61), D(180))
WOMAN = Person("female", 40, D(58), D(165))


def need(needs: Needs, *codes: str) -> Need:
    [found] = [n for n in needs.nutrients if n.nutrients == codes]
    return found


def test_every_nutrient_the_references_name_is_in_the_catalogue(catalogue: None):
    data = references()
    named = {code for entry in data["references"] for code in entry["nutrients"]}
    named |= {
        code
        for ratio in data["ratios"]
        for code in (*ratio["numerator"], *ratio["denominator"])
    }

    assert named - set(Nutrient.objects.values_list("code", flat=True)) == set()
    assert {e["source"] for e in data["references"]} <= data["sources"].keys()


def test_a_mans_needs_are_the_tables_figures():
    needs = needs_for(MAN, D("1.7"))

    vitamin_c = need(needs, "vitamin_c")
    assert (vitamin_c.low, vitamin_c.high) == (D(110), None)
    assert (vitamin_c.low_kind, vitamin_c.low_source) == (Kind.RNP, "anses-2021")
    assert need(needs, "zinc").low == D(14)
    assert need(needs, "zinc").high == D(25)
    assert need(needs, "iron").low == D(11)
    assert need(needs, "magnesium").low == D(380)
    # No upper limit for magnesium: the opinion's is on supplements only.
    assert need(needs, "magnesium").high is None
    assert need(needs, "vitamin_a").low == D(750)
    # The vitamin A limit is on retinol, the folic acid one on folic acid.
    assert need(needs, "retinol").high == D(3000)
    assert need(needs, "folic_acid").high == D(1000)


def test_calcium_depends_on_the_age():
    assert need(needs_for(MAN._replace(age=24), D("1.6")), "calcium").low == D(1000)
    assert need(needs_for(MAN._replace(age=25), D("1.6")), "calcium").low == D(950)


def test_a_womans_iron_depends_on_her_losses():
    assert need(needs_for(WOMAN, D("1.6")), "iron").low == D(11)
    high = needs_for(WOMAN, D("1.6"), high_iron_losses=True)
    assert need(high, "iron").low == D(16)
    assert need(high, "vitamin_a").low == D(650)
    assert need(high, "magnesium").low == D(300)
    # A man's iron is a man's, whatever is said of losses.
    assert need(needs_for(MAN, D("1.6"), high_iron_losses=True), "iron").low == 11  # noqa: PLR2004


def test_what_is_given_for_the_energy_is_worked_out_for_the_persons():
    needs = needs_for(MAN, D("1.7"))
    kcal = needs.energy

    # 35 to 40 % of the energy as fat, at 9 kcal a gram.
    fat = need(needs, "fat")
    assert (fat.low, fat.high) == (kcal * 35 / 100 / 9, kcal * 40 / 100 / 9)
    assert fat.energy_share is not None
    assert (fat.energy_share.low, fat.energy_share.high) == (D(35), D(40))
    # 0.1 mg of thiamin for each MJ.
    assert need(needs, "vitamin_b1").low == D("0.1") * kcal / KCAL_PER_MJ
    # The energy itself, in kJ as the catalogue has it, within 5 %.
    energy = need(needs, "energy")
    assert energy.low == kcal * D("0.95") * KJ_PER_KCAL
    assert energy.high == kcal * D("1.05") * KJ_PER_KCAL


def test_a_need_can_be_on_a_sum_of_nutrients():
    needs = needs_for(MAN, D("1.7"))

    assert need(needs, "epa", "dha").low == D("0.5")
    saturated = need(needs, "lauric_acid", "myristic_acid", "palmitic_acid")
    assert saturated.high == needs.energy * 8 / 100 / 9
    assert saturated.low is None


def test_oleic_acid_has_the_2011_recommended_share_of_the_energy():
    needs = needs_for(MAN, D("1.7"))

    oleic = need(needs, "oleic_acid")
    assert oleic.low is not None
    assert oleic.high is not None
    # Worked out in another order than the code's: equal to the last digits only.
    assert oleic.low == pytest.approx(needs.energy * 15 / 100 / 9)
    assert oleic.high == pytest.approx(needs.energy * 20 / 100 / 9)
    assert round(oleic.low) == 44  # noqa: PLR2004
    assert round(oleic.high) == 59  # noqa: PLR2004
    assert (oleic.low_kind, oleic.high_kind) == (Kind.ANC, Kind.ANC)
    assert (oleic.low_source, oleic.high_source) == ("anses-2011", "anses-2011")
    assert oleic.energy_share is not None
    assert (oleic.energy_share.low, oleic.energy_share.high) == (D(15), D(20))


def test_a_need_counts_as_much_as_the_others_unless_its_reference_says_more():
    needs = needs_for(MAN, D("1.7"))

    assert need(needs, "oleic_acid").priority == D(3)
    others = {n.priority for n in needs.nutrients if n.nutrients != ("oleic_acid",)}
    assert others == {D(1)}


def test_the_two_ends_of_a_need_keep_the_higher_priority():
    low = Need(("x",), D(1), None, "rnp", "", "a", "", priority=D(2))
    high = Need(("x",), None, D(5), "", "lss", "", "b", priority=D(3))

    [merged] = _merged([low, high])

    assert (merged.low, merged.high, merged.priority) == (D(1), D(5), D(3))


def test_a_sum_is_called_by_the_name_the_references_give_it(catalogue: None):
    needs = needs_for(MAN, D("1.7"))
    catalogue_by_code = Nutrient.objects.in_bulk()
    saturated = need(needs, "lauric_acid", "myristic_acid", "palmitic_acid")
    both = need(needs, "epa", "dha")

    with translation.override("fr"):
        assert (
            need_name(saturated, catalogue_by_code)
            == "Acides laurique + myristique + palmitique"
        )
        assert need_name(both, catalogue_by_code) == "EPA + DHA"
    with translation.override("en"):
        assert (
            need_name(saturated, catalogue_by_code)
            == "Lauric + myristic + palmitic acids"
        )


def test_a_need_with_no_name_of_its_own_takes_its_nutrients(catalogue: None):
    needs = needs_for(MAN, D("1.7"))
    catalogue_by_code = Nutrient.objects.in_bulk()

    with translation.override("fr"):
        assert (
            need_name(need(needs, "oleic_acid"), catalogue_by_code)
            == "Acide oléique (oméga-9)"
        )
    with translation.override("en"):
        assert (
            need_name(need(needs, "oleic_acid"), catalogue_by_code)
            == "Oleic acid (omega-9)"
        )


def test_only_the_sums_have_names_of_their_own():
    named = {
        tuple(entry["nutrients"])
        for entry in references()["references"]
        if "name_en" in entry or "name_fr" in entry
    }

    assert named == {
        ("lauric_acid", "myristic_acid", "palmitic_acid"),
        ("epa", "dha"),
    }
    for entry in references()["references"]:
        assert ("name_en" in entry) == ("name_fr" in entry)


def test_the_two_ends_of_a_need_can_come_from_two_opinions():
    vitamin_e = need(needs_for(MAN, D("1.7")), "vitamin_e")

    assert (vitamin_e.low, vitamin_e.low_kind, vitamin_e.low_source) == (
        D(10),
        Kind.AS,
        "anses-2021",
    )
    assert (vitamin_e.high, vitamin_e.high_kind, vitamin_e.high_source) == (
        D(300),
        Kind.CONSTRAINT,
        "anses-2016",
    )


def test_two_references_for_the_same_end_are_refused():
    twice = Need(("zinc",), D(14), None, Kind.RNP, "", "anses-2021", "")

    with pytest.raises(ValueError, match="same end"):
        _merged([twice, twice])


def test_the_ratios_are_anses_and_the_users_targets_within_the_tolerance():
    needs = needs_for(
        MAN,
        D("1.7"),
        targets=(({"dha": D(1)}, {"epa": D(1)}, D(1)),),
        tolerance=D("0.2"),
    )

    anses, targets = needs.ratios[:2], needs.ratios[2:]
    assert [(r.numerator, r.high) for r in anses] == [
        ({"linoleic_acid": D(1)}, D(5)),
        ({"sodium": D("0.043498")}, D(1)),
    ]
    assert [(r.low, r.high, r.kind, r.source) for r in targets] == [
        (D("0.8"), D("1.2"), Kind.TARGET, "user")
    ]


def test_the_references_are_for_adults():
    with pytest.raises(NoReferenceError):
        needs_for(MAN._replace(age=17), D("1.6"))
