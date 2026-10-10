"""
How CIQUAL's constituents become nutrients of the catalogue.

CIQUAL gives each constituent a numeric code and a label that ends with its
unit ("Vitamine C (mg/100 g)"). The import reads names and units from the file;
what the file does not say, and the catalogue needs, is here: the nutrient's
code, its group and the nutrient it is part of, and a plainer name for the fatty
acids ("AG 12:0, laurique" becomes "Acide laurique (C12:0)"). A nutrient that
already exists with that CIQUAL code (the label's eight, seeded by migration) is
used as it is, and not changed.

Every constituent of the file must be in CONSTITUENTS or SKIPPED: a new one,
in a later CIQUAL release, is a decision to take, so the import refuses it.
"""

from typing import NamedTuple

from opennutrilab.products.models import Nutrient

ENERGY = Nutrient.Group.ENERGY
MACRO = Nutrient.Group.MACRONUTRIENT
FATTY = Nutrient.Group.FATTY_ACID
MINERAL = Nutrient.Group.MINERAL
VITAMIN = Nutrient.Group.VITAMIN
OTHER = Nutrient.Group.OTHER


class Constituent(NamedTuple):
    code: str
    group: Nutrient.Group
    parent: str | None = None


# CIQUAL code -> the nutrient it is. Parents come before their children.
CONSTITUENTS: dict[str, Constituent] = {
    # Energy. 327 is the EU 1169/2011 definition, the one labels follow.
    "327": Constituent("energy", ENERGY),
    "332": Constituent("energy_jones", ENERGY),
    "400": Constituent("water", MACRO),
    "10000": Constituent("ash", OTHER),
    "10004": Constituent("salt", OTHER),
    # Minerals.
    "10110": Constituent("sodium", MINERAL),
    "10120": Constituent("magnesium", MINERAL),
    "10150": Constituent("phosphorus", MINERAL),
    "10170": Constituent("chloride", MINERAL),
    "10190": Constituent("potassium", MINERAL),
    "10200": Constituent("calcium", MINERAL),
    "10251": Constituent("manganese", MINERAL),
    "10260": Constituent("iron", MINERAL),
    "10290": Constituent("copper", MINERAL),
    "10300": Constituent("zinc", MINERAL),
    "10340": Constituent("selenium", MINERAL),
    "10530": Constituent("iodine", MINERAL),
    # Protein: nitrogen x 6.25 is the labels' rule, the Jones factor CIQUAL's own.
    "25003": Constituent("proteins", MACRO),
    "25000": Constituent("proteins_jones", MACRO),
    # Carbohydrates.
    "31000": Constituent("carbohydrates", MACRO),
    "32000": Constituent("sugars", MACRO, "carbohydrates"),
    "32210": Constituent("fructose", MACRO, "sugars"),
    "32220": Constituent("galactose", MACRO, "sugars"),
    "32250": Constituent("glucose", MACRO, "sugars"),
    "32410": Constituent("lactose", MACRO, "sugars"),
    "32430": Constituent("maltose", MACRO, "sugars"),
    "32480": Constituent("sucrose", MACRO, "sugars"),
    "33110": Constituent("starch", MACRO, "carbohydrates"),
    "34000": Constituent("polyols", MACRO, "carbohydrates"),
    "34100": Constituent("fiber", MACRO),
    # Fats and fatty acids.
    "40000": Constituent("fat", MACRO),
    "40302": Constituent("saturated_fat", FATTY, "fat"),
    "40303": Constituent("monounsaturated_fat", FATTY, "fat"),
    "40304": Constituent("polyunsaturated_fat", FATTY, "fat"),
    "40400": Constituent("butyric_acid", FATTY, "saturated_fat"),
    "40600": Constituent("caproic_acid", FATTY, "saturated_fat"),
    "40800": Constituent("caprylic_acid", FATTY, "saturated_fat"),
    "41000": Constituent("capric_acid", FATTY, "saturated_fat"),
    "41200": Constituent("lauric_acid", FATTY, "saturated_fat"),
    "41400": Constituent("myristic_acid", FATTY, "saturated_fat"),
    "41600": Constituent("palmitic_acid", FATTY, "saturated_fat"),
    "41800": Constituent("stearic_acid", FATTY, "saturated_fat"),
    "41819": Constituent("oleic_acid", FATTY, "monounsaturated_fat"),
    "41826": Constituent("linoleic_acid", FATTY, "polyunsaturated_fat"),
    "41833": Constituent("alpha_linolenic_acid", FATTY, "polyunsaturated_fat"),
    "42046": Constituent("arachidonic_acid", FATTY, "polyunsaturated_fat"),
    "42053": Constituent("epa", FATTY, "polyunsaturated_fat"),
    "42263": Constituent("dha", FATTY, "polyunsaturated_fat"),
    # Vitamins. 51104 is vitamin A in retinol equivalents, 56702 folates in
    # dietary folate equivalents: CIQUAL 2025 gives them directly.
    "51104": Constituent("vitamin_a", VITAMIN),
    "51200": Constituent("retinol", VITAMIN),
    "51330": Constituent("beta_carotene", VITAMIN),
    "52100": Constituent("vitamin_d", VITAMIN),
    "52200": Constituent("vitamin_d2", VITAMIN, "vitamin_d"),
    "52300": Constituent("vitamin_d3", VITAMIN, "vitamin_d"),
    "53100": Constituent("vitamin_e", VITAMIN),
    "54101": Constituent("vitamin_k1", VITAMIN),
    "54104": Constituent("vitamin_k2", VITAMIN),
    "55100": Constituent("vitamin_c", VITAMIN),
    "56100": Constituent("vitamin_b1", VITAMIN),
    "56200": Constituent("vitamin_b2", VITAMIN),
    "56310": Constituent("vitamin_b3", VITAMIN),
    "56400": Constituent("vitamin_b5", VITAMIN),
    "56500": Constituent("vitamin_b6", VITAMIN),
    "56600": Constituent("vitamin_b12", VITAMIN),
    "56700": Constituent("vitamin_b9", VITAMIN),
    "56702": Constituent("vitamin_b9_dfe", VITAMIN),
    "56704": Constituent("intrinsic_folates", VITAMIN, "vitamin_b9"),
    "56708": Constituent("folic_acid", VITAMIN, "vitamin_b9"),
    "71010": Constituent("alpha_tocopherol", VITAMIN),
    # Others.
    "60000": Constituent("alcohol", OTHER),
    "65000": Constituent("organic_acids", OTHER),
    "75100": Constituent("cholesterol", OTHER),
}

