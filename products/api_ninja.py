from django.http import HttpRequest
from django.http import HttpResponse
from ninja import Query
from ninja import Router

from products.openfoodfacts.schema import MacronutrientsFormSchema
from products.openfoodfacts.schema import OFFProductSchema

from .openfoodfacts.utils import fetch_product

router = Router()


@router.get(path="/off/{barcode}")
def get_product(
    request: HttpRequest, response: HttpResponse, barcode: str
) -> OFFProductSchema:
    return fetch_product(barcode)


@router.get(path="macronutrients/form-data")
def get_macronutrients_form_data(
    request: HttpRequest, macronutrients: Query[MacronutrientsFormSchema]
):
    """Return parsed macronutrient data from form input."""
    return {"macronutrients": macronutrients.dict()}
