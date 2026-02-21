from django.db import transaction
from django.shortcuts import get_object_or_404

from products.api.schemas.inbound import ProductCreate
from products.api.schemas.inbound import ProductUpdate
from products.models import Macronutrient
from products.models import Product
from products.models import ProductMacronutrient


def create_product(data: ProductCreate) -> Product:
    # 1. On crée le produit avec les champs "plats"
    # Note : on va chercher 'energy' à l'intérieur de nutritional_values
    product = Product.objects.create(
        barcode=data.barcode,
        name=data.name,
        description=data.description,
        group_level_1=data.group_level_1,
        group_level_2=data.group_level_2,
        energy=data.nutritional_values.energy,  # <-- Extraction ici !
    )

    # 2. On traite la liste des macronutriments (Table de liaison)
    for item in data.nutritional_values.macronutrients:
        # On récupère l'objet Macronutrient (Glucides, Lipides, etc.)
        macro_obj = Macronutrient.objects.get(name=item.name)

        # On crée la ligne dans la table intermédiaire
        ProductMacronutrient.objects.create(
            product=product, macronutrient=macro_obj, amount=item.amount
        )

    return product


def update_product(barcode: str, data: ProductUpdate) -> Product:
    product: Product = get_object_or_404(Product, barcode=barcode)

    # Utilisation d'une transaction pour être sûr que tout passe ou rien
    with transaction.atomic():
        # 1. Mise à jour des champs simples du produit
        # On exclut 'nutritional_values' car c'est un objet imbriqué
        update_data = data.dict(exclude_unset=True, exclude={"nutritional_values"})
        for attr, value in update_data.items():
            setattr(product, attr, value)

        # 2. Gestion de l'énergie (si présente dans le payload)
        if data.nutritional_values and data.nutritional_values.energy is not None:
            product.energy = data.nutritional_values.energy

        product.save()

        # 3. Mise à jour des macronutriments (si présents dans le payload)
        if (
            data.nutritional_values
            and data.nutritional_values.macronutrients is not None
        ):
            # Approche radicale mais fiable : on vide et on recrée
            product.productmacronutrient_set.all().delete()

            for item in data.nutritional_values.macronutrients:
                macro_def = Macronutrient.objects.get(name=item.name)
                ProductMacronutrient.objects.create(
                    product=product, macronutrient=macro_def, amount=item.amount
                )

    return product
