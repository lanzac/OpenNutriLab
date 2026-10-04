# Test OpenFoodFacts related functionalities
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from requests import RequestException

from opennutrilab.products.api.openfoodfacts.schemas import OFFProductSchema
from opennutrilab.products.api.openfoodfacts.services import OFFError
from opennutrilab.products.api.openfoodfacts.services import OFFProductNotFoundError
from opennutrilab.products.api.openfoodfacts.services import declared_nutrients_from_off
from opennutrilab.products.api.openfoodfacts.services import fetch_from_off
from opennutrilab.products.api.openfoodfacts.services import (
    ingredient_inputs_from_label,
)
from opennutrilab.products.models import Nutrient

# A product recorded from OpenFoodFacts (API v2: the envelope differs from
# the v3 one fetch_from_off reads, but the "product" object has the same shape).
RECORDED_PRODUCT = Path(__file__).parent / "data" / "3229820794556.json"
# Extract of OFF's ingredient taxonomy: the entries of that product, plus ones
# with no English name.


def test_product_schema_parses_a_recorded_off_product():
    """OFFProductSchema maps a real OpenFoodFacts payload, not a hand-made one."""
    with RECORDED_PRODUCT.open(encoding="utf-8") as f:
        payload: dict[str, Any] = json.load(f)["product"]

    product = OFFProductSchema.model_validate(payload)

    assert product.barcode == "3229820794556"
    assert product.name == "Muesli Protéines"
    assert product.nutriments["fat_100g"] == 12  # noqa: PLR2004
    assert product.group_level_1 == "Cereals and potatoes"
    # The ingredients are read from the label's text and its language, and OFF's
    # own parsing of them is not read at all.
    assert product.ingredients_lc == "fr"
    assert product.ingredients_text is not None
    assert product.ingredients_text.startswith("Flocons de soja* 33%, ")
    assert not hasattr(product, "ingredients")


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
        nutriments={"fat_100g": 3.0, "proteins_100g": 1.5},
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


@pytest.mark.django_db
def test_declared_values_are_read_through_the_catalogue_off_keys():
    """Recorded muesli: energy is kJ in OFF, masses are grams."""
    with RECORDED_PRODUCT.open(encoding="utf-8") as f:
        nutriments = json.load(f)["product"]["nutriments"]

    values = declared_nutrients_from_off(nutriments)

    assert values == {
        "energy": Decimal(1598),
        "fat": Decimal(12),
        "saturated_fat": Decimal("1.9"),
        "carbohydrates": Decimal(41),
        "sugars": Decimal(11),
        "fiber": Decimal(13),
        "proteins": Decimal(21),
        "salt": Decimal("0.03"),
    }


@pytest.mark.django_db
def test_declared_values_are_converted_from_grams_to_each_unit():
    """OFF stores 3.4 µg of vitamin D as 3.4e-06 g."""
    Nutrient.objects.create(
        code="vitamin_d",
        name_en="Vitamin D",
        name_fr="Vitamine D",
        unit="µg",
        group="vitamin",
        off_key="vitamin-d",
    )
    Nutrient.objects.create(
        code="iron",
        name_en="Iron",
        name_fr="Fer",
        unit="mg",
        group="mineral",
        off_key="iron",
    )

    values = declared_nutrients_from_off(
        {"vitamin-d_100g": 3.4e-06, "iron_100g": 0.012}
    )

    assert values == {"vitamin_d": Decimal("3.4"), "iron": Decimal(12)}


@pytest.mark.django_db
def test_unusable_declared_values_are_left_out():
    values = declared_nutrients_from_off(
        {"fat_100g": "", "sugars_100g": "n/a", "salt_100g": -1, "fiber_100g": None}
    )

    assert values == {}


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


def test_the_recorded_muesli_is_read_from_its_label_and_loses_nothing():
    """
    OFF's own list for this product says "soja", "fruits rouges" and (in the
    live product) leaves out the buckwheat: the words that tell flakes from
    beans, and freeze-dried from raw, are only in the label.
    """
    with RECORDED_PRODUCT.open(encoding="utf-8") as f:
        payload: dict[str, Any] = json.load(f)["product"]
    assert payload["ingredients"][0]["text"] == "soja"
    product = OFFProductSchema.model_validate(payload)

    inputs, warnings = ingredient_inputs_from_label(
        product.ingredients_text, product.ingredients_lc
    )

    assert warnings == []
    assert [(i.name, i.percentage) for i in inputs] == [
        ("flocons de soja", Decimal(33)),
        ("flocons d'avoine", Decimal(26)),
        ("flocons de blé", Decimal(25)),
        ("raisins secs", Decimal(8)),
        ("dattes", Decimal(5)),
        ("fruits rouges lyophilisés", Decimal("1.4")),
        ("graines de sarrasin", Decimal(1)),
    ]
    assert {i.language for i in inputs} == {"fr"}
    assert [c.name for c in inputs[3].sub_ingredients] == [
        "raisins",
        "huile de tournesol",
    ]


def test_the_ingredients_come_with_the_percentages_the_label_prints():
    inputs, _warnings = ingredient_inputs_from_label(
        "Polpa di pomodoro 70%, cipolla, peperoncino 0,1%", "it"
    )

    assert [(i.name, i.percentage, i.language) for i in inputs] == [
        ("polpa di pomodoro", Decimal(70), "it"),
        ("cipolla", None, "it"),
        ("peperoncino", Decimal("0.1"), "it"),
    ]


def test_a_text_that_looks_badly_read_gives_no_ingredient_and_says_why():
    inputs, warnings = ingredient_inputs_from_label(
        "Sucre, émulsifiants : lécithines [SOJA), vanilline", "fr"
    )

    assert inputs == []
    assert [w.stops_reading for w in warnings] == [True]
    assert "[SOJA)" in warnings[0].message()


@pytest.mark.parametrize("text", [None, ""])
def test_a_product_without_a_list_gives_no_ingredient_and_a_warning(text: str | None):
    inputs, warnings = ingredient_inputs_from_label(text, "fr")

    assert inputs == []
    assert [w.stops_reading for w in warnings] == [False]


def test_a_name_longer_than_an_ingredient_can_have_is_cut():
    inputs, _warnings = ingredient_inputs_from_label("a" * 300 + " b, sel", "fr")

    assert len(inputs[0].name) == 255  # noqa: PLR2004


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
