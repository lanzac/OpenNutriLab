# aliments/api.py
import requests
from ninja import Router
from ninja.errors import HttpError

from foods.schema import ProductSchema

from .off_utils import fetch_product_data

router = Router()


@router.get(path="/off/{barcode}", response=ProductSchema)
def get_product(barcode: str) -> ProductSchema:
    try:
        return fetch_product_data(barcode)
    except (requests.RequestException, ValueError, KeyError) as e:
        raise HttpError(
            status_code=404, message=f"Error when fetching the product data: {e}"
        ) from e
