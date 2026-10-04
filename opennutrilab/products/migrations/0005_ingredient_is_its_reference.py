from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0004_reference_names_and_status'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='ingredient',
            name='unique_ingredient_per_product_parent',
        ),
        migrations.RemoveConstraint(
            model_name='ingredient',
            name='unique_root_ingredient_per_product',
        ),
        migrations.RemoveField(
            model_name='ingredient',
            name='name',
        ),
        migrations.RemoveField(
            model_name='ingredient',
            name='off_id',
        ),
        migrations.RemoveField(
            model_name='ingredient',
            name='off_ciqual_food_code',
        ),
        migrations.RemoveField(
            model_name='ingredient',
            name='off_ciqual_proxy_food_code',
        ),
        migrations.AlterField(
            model_name='ingredient',
            name='reference',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='usages', to='products.referenceingredient'),
        ),
        migrations.AddConstraint(
            model_name='ingredient',
            constraint=models.UniqueConstraint(fields=('product', 'parent', 'reference'), name='unique_ingredient_per_product_parent'),
        ),
        migrations.AddConstraint(
            model_name='ingredient',
            constraint=models.UniqueConstraint(condition=models.Q(('parent__isnull', True)), fields=('product', 'reference'), name='unique_root_ingredient_per_product'),
        ),
    ]
