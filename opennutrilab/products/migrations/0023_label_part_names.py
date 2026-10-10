from django.db import migrations

# The label's two parts of another nutrient were seeded with the label's wording
# ("of which sugars"), which reads wrongly alone, in a gauge or a warning. They get
# the plain name; the product form writes "of which" itself (forms.label_wording).
# A name an admin has changed since is left as it is.
NAMES = {
    "saturated_fat": (
        ("of which saturates", "dont acides gras saturés"),
        ("Saturated fatty acids", "Acides gras saturés"),
    ),
    "sugars": (
        ("of which sugars", "dont sucres"),
        ("Sugars", "Sucres"),
    ),
}


def rename(apps, old: int, new: int):
    Nutrient = apps.get_model("products", "Nutrient")
    for code, names in NAMES.items():
        (old_en, old_fr), (new_en, new_fr) = names[old], names[new]
        Nutrient.objects.filter(code=code, name_en=old_en, name_fr=old_fr).update(
            name_en=new_en, name_fr=new_fr
        )


def plain_names(apps, schema_editor):
    rename(apps, 0, 1)


def label_names(apps, schema_editor):
    rename(apps, 1, 0)


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0022_fatty_acid_group"),
    ]

    operations = [
        migrations.RunPython(plain_names, label_names),
    ]
