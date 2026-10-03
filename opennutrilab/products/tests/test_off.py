# Test OpenFoodFacts related functionalities
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from requests import RequestException

from opennutrilab.products.api.openfoodfacts.schemas import OFFIngredientSchema
from opennutrilab.products.api.openfoodfacts.schemas import OFFMacronutrientsSchema
from opennutrilab.products.api.openfoodfacts.schemas import OFFProductSchema
from opennutrilab.products.api.openfoodfacts.schemas import ProductFormSchema
from opennutrilab.products.api.openfoodfacts.schemas import product_schema_to_form_data
from opennutrilab.products.api.openfoodfacts.services import OFFError
from opennutrilab.products.api.openfoodfacts.services import OFFProductNotFoundError
from opennutrilab.products.api.openfoodfacts.services import fetch_from_off
from opennutrilab.products.api.openfoodfacts.services import to_ingredient_inputs

# A product recorded from OpenFoodFacts (API v2: the envelope differs from
# the v3 one fetch_from_off reads, but the "product" object has the same shape).
RECORDED_PRODUCT = Path(__file__).parent / "data" / "3229820794556.json"


def test_product_schema_parses_a_recorded_off_product():
    """OFFProductSchema maps a real OpenFoodFacts payload, not a hand-made one."""
    with RECORDED_PRODUCT.open(encoding="utf-8") as f:
        payload: dict[str, Any] = json.load(f)["product"]

    product = OFFProductSchema.model_validate(payload)

    assert product.barcode == "3229820794556"
    assert product.name == "Muesli Protéines"
    assert product.energy_kj == 1598  # noqa: PLR2004
    assert product.macronutrients is not None
    assert product.macronutrients.fat == 12  # noqa: PLR2004
    assert product.group_level_1 == "Cereals and potatoes"
    assert product.ingredients is not None
    assert len(product.ingredients) == 7  # noqa: PLR2004


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
    mock_response.status_code = 200

    with patch(
        "opennutrilab.products.api.openfoodfacts.services.requests.get",
        return_value=mock_response,
    ):
        product: OFFProductSchema = fetch_from_off(query_barcode="999999")

    expected_product = OFFProductSchema(
        # Only fields present in mock_json set in form of expected ProductSchema
        # The rest will have their value by default
        barcode="999999",
        name="Remote Product",
        macronutrients=OFFMacronutrientsSchema(
            fat=3.0,
            proteins=1.5,
        ),
    )

    assert isinstance(product, OFFProductSchema)
    assert product.dict() == expected_product.dict()


def test_fetch_product_http_error():
    """An upstream status other than 200/404 is a gateway failure."""
    mock_response = MagicMock()
    mock_response.status_code = 500

    with (
        patch(
            "opennutrilab.products.api.openfoodfacts.services.requests.get",
            return_value=mock_response,
        ),
        pytest.raises(OFFError) as exc,
    ):
        fetch_from_off(query_barcode="999999")

    # An outage, not an unknown barcode.
    assert type(exc.value) is OFFError

    assert "External API returned an error" in str(exc.value)


def test_fetch_product_request_exception():
    with (
        patch(
            "opennutrilab.products.api.openfoodfacts.services.requests.get",
            side_effect=RequestException("Connection timeout"),
        ),
        pytest.raises(OFFError) as exc,
    ):
        fetch_from_off("999999")

    # An outage, not an unknown barcode.
    assert type(exc.value) is OFFError

    assert "External API unreachable" in str(exc.value)


def test_fetch_product_invalid_json():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("Invalid JSON")

    with (
        patch(
            "opennutrilab.products.api.openfoodfacts.services.requests.get",
            return_value=mock_response,
        ),
        pytest.raises(OFFError) as exc,
    ):
        fetch_from_off("999999")

    # An outage, not an unknown barcode.
    assert type(exc.value) is OFFError

    assert "Invalid JSON received" in str(exc.value)


def test_fetch_product_invalid_schema():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"unexpected": "structure"}

    with (
        patch(
            "opennutrilab.products.api.openfoodfacts.services.requests.get",
            return_value=mock_response,
        ),
        pytest.raises(OFFError) as exc,
    ):
        fetch_from_off("999999")

    # An outage, not an unknown barcode.
    assert type(exc.value) is OFFError

    assert "Invalid API response format" in str(exc.value)


def test_fetch_product_not_found():
    """
    OFF reports an unknown barcode as HTTP 404 carrying a `status: failure`
    body. Reading the status line alone turned that into a 502, and the
    product form 500'd instead of inviting the user to fill it in by hand.
    """
    mock_response = MagicMock()
    mock_response.status_code = 404
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
        patch(
            "opennutrilab.products.api.openfoodfacts.services.requests.get",
            return_value=mock_response,
        ),
        pytest.raises(OFFProductNotFoundError),
    ):
        fetch_from_off("999999")


