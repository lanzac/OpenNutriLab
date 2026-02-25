from typing import Any
from typing import cast
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.test import Client
from pint import Quantity
from pydantic import BaseModel
from pydantic import ValidationError
from quantityfield.units import ureg

from products.api.types import DEFAULT_UNIT
from products.api.types import QuantityType


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
        "products.api.openfoodfacts.api_ninja_fetch_product.requests.get",
        return_value=mock_response,
    ):
        client = Client()
        response = client.get("/api-ninja/products/off/fetch-product/1234567890")

    assert response.status_code == 200  # noqa: PLR2004
    assert response.json()["product"]["name"] == "Test Product"


@pytest.mark.django_db
def test_get_product_off_api_error():
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.json.return_value = {"detail": "server error"}

    with patch(
        "products.api.openfoodfacts.api_ninja_fetch_product.requests.get",
        return_value=mock_response,
    ):
        client = Client()
        response = client.get("/api-ninja/products/off/fetch-product/1234567890")

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


class ModelWithQuantity(BaseModel):
    q: QuantityType


@pytest.mark.parametrize(
    ("input_value", "expected_value", "expected_unit"),
    [
        (None, None, None),
        ({"value": 3.14159, "unit": "m"}, 3.14, "meter"),
        # pint-like object (has .magnitude and .units)
        (ureg.Quantity(2.71828, ureg.kg), 2.72, "kilogram"),
        # float -> converted using DEFAULT_UNIT
        (1.9876, 1.99, DEFAULT_UNIT),
        # string convertible
        ("4.567", 4.57, DEFAULT_UNIT),
    ],
)
def test_quantitytype_validation_success(
    input_value: Any, expected_value: Any, expected_unit: Any
):
    """
    Validate that QuantityType accepts various input shapes and returns a pint.Quantity
    (or None) with expected rounded magnitude and unit.
    """
    if input_value is None:
        m = ModelWithQuantity.model_validate({"q": None})
        assert m.q is None
        # also check model dump serializes to None
        assert ModelWithQuantity.model_validate({"q": None}).model_dump()["q"] is None
        return

    m = ModelWithQuantity.model_validate({"q": input_value})
    # result must be a pint.Quantity-like
    assert m.q is not None

    assert isinstance(m.q, Quantity)
    # check rounding (compare rounded values to avoid floating noise)
    assert round(float(m.q.magnitude), 2) == expected_value
    assert m.q.units == ureg(expected_unit).units

    # also check serialization (model_dump) returns dict {"value": ..., "unit": ...}
    dumped = ModelWithQuantity.model_validate({"q": input_value}).model_dump()
    assert isinstance(dumped, dict)
    assert isinstance(dumped["q"], dict)
    value = cast("float", dumped["q"]["value"])
    unit = cast("str", dumped["q"]["unit"])
    assert round(value, 2) == expected_value
    assert unit == format(ureg.parse_units(expected_unit), "~P")


@pytest.mark.parametrize("bad_input", ["not_a_number", object()])
def test_quantitytype_validation_error(bad_input: Any):
    """Non-convertible inputs should raise a Pydantic ValidationError."""
    with pytest.raises(ValidationError):
        ModelWithQuantity.model_validate({"q": bad_input})
