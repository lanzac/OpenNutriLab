from django.db import migrations
from django.db import models

# The nutrients that are fatty acids, or totals of them, and the plainer names
# the CIQUAL import gives them (see services.ciqual_constituents.NAMES). Copied
# here so that this migration does not change when that module does. `fat` stays
# a macronutrient, with the proteins and the carbohydrates it is counted with.
FATTY_ACIDS = [
    "saturated_fat",
    "monounsaturated_fat",
    "polyunsaturated_fat",
    "butyric_acid",
    "caproic_acid",
    "caprylic_acid",
    "capric_acid",
    "lauric_acid",
    "myristic_acid",
    "palmitic_acid",
    "stearic_acid",
    "oleic_acid",
    "linoleic_acid",
    "alpha_linolenic_acid",
    "arachidonic_acid",
    "epa",
    "dha",
    "omega_3",
    "omega_6",
]

# Code -> (English, French). The omega totals keep the names they were made with,
# and `saturated_fat` is renamed by the next migration, with the label's other part.
NAMES = {
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


def move_fatty_acids(apps, schema_editor):
    """The fatty acids that exist go to their group, under their plainer names."""
    Nutrient = apps.get_model("products", "Nutrient")
    Nutrient.objects.filter(code__in=FATTY_ACIDS).update(group="fatty_acid")
    for code, (name_en, name_fr) in NAMES.items():
        Nutrient.objects.filter(code=code).update(name_en=name_en, name_fr=name_fr)


def back_to_macronutrients(apps, schema_editor):
    """The names stay the plainer ones: the CIQUAL ones are not kept anywhere."""
    Nutrient = apps.get_model("products", "Nutrient")
    Nutrient.objects.filter(group="fatty_acid").update(group="macronutrient")


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0021_ingredient_nutrient"),
    ]

    operations = [
        migrations.AlterField(
            model_name="nutrient",
            name="group",
            field=models.CharField(
                choices=[
                    ("energy", "Energy"),
                    ("macronutrient", "Macronutrient"),
                    ("fatty_acid", "Fatty acid"),
                    ("mineral", "Mineral"),
                    ("vitamin", "Vitamin"),
                    ("other", "Other"),
                ],
                max_length=20,
            ),
        ),
        migrations.RunPython(move_fatty_acids, back_to_macronutrients),
    ]
