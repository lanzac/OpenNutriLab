"""
The vitamins a label declares, and the key OpenFoodFacts gives each.

A label may declare the vitamins of annex XIII of Regulation 1169/2011, and the
product form asks for them as it does for the eight nutrients every label
declares: they are on the label (`Nutrient.on_label`), which is also what makes a
declared figure a check of the estimate (see estimate_validation). OpenFoodFacts
keeps each in grams under `<key>_100g` (see declared_nutrients_from_off).

Not here: biotin, which the catalogue lacks (CIQUAL does not give it), and the
other forms of a vitamin that CIQUAL gives, which a label does not declare
(retinol, vitamin D2 and D3, the folates in equivalents...). Vitamin B3 is niacin,
which OpenFoodFacts calls `vitamin-pp`. The minerals of the annex are not here
either.

The CIQUAL import and the derivations create these nutrients with `label_fields`,
and migration 0027 sets them on a catalogue that already has them.
"""

# Nutrient code -> OpenFoodFacts nutriment key.
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


def label_fields(code: str) -> dict[str, object]:
    """What a new nutrient `code` is made with to be on the label, if it is."""
    key = LABEL_VITAMINS.get(code)
    return {} if key is None else {"on_label": True, "off_key": key}
