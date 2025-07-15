import os
import json
import requests
from glom import glom
from .schema import ProductSchema
from .data_mapping import openfoodfacts_data_mapping as spec
from django.conf import settings

def fetch_product_data(barcode: str, use_local: bool = False) -> ProductSchema:
    if use_local:
        local_path = os.path.join(settings.BASE_DIR, "foods", "tests", "data", f"{barcode}.json")
        with open(local_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        url = f"https://world.openfoodfacts.net/api/v2/product/{barcode}.json"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
    result = glom(data, spec)
    result['barcode'] = barcode  # Ajout du code-barres au résultat
    return ProductSchema(**result)
