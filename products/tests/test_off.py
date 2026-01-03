# Test OpenFoodFacts related fonctionalities
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from ninja.errors import HttpError
from requests import HTTPError
from requests import RequestException

from products.base_schema import MacronutrientsSchema
from products.base_schema import ProductSchema
from products.openfoodfacts.schema import OFFProductSchema
from products.openfoodfacts.schema import ProductFormSchema
from products.openfoodfacts.schema import product_schema_to_form_data
from products.openfoodfacts.utils import fetch_local_product
from products.openfoodfacts.utils import fetch_product


@pytest.fixture
def sample_data(tmp_path: Path) -> Path:
    """Create a temporary local JSON file mimicking OFF data."""
    data = {
        "product": {
            "code": "123456",
            "product_name": "Test Product",
            "image_small_url": "https://example.com/image.jpg",
            "nutriments": {
                "fat_100g": 10.0,
                "carbohydrates_100g": 20.0,
                "proteins_100g": 5.0,
            },
        },
    }
    data_dir = tmp_path / "products" / "tests" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / "123456.json"
    with Path.open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return file_path


def test_fetch_local_product_valid_data(sample_data: Path):
    """Test reading a local JSON and transforming it into a ProductSchema."""
    base_dir = sample_data.parents[3]  # root of the tmp project structure
    product: OFFProductSchema = fetch_local_product(
        barcode="123456",
        base_dir=base_dir,
    )

    expected_product: ProductSchema[MacronutrientsSchema, Any] = ProductSchema(
        barcode="123456",
        name="Test Product",
        image_url="https://example.com/image.jpg",
        macronutrients=MacronutrientsSchema(
            fat=10.0,
            carbohydrates=20.0,
            proteins=5.0,
        ),
    )

    assert isinstance(product, OFFProductSchema)
    assert product.dict() == expected_product.dict()


def test_fetch_local_product_invalid_data(sample_data: Path):
    """Test that invalid product data raises a ValueError."""
    # We volontarily corrupt the sample data
    with Path.open(sample_data, "r+", encoding="utf-8") as f:
        data = json.load(f)

        del data["product"]["product_name"]  # mandatory field removed
        data["product"]["nutriments"]["fat_100g"] = "not_a_number"

        f.seek(0)
        json.dump(data, f)
        f.truncate()

    base_dir = sample_data.parents[3]

    with pytest.raises(ValueError, match="Invalid product data format for 123456"):
        fetch_local_product("123456", base_dir)


def test_fetch_product():
    """Test that the function builds ProductSchema from mocked HTTP response."""
    mock_json = {
        "status": "success",
        "result": {
            "id": "product_found",
            "name": "Product found",
            "lc_name": "Product found",
        },
        "product": {
            "code": "999999",
            "product_name": "Remote Product",
            "image_small_url": None,
            "nutriments": {"fat_100g": 3.0, "proteins_100g": 1.5},
        },
    }

    mock_response = MagicMock()
    mock_response.json.return_value = mock_json
    mock_response.raise_for_status.return_value = None

    with patch("products.openfoodfacts.utils.requests.get", return_value=mock_response):
        product: OFFProductSchema = fetch_product(query_barcode="999999")

    expected_product: ProductSchema[MacronutrientsSchema, Any] = ProductSchema(
        # Only fields present in mock_json set in form of expected ProductSchema
        # The rest will have their value by default
        barcode="999999",
        name="Remote Product",
        macronutrients=MacronutrientsSchema(
            fat=3.0,
            proteins=1.5,
        ),
    )

    assert isinstance(product, OFFProductSchema)
    assert product.dict() == expected_product.dict()


def test_fetch_product_http_error():
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = HTTPError("500 Server Error")

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product(query_barcode="999999")

    assert exc.value.status_code == 502  # noqa: PLR2004
    assert "External API returned an error" in exc.value.message


