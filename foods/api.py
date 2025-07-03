# aliments/api.py
from ninja import Router
from .schema import ProductSchema
from glom import glom
import requests
from ninja.errors import HttpError
from .off_utils import fetch_product_data

router = Router()

@router.get("/off/{barcode}", response=ProductSchema)
def get_product(request, barcode: str):
    try:
        return fetch_product_data(barcode)
    except Exception as e:
        raise HttpError(404, f"Erreur lors de la récupération du produit : {e}")