def test_fetch_product_success_with_warnings():
    """
    Warnings are informational: OFF attaches one to every short barcode it
    pads. Rejecting them made every UPC-A lookup fail even when the product
    was found.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
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

    with patch(
        "opennutrilab.products.api.openfoodfacts.services.requests.get",
        return_value=mock_response,
    ):
        product: OFFProductSchema = fetch_from_off("999999")

    assert product.barcode == "999999"
    assert product.name == "Remote Product"


def test_fetch_product_success_with_errors():
    mock_response = MagicMock()
    mock_response.status_code = 200
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
        patch(
            "opennutrilab.products.api.openfoodfacts.services.requests.get",
            return_value=mock_response,
        ),
        pytest.raises(OFFError) as exc,
    ):
        fetch_from_off("999999")

    # An outage, not an unknown barcode.
    assert type(exc.value) is OFFError

    assert "Invalid nutriments" in str(exc.value)


def test_fetch_product_success_but_product_is_none():
    mock_response = MagicMock()
    mock_response.status_code = 200
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
        patch(
            "opennutrilab.products.api.openfoodfacts.services.requests.get",
            return_value=mock_response,
        ),
        pytest.raises(OFFError) as exc,
    ):
        fetch_from_off("999999")

    # An outage, not an unknown barcode.
    assert type(exc.value) is OFFError

    assert "returned no product" in str(exc.value)


def test_fetch_product_accepts_normalized_upca_barcode():
    """
    OFF stores codes as 13-digit EAN, so a 12-digit UPC-A comes back with a
    leading zero and a `different_normalized_product_code` warning. The
    requested and returned spellings must still be treated as the same code.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success_with_warnings",
        "code": "0013764027053",
        "product": {
            "code": "0013764027053",
            "product_name": "Remote Product",
        },
        "errors": [],
        "warnings": [
            {
                "message": {
                    "id": "different_normalized_product_code",
                    "name": "Different normalized product code",
                },
                "field": {"id": "code", "value": "0013764027053"},
                "impact": {"id": "none", "name": "None"},
            }
        ],
        "result": {"id": "product_found", "name": "Product found"},
    }

    with patch(
        "opennutrilab.products.api.openfoodfacts.services.requests.get",
        return_value=mock_response,
    ):
        product: OFFProductSchema = fetch_from_off("13764027053")

    assert product.barcode == "0013764027053"


def test_fetch_product_rounds_fractional_energy():
    """
    OFF sends `energy_100g` as a float while Product.energy_kj is an
    IntegerField, so an unrounded value failed schema validation with a 500.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "product": {
            "code": "999999",
            "product_name": "Remote Product",
            "nutriments": {"energy_100g": 1443.5},
        },
        "errors": [],
        "warnings": [],
        "result": {"id": "product_found", "name": "Product found"},
    }

    with patch(
        "opennutrilab.products.api.openfoodfacts.services.requests.get",
        return_value=mock_response,
    ):
        product: OFFProductSchema = fetch_from_off("999999")

    assert product.energy_kj == 1444  # noqa: PLR2004


def test_fetch_product_barcode_mismatch():
    mock_response = MagicMock()
    mock_response.status_code = 200
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
        patch(
            "opennutrilab.products.api.openfoodfacts.services.requests.get",
            return_value=mock_response,
        ),
        pytest.raises(OFFProductNotFoundError, match="Barcode mismatch"),
    ):
        fetch_from_off("999999")


def test_product_schema_to_form_data():
    """Test conversion from ProductSchema to ProductFormSchema."""
    product = OFFProductSchema(
        barcode="123456",
        name="Test Product",
        image_url="https://example.com/image.jpg",
        macronutrients=OFFMacronutrientsSchema(
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


def test_to_ingredient_inputs_keeps_the_tree():
    ingredients = [
        OFFIngredientSchema(name="Sucre", percentage=56.3),
        OFFIngredientSchema(
            name="Lait écrémé en poudre",
            ingredients=[OFFIngredientSchema(name=" lait ", percentage=8.7)],
        ),
    ]

    inputs = to_ingredient_inputs(ingredients)

    assert [i.name for i in inputs] == ["Sucre", "Lait écrémé en poudre"]
    assert inputs[0].percentage == Decimal("56.3")
    assert inputs[0].sub_ingredients == []
    assert [(c.name, c.percentage) for c in inputs[1].sub_ingredients] == [
        ("lait", Decimal("8.7"))
    ]


def test_to_ingredient_inputs_drops_what_could_not_be_saved():
    """
    OFF data that would fail the schemas must not make the product
    unsavable: nameless ingredients are dropped, impossible percentages
    forgotten.
    """
    ingredients = [
        OFFIngredientSchema(name="   "),
        OFFIngredientSchema(name="Concentrate", percentage=180.0),
        OFFIngredientSchema(name="Water", percentage=-1.0),
    ]

    inputs = to_ingredient_inputs(ingredients)

    assert [(i.name, i.percentage) for i in inputs] == [
        ("Concentrate", None),
        ("Water", None),
    ]


def test_to_ingredient_inputs_of_nothing():
    assert to_ingredient_inputs(None) == []


def test_fetch_from_off_identifies_the_client():
    """
    OpenFoodFacts answers 403 Forbidden to clients that do not name
    themselves, which is what requests sends by default. Without this header
    every barcode lookup fails and the product form 500s.
    """
    mock_response = MagicMock()
    mock_response.json.return_value = {
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
    mock_response.status_code = 200

    with patch(
        "opennutrilab.products.api.openfoodfacts.services.requests.get",
        return_value=mock_response,
    ) as mock_get:
        fetch_from_off(query_barcode="999999")

    headers = mock_get.call_args.kwargs["headers"]
    assert "OpenNutriLab" in headers["User-Agent"]
