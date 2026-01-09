from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.test import Client


@pytest.mark.django_db
def test_get_product_success():
    mock_json = {
        "status": "success",
        "result": {
            "id": "product_found",
            "name": "Product found",
            "lc_name": "Product found",
        },
        "product": {
            "code": "1234567890",
            "product_name": "Test Product",
        },
    }

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_json

    with patch(
        "products.api_ninja.requests.get",
        return_value=mock_response,
    ):
        client = Client()
        response = client.get("/api-ninja/products/off/1234567890")

    assert response.status_code == 200  # noqa: PLR2004
    assert response.json()["product"]["name"] == "Test Product"


@pytest.mark.django_db
def test_get_product_off_api_error():
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.json.return_value = {"detail": "server error"}

    with patch(
        "products.api_ninja.requests.get",
        return_value=mock_response,
    ):
        client = Client()
        response = client.get("/api-ninja/products/off/1234567890")

    assert response.status_code == 502  # noqa: PLR2004
    assert response.json() == {"error": "OFF API unavailable"}


@pytest.mark.django_db
def test_get_macronutrients_form_data():
    client = Client()
    # Query parameters using the aliases defined in MacronutrientsFormSchema
    params = {
        "macronutrients_fat_0": 10.5,
        "macronutrients_saturated_fat_0": 3.0,
        "macronutrients_carbohydrates_0": 50.0,
        "macronutrients_sugars_0": 20.0,
        "macronutrients_fiber_0": 5.0,
        "macronutrients_proteins_0": 15.0,
    }

    response = client.get("/api-ninja/products/macronutrients/form-data", params)

    assert response.status_code == 200  # noqa: PLR2004
    data = response.json()
    assert "macronutrients" in data
    assert data["macronutrients"]["fat"] == 10.5  # noqa: PLR2004
    assert data["macronutrients"]["saturated_fat"] == 3.0  # noqa: PLR2004
    assert data["macronutrients"]["carbohydrates"] == 50.0  # noqa: PLR2004
    assert data["macronutrients"]["sugars"] == 20.0  # noqa: PLR2004
    assert data["macronutrients"]["fiber"] == 5.0  # noqa: PLR2004
    assert data["macronutrients"]["proteins"] == 15.0  # noqa: PLR2004
