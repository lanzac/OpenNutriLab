import requests
from django.http import HttpRequest
from django.http import HttpResponse
from ninja import Router

from .schemas import OFFAPIErrorSchema
from .schemas import OFFProductAPIResponseSchema

router = Router(tags=["OpenFoodFacts"])


@router.get(
    path="/fetch-product/{barcode}",
    response={
        200: OFFProductAPIResponseSchema,
        502: OFFAPIErrorSchema,
    },
)
def fetch_product(request: HttpRequest, response: HttpResponse, barcode: str):
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
