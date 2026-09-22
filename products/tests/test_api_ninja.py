import pytest
from django.test import Client


@pytest.mark.django_db
def test_get_macronutrients_form_data():
    client = Client()
    # Query parameters using the aliases defined in MacronutrientsFormSchema
    params = {
        "macronutrients_fat": 10.5,
        "macronutrients_saturated_fat": 3.0,
        "macronutrients_carbohydrates": 50.0,
        "macronutrients_sugars": 20.0,
        "macronutrients_fiber": 5.0,
        "macronutrients_proteins": 15.0,
    }

    response = client.get("/api-ninja/products/off/macronutrients/form-data", params)

    assert response.status_code == 200  # noqa: PLR2004
    data = response.json()
    assert "macronutrients" in data
    assert data["macronutrients"]["fat"] == 10.5  # noqa: PLR2004
    assert data["macronutrients"]["saturated_fat"] == 3.0  # noqa: PLR2004
    assert data["macronutrients"]["carbohydrates"] == 50.0  # noqa: PLR2004
    assert data["macronutrients"]["sugars"] == 20.0  # noqa: PLR2004
    assert data["macronutrients"]["fiber"] == 5.0  # noqa: PLR2004
    assert data["macronutrients"]["proteins"] == 15.0  # noqa: PLR2004
