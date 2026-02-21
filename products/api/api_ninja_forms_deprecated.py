from django.http import HttpRequest
from ninja import Query
from ninja import Router

from products.api.openfoodfacts.schemas import MacronutrientsFormSchema

router = Router(tags=["OpenFoodFacts"])


@router.get(path="macronutrients/form-data")
def get_macronutrients_form_data(
    request: HttpRequest, macronutrients: Query[MacronutrientsFormSchema]
):
    """Return parsed macronutrient data from form input."""
    return {"macronutrients": macronutrients.dict()}
