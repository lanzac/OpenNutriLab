from glom import Coalesce

# https://static.openfoodfacts.org/data/data-fields.txt
openfoodfacts_data_mapping = {
    "name": "product.product_name",
    "image_url": Coalesce("product.image_small_url", default=None),
    "description": Coalesce("product.categories", default=None),
    "energy": Coalesce("product.nutriments.energy_100g", default=None),
    # energy-kj_100g not in product barcode 3229820794556 !
    "macronutrients": {
        "fat": Coalesce("product.nutriments.fat_100g", default=None),
        "saturated_fat": Coalesce(
            "product.nutriments.saturated-fat_100g",
            default=None,
        ),
        "carbohydrates": Coalesce(
            "product.nutriments.carbohydrates_100g",
            default=None,
        ),
        "sugars": Coalesce("product.nutriments.sugars_100g", default=None),
        "proteins": Coalesce("product.nutriments.proteins_100g", default=None),
        "fiber": Coalesce("product.nutriments.fiber_100g", default=None),
    },
}
