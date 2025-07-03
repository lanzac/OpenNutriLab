from foods.schema import ProductSchema, MacronutrientsSchema

# https://static.openfoodfacts.org/data/data-fields.txt
openfoodfacts_data_mapping = {
        ProductSchema.annot.name: "product.product_name",
        ProductSchema.annot.image_url: "product.image_small_url",
        ProductSchema.annot.description: "product.categories",
        ProductSchema.annot.energy: "product.nutriments.energy_100g",
        # energy-kj_100g not in product barcode 3229820794556 !
        ProductSchema.annot.macronutrients: {
            MacronutrientsSchema.annot.fat: 'product.nutriments.fat_100g',
            MacronutrientsSchema.annot.saturated_fat: 'product.nutriments.saturated-fat_100g',
            MacronutrientsSchema.annot.carbohydrates: 'product.nutriments.carbohydrates_100g',
            MacronutrientsSchema.annot.sugars: 'product.nutriments.sugars_100g',
            MacronutrientsSchema.annot.proteins: 'product.nutriments.proteins_100g',
            MacronutrientsSchema.annot.fiber: 'product.nutriments.fiber_100g'
        }
    }