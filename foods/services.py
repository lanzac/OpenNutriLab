from .models import Food, Macronutrient, FoodMacronutrient
from mapping.schema import Product


def save_product(product: Product):
    food, _ = Food.objects.update_or_create(
        barcode=product.barcode,
        defaults={
            'name': product.name,
            'description': product.description,
            'image': product.image_url,
            'energy': product.energy,
        }
    )

    for macro_name, amount in product.macronutrients.model_dump().items():
        if amount is None:
            continue

        orm_name = MACRONUTRIENT_NAME_MAP[macro_name]
        macronutrient_obj = Macronutrient.objects.get(name=orm_name)

        FoodMacronutrient.objects.update_or_create(
            food=food,
            macronutrient=macronutrient_obj,
            defaults={'amount': amount}
        )

    return food
