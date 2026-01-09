import requests
from django.http import HttpRequest
from django.http import HttpResponse
from ninja import Query
from ninja import Router

from products.openfoodfacts.api_response_shema import OFFAPIErrorSchema
from products.openfoodfacts.api_response_shema import OFFProductAPIResponseSchema
from products.openfoodfacts.schema import MacronutrientsFormSchema

router = Router()


@router.get(
    path="/off/{barcode}",
    response={
        200: OFFProductAPIResponseSchema,
        502: OFFAPIErrorSchema,
    },
)
def get_product(request: HttpRequest, response: HttpResponse, barcode: str):
    r = requests.get(
        f"https://world.openfoodfacts.org/api/v3/product/{barcode}.json",
        timeout=10,
    )

    if r.status_code == 500:  # noqa: PLR2004
        response.status_code = 502
        return 502, {"error": "OFF API unavailable"}

    # Return the JSON response from the OFF API with HTTP 200 (success) status.
    # Django Ninja will automatically validate it against OFFProductAPIResponseSchema.
    return r.json()


@router.get(path="macronutrients/form-data")
def get_macronutrients_form_data(
    request: HttpRequest, macronutrients: Query[MacronutrientsFormSchema]
):
    """Return parsed macronutrient data from form input."""
    return {"macronutrients": macronutrients.dict()}