def test_fetch_product_request_exception():
    with (
        patch(
            "products.openfoodfacts.utils.requests.get",
            side_effect=RequestException("Connection timeout"),
        ),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 503  # noqa: PLR2004
    assert "External API unreachable" in exc.value.message


def test_fetch_product_invalid_json():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.side_effect = ValueError("Invalid JSON")

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 502  # noqa: PLR2004
    assert "Invalid JSON received" in exc.value.message


def test_fetch_product_invalid_schema():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"unexpected": "structure"}

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 500  # noqa: PLR2004
    assert "Invalid API response format" in exc.value.message


def test_fetch_product_not_found():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "code": "204504898888",
        "errors": [
            {
                "field": {"id": "code", "value": "204504898888"},
                "impact": {"id": "failure", "lc_name": "Failure", "name": "Failure"},
                "message": {"id": "product_not_found", "lc_name": "", "name": ""},
            }
        ],
        "result": {
            "id": "product_found",
            "lc_name": "Product found",
            "name": "Product found",
        },
        "status": "failure",
        "warnings": [],
    }

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 404  # noqa: PLR2004


def test_fetch_product_success_with_warnings():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "status": "success_with_warnings",
        "code": "999999",
        "product": {
            "code": "999999",
            "product_name": "Remote Product",
        },
        "errors": [],
        "warnings": [
            {
                "message": {
                    "id": "incomplete_data",
                    "name": "Incomplete data",
                },
                "field": {
                    "id": "ingredients",
                    "value": "ingredients",
                },
                "impact": {
                    "id": "info",
                    "name": "Information",
                },
            }
        ],
        "result": {
            "id": "product_found",
            "lc_name": "Product found",
            "name": "Product found",
        },
    }

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 400  # noqa: PLR2004
    assert "Incomplete data" in exc.value.message


def test_fetch_product_success_with_errors():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "status": "success_with_errors",
        "code": "999999",
        "product": {
            "code": "999999",
            "product_name": "Remote Product",
        },
        "errors": [
            {
                "message": {
                    "id": "invalid_nutriments",
                    "name": "Invalid nutriments",
                },
                "field": {
                    "id": "nutriments",
                    "value": "nutriments",
                },
                "impact": {
                    "id": "warning",
                    "name": "Warning",
                },
            }
        ],
        "warnings": [],
        "result": {
            "id": "product_found",
            "name": "Product found",
        },
    }

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 400  # noqa: PLR2004
    assert "Invalid nutriments" in exc.value.message


def test_fetch_product_success_but_product_is_none():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "status": "success",
        "product": None,
        "errors": [],
        "warnings": [],
        "result": {
            "id": "product_found",
            "name": "Product found",
        },
    }

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 500  # noqa: PLR2004
    assert "returned no product" in exc.value.message


def test_fetch_product_barcode_mismatch():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "status": "success",
        "product": {
            "code": "111111",
            "product_name": "Wrong Product",
        },
        "errors": [],
        "warnings": [],
        "result": {
            "id": "product_found",
            "name": "Product found",
        },
    }

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(ValueError, match="Barcode mismatch"),
    ):
        fetch_product("999999")


def test_product_schema_to_form_data():
    """Test conversion from ProductSchema to ProductFormSchema."""
    product: ProductSchema[MacronutrientsSchema, Any] = ProductSchema(
        barcode="123456",
        name="Test Product",
        image_url="https://example.com/image.jpg",
        macronutrients=MacronutrientsSchema(
            fat=10.0,
            carbohydrates=20.0,
            proteins=5.0,
        ),
    )
    form_data: ProductFormSchema = product_schema_to_form_data(product)

    assert isinstance(form_data, ProductFormSchema)
    assert form_data.barcode == "123456"
    assert form_data.name == "Test Product"
    assert form_data.image_url == "https://example.com/image.jpg"
    assert form_data.macronutrients_fat == 10.0  # noqa: PLR2004
    assert form_data.macronutrients_carbohydrates == 20.0  # noqa: PLR2004
    assert form_data.macronutrients_proteins == 5.0  # noqa: PLR2004
