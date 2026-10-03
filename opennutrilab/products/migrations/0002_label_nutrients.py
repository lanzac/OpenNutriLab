"""
The nutrients of the EU nutrition declaration (Regulation 1169/2011), which
the product form asks for. Vitamins, minerals and their CIQUAL counterparts
are added with the CIQUAL import.

CIQUAL codes: energy is the EU 1169/2011 definition (327), and protein is
nitrogen x 6.25 (25003), the rule labels follow, rather than CIQUAL's default
Jones-factor protein (25000).

OFF keys: OpenFoodFacts' `energy` is always in kJ (converted from kcal when
the label only gives kcal); its mass nutrients are in grams.
"""

from django.db import migrations

LABEL_NUTRIENTS = [
    # code, English, French, unit, group, parent, CIQUAL, OFF
    ("energy", "Energy", "Énergie", "kJ", "energy", None, "327", "energy"),
    ("fat", "Fat", "Matières grasses", "g", "macronutrient", None, "40000", "fat"),
    (
        "saturated_fat",
        "of which saturates",
        "dont acides gras saturés",
        "g",
        "macronutrient",
        "fat",
        "40302",
        "saturated-fat",
    ),
    (
        "carbohydrates",
        "Carbohydrate",
        "Glucides",
        "g",
        "macronutrient",
        None,
        "31000",
        "carbohydrates",
    ),
    (
        "sugars",
        "of which sugars",
        "dont sucres",
        "g",
        "macronutrient",
        "carbohydrates",
        "32000",
        "sugars",
    ),
    ("fiber", "Fibre", "Fibres alimentaires", "g", "macronutrient", None, "34100", "fiber"),
    ("proteins", "Protein", "Protéines", "g", "macronutrient", None, "25003", "proteins"),
    ("salt", "Salt", "Sel", "g", "other", None, "10004", "salt"),
]


def create_label_nutrients(apps, schema_editor):
    Nutrient = apps.get_model("products", "Nutrient")
    for order, (code, name_en, name_fr, unit, group, parent, ciqual, off) in enumerate(
        LABEL_NUTRIENTS
    ):
        Nutrient.objects.create(
            code=code,
            name_en=name_en,
            name_fr=name_fr,
            unit=unit,
            group=group,
            parent_id=parent,
            on_label=True,
            display_order=order,
            ciqual_code=ciqual,
            off_key=off,
        )


def delete_label_nutrients(apps, schema_editor):
    Nutrient = apps.get_model("products", "Nutrient")
    codes = [row[0] for row in LABEL_NUTRIENTS]
    # Children first: parent is a protected foreign key.
    Nutrient.objects.filter(code__in=codes, parent__isnull=False).delete()
    Nutrient.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_label_nutrients, delete_label_nutrients),
    ]
