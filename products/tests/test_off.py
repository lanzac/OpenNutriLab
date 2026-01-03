# Test OpenFoodFacts related fonctionalities
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

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


def test_fetch_local_product_data(sample_data: Path):
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


def test_fetch_product_data():
    """Test that the function builds ProductSchema from mocked HTTP response."""
    mock_json = {
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
