from django.db import migrations


def set_name_in_form(apps, schema_editor):
    Macronutrient = apps.get_model("products", "Macronutrient")

    for entry in Macronutrient.objects.all():
        entry.name_in_form = f"macronutrients_{entry.name}"
        entry.save(update_fields=["name_in_form"])


def reverse_func(apps, schema_editor):
    Macronutrient = apps.get_model("products", "Macronutrient")

    # Optionnel : on vide le champ pour revenir à l’état précédent
    Macronutrient.objects.update(name_in_form="")


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0008_macronutrient_name_in_form"),
    ]

    operations = [
        migrations.RunPython(set_name_in_form, reverse_func),
    ]
