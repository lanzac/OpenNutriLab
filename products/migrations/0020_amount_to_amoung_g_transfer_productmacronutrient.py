from django.db import migrations

def transfer_amount_to_amount_g(apps, schema_editor):
    ProductMacronutrient = apps.get_model("products", "ProductMacronutrient")
    for product_macronutrient in ProductMacronutrient.objects.all():
        if product_macronutrient.amount:  # QuantityField returns Pint Quantity or None
            product_macronutrient.amount_g = float(product_macronutrient.amount.to("g").magnitude)
            product_macronutrient.save(update_fields=["amount_g"])

class Migration(migrations.Migration):

    dependencies = [
        ('products', '0019_energy_to_energy_g_transfer'),
    ]

    operations = [
        migrations.RunPython(transfer_amount_to_amount_g),
    ]
