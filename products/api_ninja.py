from typing import TYPE_CHECKING

import requests
from django.http import HttpRequest
from django.http import HttpResponse
from ninja import Query
from ninja import Router

from products.openfoodfacts.api_response_shema import OFFProductAPIResponseSchema
from products.openfoodfacts.schema import MacronutrientsFormSchema

if TYPE_CHECKING:
    from requests.models import Response

router = Router()


@router.get(path="/off/{barcode}", response=OFFProductAPIResponseSchema)
def get_product(request: HttpRequest, response: HttpResponse, barcode: str):
    r: Response = requests.get(
        url=f"https://world.openfoodfacts.org/api/v3/product/{barcode}.json", timeout=10
    )
    return r.json()


@router.get(path="macronutrients/form-data")
def get_macronutrients_form_data(
    request: HttpRequest, macronutrients: Query[MacronutrientsFormSchema]
):
    """Return parsed macronutrient data from form input."""
    return {"macronutrients": macronutrients.dict()}