# Nutrient code -> (English, French) name, where CIQUAL's own is a code and a
# name ("AG 18:3 c9,c12,c15 (n-3), alpha-linolénique"). The omega family is said
# for the acids whose name does not tell it, but not for EPA and DHA, which are
# known as omega-3 by their initials.
NAMES: dict[str, tuple[str, str]] = {
    "monounsaturated_fat": (
        "Monounsaturated fatty acids",
        "Acides gras monoinsaturés",
    ),
    "polyunsaturated_fat": (
        "Polyunsaturated fatty acids",
        "Acides gras polyinsaturés",
    ),
    "butyric_acid": ("Butyric acid (C4:0)", "Acide butyrique (C4:0)"),
    "caproic_acid": ("Caproic acid (C6:0)", "Acide caproïque (C6:0)"),
    "caprylic_acid": ("Caprylic acid (C8:0)", "Acide caprylique (C8:0)"),
    "capric_acid": ("Capric acid (C10:0)", "Acide caprique (C10:0)"),
    "lauric_acid": ("Lauric acid (C12:0)", "Acide laurique (C12:0)"),
    "myristic_acid": ("Myristic acid (C14:0)", "Acide myristique (C14:0)"),
    "palmitic_acid": ("Palmitic acid (C16:0)", "Acide palmitique (C16:0)"),
    "stearic_acid": ("Stearic acid (C18:0)", "Acide stéarique (C18:0)"),
    "oleic_acid": ("Oleic acid (omega-9)", "Acide oléique (oméga-9)"),
    "linoleic_acid": (
        "Linoleic acid (LA, omega-6)",
        "Acide linoléique (LA, oméga-6)",
    ),
    "alpha_linolenic_acid": (
        "Alpha-linolenic acid (ALA, omega-3)",
        "Acide alpha-linolénique (ALA, oméga-3)",
    ),
    "arachidonic_acid": (
        "Arachidonic acid (AA, omega-6)",
        "Acide arachidonique (AA, oméga-6)",
    ),
    "epa": ("EPA", "EPA"),
    "dha": ("DHA", "DHA"),
}

# Constituents left out on purpose, and why.
SKIPPED: dict[str, str] = {
    "328": "Energy in kcal: the same energy as 327, which the catalogue gives in kJ.",
    "333": "Energy in kcal: the same energy as 332, which the catalogue gives in kJ.",
}
