from django.db import migrations, models
import django.db.models.functions.text


def _key(name):
    return ' '.join(name.split()).lower()


def link_ingredients_to_references(apps, schema_editor):
    """
    Give every ingredient the reference ingredient that has its name.

    The next migration drops Ingredient.name, so each ingredient must have its
    reference by then. A name no reference has creates one, to review, with the
    French name the taxonomy gives for the ingredient's OFF id. An ingredient
    that already had a reference keeps it. Two ingredients of one parent that
    end up on the same reference cannot both stay: the first is kept.
    """
    Ingredient = apps.get_model('products', 'Ingredient')
    Reference = apps.get_model('products', 'ReferenceIngredient')
    Taxon = apps.get_model('products', 'IngredientTaxon')

    taken = {}
    for reference in Reference.objects.all():
        for name in (reference.name_en, reference.name_fr):
            if _key(name):
                taken[_key(name)] = reference.pk

    for ingredient in Ingredient.objects.filter(reference=None).order_by('id'):
        name = ' '.join(ingredient.name.split())
        reference_id = taken.get(_key(name))
        if reference_id is None:
            name_fr = ''
            if ingredient.off_id:
                taxon = Taxon.objects.filter(off_id=ingredient.off_id).first()
                name_fr = ' '.join(taxon.name_fr.split()) if taxon else ''
            if _key(name_fr) in taken:
                name_fr = ''
            reference = Reference.objects.create(
                name_en=name,
                name_fr=name_fr,
                description='Created from an existing ingredient.',
                status='to_review',
            )
            reference_id = reference.pk
            for new_name in (name, name_fr):
                if _key(new_name):
                    taken[_key(new_name)] = reference_id
        ingredient.reference_id = reference_id
        ingredient.save(update_fields=['reference'])

    seen = set()
    duplicates = []
    for ingredient in Ingredient.objects.order_by('id'):
        place = (ingredient.product_id, ingredient.parent_id, ingredient.reference_id)
        if place in seen:
            duplicates.append(ingredient.pk)
        seen.add(place)
    Ingredient.objects.filter(pk__in=duplicates).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0003_ingredient_taxon'),
    ]

    operations = [
        migrations.AlterField(
            model_name='referenceingredient',
            name='name_fr',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='referenceingredient',
            name='description',
            field=models.TextField(blank=True, help_text='Notes for whoever curates it, such as what it was created from.'),
        ),
        migrations.AddField(
            model_name='referenceingredient',
            name='status',
            field=models.CharField(choices=[('to_review', 'To review'), ('curated', 'Curated')], default='to_review', max_length=10),
        ),
        migrations.AddConstraint(
            model_name='referenceingredient',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('name_en'), condition=models.Q(('name_en', ''), _negated=True), name='unique_reference_name_en'),
        ),
        migrations.AddConstraint(
            model_name='referenceingredient',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('name_fr'), condition=models.Q(('name_fr', ''), _negated=True), name='unique_reference_name_fr'),
        ),
        migrations.AddConstraint(
            model_name='referenceingredient',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('name_en', ''), _negated=True), models.Q(('name_fr', ''), _negated=True), _connector='OR'), name='reference_has_a_name'),
        ),
        migrations.RunPython(link_ingredients_to_references, migrations.RunPython.noop),
    ]
