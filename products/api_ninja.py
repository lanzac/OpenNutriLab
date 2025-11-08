import requests
from django.http import HttpRequest
from ninja import Query
from ninja import Router
from ninja.errors import HttpError

from products.schema import MacronutrientsFormSchema
from products.schema import ProductSchema

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


@router.get(path="macronutrients/form-data")
def get_macronutrients_form_data(
    request: HttpRequest, macronutrients: Query[MacronutrientsFormSchema]
):
    """Return parsed macronutrient data from form input."""
    return {"macronutrients": macronutrients.dict()}
