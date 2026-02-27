from typing import Any

import pytest
from ninja.errors import ValidationError as NinjaValidationError

from products.api.schemas.inbound import ProductCreate


def _minimal_payload(barcode: str, name: str) -> dict[str, Any]:
    return {
        "barcode": barcode,
        "name": name,
        "description": "",
        "group_level_1": "",
        "group_level_2": "",
        "nutritional_values": {
            "energy_kj": 100,
            "macronutrients": [],
        },
    }


def test_barcode_valid():
    valid_barcode = "4006381333931"  # EAN13 valide

    schema = ProductCreate.model_validate(
        _minimal_payload(valid_barcode, "Test Product")
    )

    assert schema.barcode == valid_barcode


def test_barcode_invalid():
    invalid_barcode = "1234567890123"  # checksum invalide

    with pytest.raises(NinjaValidationError) as exc_info:
        ProductCreate.model_validate(_minimal_payload(invalid_barcode, "Test Product"))
    assert "Invalid EAN-13 checksum." in str(exc_info.value)
