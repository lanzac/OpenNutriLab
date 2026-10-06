"""
Load the table of additives from its dataset (products/data/additives.json), the
additives of the European Commission with their English and French names, so that it
is there without a command. The additives that an earlier way of filling the table
made from OpenFoodFacts' list are deleted when nothing has touched them, and loaded
again from the dataset; what the table has otherwise is completed and never
overwritten (see services.additive_sync).
"""

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def load_additives(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    # Imported here: the migration loads with the apps, and runs with the historical
    # model, which is all the service asks for.
    from opennutrilab.products.services.additive_sync import clear_untouched
    from opennutrilab.products.services.additive_sync import read_dataset
    from opennutrilab.products.services.additive_sync import sync_additives

    additive = apps.get_model("products", "Additive")
    _dataset, entries = read_dataset()
    # What an earlier way of filling the table made goes first, and is loaded again.
    clear_untouched(model=additive)
    sync_additives(entries, model=additive)


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0012_additive"),
    ]

    operations = [
        # Nothing to undo: the additives are data, and some may have been curated.
        migrations.RunPython(load_additives, migrations.RunPython.noop),
    ]
