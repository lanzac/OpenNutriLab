from django.db import migrations

# The vitamins a label declares, with their OpenFoodFacts key (see
# services.label_vitamins). Copied here so that this migration does not change
# when that module does. A catalogue that has none of them yet is left as it is:
# the CIQUAL import creates them on the label.
LABEL_VITAMINS = {
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


def put_vitamins_on_label(apps, schema_editor):
    """The vitamins that exist are asked for by the form and read from OpenFoodFacts."""
    Nutrient = apps.get_model("products", "Nutrient")
    for code, key in LABEL_VITAMINS.items():
        Nutrient.objects.filter(code=code).update(on_label=True, off_key=key)


def take_vitamins_off_label(apps, schema_editor):
    Nutrient = apps.get_model("products", "Nutrient")
    Nutrient.objects.filter(code__in=LABEL_VITAMINS).update(
        on_label=False, off_key=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0026_kept_estimate_density"),
    ]

    operations = [
        migrations.RunPython(put_vitamins_on_label, take_vitamins_off_label),
    ]
