from django.db import migrations

# What a label declares besides the eight and the vitamins of migration 0027, with
# the key of OpenFoodFacts (see services.label_nutrients). Copied here so that this
# migration does not change when that module does.
LABEL_MORE = {
    "biotin": "biotin",
    "beta_carotene": "beta-carotene",
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
    "lactose": "lactose",
    "added_sugars": "added-sugars",
    "starch": "starch",
    "polyols": "polyols",
    "cholesterol": "cholesterol",
}

# The nutrients no source gives, and EPA + DHA, which the derivations create: code ->
# (English, French, unit, group, display order, parent). Made on a catalogue the CIQUAL
# import has filled (it has the vitamin C), as the import would make them; a catalogue
# without it is left as it is, the import making them on its first run.
CREATED = {
    "added_sugars": (
        "Added sugars",
        "Sucres ajoutés",
        "g",
        "macronutrient",
        385,
        "sugars",
    ),
    "trans_fat": ("Trans fatty acids", "Acides gras trans", "g", "fatty_acid", 455, "fat"),
    "fluoride": ("Fluoride", "Fluorure", "mg", "mineral", 255, None),
    "chromium": ("Chromium", "Chrome", "µg", "mineral", 275, None),
    "molybdenum": ("Molybdenum", "Molybdène", "µg", "mineral", 276, None),
    "biotin": ("Biotin (vitamin B8)", "Biotine (vitamine B8)", "µg", "vitamin", 745, None),
    "epa_dha": ("EPA + DHA", "EPA + DHA", "g", "fatty_acid", 591, "omega_3"),
}


def put_nutrients_on_label(apps, schema_editor):
    """The nutrients that exist are asked for by the form and read from OpenFoodFacts."""
    Nutrient = apps.get_model("products", "Nutrient")
    if Nutrient.objects.filter(code="vitamin_c").exists():
        for code, (name_en, name_fr, unit, group, order, parent) in CREATED.items():
            if parent is not None and not Nutrient.objects.filter(code=parent).exists():
                continue
            Nutrient.objects.get_or_create(
                code=code,
                defaults={
                    "name_en": name_en,
                    "name_fr": name_fr,
                    "unit": unit,
                    "group": group,
                    "display_order": order,
                    "parent_id": parent,
                },
            )
    for code, key in LABEL_MORE.items():
        Nutrient.objects.filter(code=code).update(on_label=True, off_key=key)


def take_nutrients_off_label(apps, schema_editor):
    Nutrient = apps.get_model("products", "Nutrient")
    ProductNutrient = apps.get_model("products", "ProductNutrient")
    # What was declared of a nutrient made here goes with it; the others keep theirs.
    ProductNutrient.objects.filter(nutrient_id__in=CREATED).delete()
    Nutrient.objects.filter(code__in=CREATED).delete()
    Nutrient.objects.filter(code__in=LABEL_MORE).update(on_label=False, off_key=None)


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0028_inventory_stock"),
    ]

    operations = [
        migrations.RunPython(put_nutrients_on_label, take_nutrients_off_label),
    ]
