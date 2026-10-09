from django.utils import translation

from opennutrilab.products.pnns import pnns_group_names


def test_every_group_has_a_name_in_french():
    """A group left out of the catalogue would be shown in English."""
    with translation.override("fr-fr"):
        names = pnns_group_names()

    untranslated = [word for word, name in names.items() if name == word]
    # These read the same in both languages.
    assert set(untranslated) <= {"Fruits"}
    assert len(names) > 40  # noqa: PLR2004


def test_the_groups_are_named_in_the_language_served():
    with translation.override("en"):
        assert pnns_group_names()["Fish Meat Eggs"] == "Fish, meat and eggs"
    with translation.override("fr-fr"):
        assert pnns_group_names()["Fish Meat Eggs"] == "Viandes, poissons et œufs"
