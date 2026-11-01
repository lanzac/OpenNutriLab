"""
The nutrients a label declares, and the key OpenFoodFacts gives each.

Besides the eight every label declares (energy, fat, saturates, carbohydrates,
sugars, fibre, proteins, salt: seeded by migration 0002), a label may declare what
the product form asks for as well: they are on the label (`Nutrient.on_label`),
which is also what makes a declared figure a check of the estimate (see
estimate_validation). OpenFoodFacts keeps each in grams under `<key>_100g` (see
declared_nutrients_from_off). They are:

- the vitamins of annex XIII of Regulation 1169/2011, and the minerals of the same
  annex, with sodium, which a label gives beside the salt it makes;
- the parts of fat and of carbohydrates that Article 30 lets a label give
  (mono- and polyunsaturates, starch, polyols), with the fatty acids a claim asks for
  (omega-3 and omega-6, ALA, EPA, DHA, EPA + DHA), the trans fats, lactose, the sugars
  added, and cholesterol.

Not here: the other forms of a vitamin that CIQUAL gives, which a label does not
declare (retinol, vitamin D2 and D3, the folates in equivalents...); the fatty acids
CIQUAL gives that no claim asks for (butyric to stearic acid); the sugars it names
one by one (fructose, glucose, sucrose...); and what the catalogue has no word for
(caffeine, taurine, amino acids...). Vitamin B3 is niacin, which OpenFoodFacts calls
`vitamin-pp`.

The CIQUAL import and the derivations create these nutrients with `label_fields`;
`LABEL_ONLY` are those CIQUAL does not give, made by `ensure_label_only`. Migration
0029 sets them on a catalogue that already has them.
"""

from typing import NamedTuple

from opennutrilab.products.models import Nutrient

# Nutrient code -> OpenFoodFacts nutriment key. The vitamins are alone in their dict,
# as migration 0027 set them (its own copy is checked against this one).
LABEL_VITAMINS: dict[str, str] = {
    "vitamin_a": "vitamin-a",
    "vitamin_d": "vitamin-d",
    "vitamin_e": "vitamin-e",
    "vitamin_k": "vitamin-k",
    "vitamin_c": "vitamin-c",
    "vitamin_b1": "vitamin-b1",
    "vitamin_b2": "vitamin-b2",
    "vitamin_b3": "vitamin-pp",
    "vitamin_b5": "pantothenic-acid",
    "vitamin_b6": "vitamin-b6",
    "vitamin_b9": "vitamin-b9",
    "vitamin_b12": "vitamin-b12",
}

# What came after them (migration 0029). None: OpenFoodFacts has no key for it.
LABEL_MORE: dict[str, str | None] = {
    # Vitamins and the like.
    "biotin": "biotin",
    "beta_carotene": "beta-carotene",
    # Minerals.
    "sodium": "sodium",
    "potassium": "potassium",
    "chloride": "chloride",
    "calcium": "calcium",
    "phosphorus": "phosphorus",
    "magnesium": "magnesium",
    "iron": "iron",
    "zinc": "zinc",
    "copper": "copper",
    "manganese": "manganese",
    "fluoride": "fluoride",
    "selenium": "selenium",
    "chromium": "chromium",
    "molybdenum": "molybdenum",
    "iodine": "iodine",
    # Parts of fat.
    "monounsaturated_fat": "monounsaturated-fat",
    "polyunsaturated_fat": "polyunsaturated-fat",
    "trans_fat": "trans-fat",
    "omega_3": "omega-3-fat",
    "omega_6": "omega-6-fat",
    "alpha_linolenic_acid": "alpha-linolenic-acid",
    "linoleic_acid": "linoleic-acid",
    "oleic_acid": "oleic-acid",
    "arachidonic_acid": "arachidonic-acid",
    "epa": "eicosapentaenoic-acid",
    "dha": "docosahexaenoic-acid",
    "epa_dha": None,
    # Parts of carbohydrates.
    "lactose": "lactose",
    "added_sugars": "added-sugars",
    "starch": "starch",
    "polyols": "polyols",
    # The rest.
    "cholesterol": "cholesterol",
}

LABEL_NUTRIENTS: dict[str, str | None] = {**LABEL_VITAMINS, **LABEL_MORE}


class LabelOnly(NamedTuple):
    """A nutrient only a label gives: no CIQUAL food has it, so it has to be created."""

    name_en: str
    name_fr: str
    unit: Nutrient.Unit
    group: Nutrient.Group
    display_order: int
    # The nutrient it is part of.
    parent: str | None = None


# Where each is listed: with the nutrients of its kind (see ciqual_import, which
# numbers CIQUAL's from 100 by tens).
LABEL_ONLY: dict[str, LabelOnly] = {
    "added_sugars": LabelOnly(
        "Added sugars",
        "Sucres ajoutés",
        Nutrient.Unit.GRAM,
        Nutrient.Group.MACRONUTRIENT,
        385,
        parent="sugars",
    ),
    "trans_fat": LabelOnly(
        "Trans fatty acids",
        "Acides gras trans",
        Nutrient.Unit.GRAM,
        Nutrient.Group.FATTY_ACID,
        455,
        parent="fat",
    ),
    "fluoride": LabelOnly(
        "Fluoride", "Fluorure", Nutrient.Unit.MILLIGRAM, Nutrient.Group.MINERAL, 255
    ),
    "chromium": LabelOnly(
        "Chromium", "Chrome", Nutrient.Unit.MICROGRAM, Nutrient.Group.MINERAL, 275
    ),
    "molybdenum": LabelOnly(
        "Molybdenum", "Molybdène", Nutrient.Unit.MICROGRAM, Nutrient.Group.MINERAL, 276
    ),
    "biotin": LabelOnly(
        "Biotin (vitamin B8)",
        "Biotine (vitamine B8)",
        Nutrient.Unit.MICROGRAM,
        Nutrient.Group.VITAMIN,
        745,
    ),
}


def label_fields(code: str) -> dict[str, object]:
    """What a new nutrient `code` is made with to be on the label, if it is."""
    if code not in LABEL_NUTRIENTS:
        return {}
    key = LABEL_NUTRIENTS[code]
    return {"on_label": True} if key is None else {"on_label": True, "off_key": key}


def ensure_label_only() -> int:
    """Make the catalogue hold LABEL_ONLY, and return how many it had to create."""
    created = 0
    for code, new in LABEL_ONLY.items():
        _nutrient, was_created = Nutrient.objects.get_or_create(
            code=code,
            defaults={
                "name_en": new.name_en,
                "name_fr": new.name_fr,
                "unit": new.unit,
                "group": new.group,
                "display_order": new.display_order,
                "parent_id": new.parent,
                **label_fields(code),
            },
        )
        created += was_created
    return created
