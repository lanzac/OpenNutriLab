from django.db import migrations, models


def set_macronutrient_labels(apps, schema_editor):
    Macronutrient = apps.get_model("products", "Macronutrient")

    entries = [
        ("fat", "Fat"),
        ("saturated_fat", "of which Saturates"),
        ("carbohydrates", "Carbohydrates"),
        ("sugars", "of which Sugars"),
        ("fiber", "Fiber"),
        ("proteins", "Proteins"),
    ]

    for order_index, (name, label) in enumerate(entries):
        Macronutrient.objects.filter(name=name).update(label=label, order_index=order_index)


def unset_macronutrient_labels(apps, schema_editor):
    Macronutrient = apps.get_model("products", "Macronutrient")
    names = ["fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins"]
    Macronutrient.objects.filter(name__in=names).update(label="", order_index=0)


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0005_alter_macronutrient_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="macronutrient",
            name="order_index",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(set_macronutrient_labels, unset_macronutrient_labels),
    ]
