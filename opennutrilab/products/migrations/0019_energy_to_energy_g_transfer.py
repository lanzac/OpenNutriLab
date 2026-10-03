from django.db import migrations

def transfer_energy_to_energy_kj(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    for product in Product.objects.all():
        if product.energy:  # QuantityField returns Pint Quantity or None
            product.energy_kj = int(product.energy.to("kJ").magnitude)
            product.save(update_fields=["energy_kj"])

class Migration(migrations.Migration):

    dependencies = [
        ('products', '0018_ingredientrefmacronutrient_amount_g_and_more'),
    ]

    operations = [
        migrations.RunPython(transfer_energy_to_energy_kj),
    ]
