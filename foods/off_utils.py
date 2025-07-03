import requests
from glom import glom
from .schema import ProductSchema
from .data_mapping import openfoodfacts_data_mapping as spec

def fetch_product_data(barcode: str) -> ProductSchema:
    url = f"https://world.openfoodfacts.net/api/v2/product/{barcode}.json"
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    result = glom(response.json(), spec)
    return ProductSchema(**result)
