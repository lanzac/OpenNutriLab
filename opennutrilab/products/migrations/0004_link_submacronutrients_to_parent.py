from django.db import migrations, models


def add_macronutrients(apps, schema_editor):
    Macronutrient = apps.get_model("products", "Macronutrient")

    # Définition des macronutriments dans l’ordre souhaité
    entries = [
        ("fat", None),
        ("saturated_fat", "fat"),
        ("carbohydrates", None),
        ("sugars", "carbohydrates"),
        ("fiber", None),
        ("proteins", None),
    ]

    for order_index, (name, parent_name) in enumerate(entries):
        parent = None
        if parent_name:
            parent = Macronutrient.objects.filter(name=parent_name).first()
        Macronutrient.objects.update_or_create(
            name=name,
            defaults={"parent": parent, "order_index": order_index},
        )


def remove_macronutrients(apps, schema_editor):
    Macronutrient = apps.get_model("products", "Macronutrient")
    names = ["fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins"]
    Macronutrient.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0003_alter_macronutrient_options_macronutrient_parent"),
    ]

    operations = [
        migrations.AddField(
            model_name="macronutrient",
            name="order_index",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(add_macronutrients, remove_macronutrients),
    ]
