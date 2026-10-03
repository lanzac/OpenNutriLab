from django.db import migrations

def add_macronutrients(apps, schema_editor):
    Macronutrient = apps.get_model("products", "Macronutrient")

    entries = [
        "fat",
        "saturated_fat",
        "carbohydrates",
        "sugars",
        "fiber",
        "proteins",
    ]

    for name in entries:
        Macronutrient.objects.get_or_create(name=name)


def remove_macronutrients(apps, schema_editor):
    Macronutrient = apps.get_model("products", "Macronutrient")

    names = [
        "fat",
        "saturated_fat",
        "carbohydrates",
        "sugars",
        "fiber",
        "proteins",
    ]
    Macronutrient.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_macronutrients, remove_macronutrients),
    ]
