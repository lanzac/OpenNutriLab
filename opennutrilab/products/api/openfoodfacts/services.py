from decimal import Decimal
from decimal import InvalidOperation
from http import HTTPStatus
from typing import Any

import requests
from pydantic import ValidationError

from opennutrilab.products.api.openfoodfacts.schemas import OFFIngredientSchema
from opennutrilab.products.api.openfoodfacts.schemas import OFFProductAPIResponseSchema
from opennutrilab.products.api.openfoodfacts.schemas import OFFProductSchema
from opennutrilab.products.api.openfoodfacts.schemas import StatusEnum
from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.models import IngredientTaxon
from opennutrilab.products.models import Nutrient


class OFFError(Exception):
    """OpenFoodFacts could not give a usable answer for a barcode.

    Raised for an unreachable API, an upstream error status, or a response
    that does not parse. Callers turn it into whatever their layer speaks: a
    notice on the product form, an HTTP status in an API route.
    """


class OFFProductNotFoundError(OFFError):
    """OpenFoodFacts has no product for this barcode."""


# OpenFoodFacts rejects generic clients: without a User-Agent naming the
# application, the API answers 403 Forbidden. See
# https://openfoodfacts.github.io/openfoodfacts-server/api/#authentication
OFF_HEADERS = {
    "User-Agent": "OpenNutriLab/0.1.0 (https://github.com/lanzac/OpenNutriLab)",
}


def normalize_barcode(barcode: str) -> str:
    """
    Drop the leading zeros OFF adds when padding a short code to 13 digits.

    A 12-digit UPC-A queried as `322982079455` is stored as `0322982079455`,
    so the two spellings have to compare equal.
    """
    return barcode.strip().lstrip("0")


def fetch_from_off(
    query_barcode: str,
) -> OFFProductSchema:
    """
    Fetch product data from OpenFoodFacts API for a given barcode.
    """
    url = f"https://world.openfoodfacts.org/api/v3/product/{query_barcode}.json"

    try:
        response = requests.get(
            url,
            timeout=30,
            allow_redirects=True,
            headers=OFF_HEADERS,
        )
    except requests.RequestException as e:
        msg = f"External API unreachable: {e}"
        raise OFFError(msg) from e

    # OFF answers an unknown barcode with 404 *and* a well-formed failure body,
    # so the status line alone cannot tell "no such product" from a broken
    # gateway. Let 404 fall through to the body checks below, which turn
    # `status: failure` into a not-found; anything else is an upstream error.
    if response.status_code not in (HTTPStatus.OK, HTTPStatus.NOT_FOUND):
        msg = f"External API returned an error: {response.status_code} for url: {url}"
        raise OFFError(msg)

    # JSON parsing
    try:
        data = response.json()
    except ValueError as e:
        msg = f"Invalid JSON received from external API: {e}"
        raise OFFError(msg) from e

    # Validation Pydantic
    try:
        api_product_response = OFFProductAPIResponseSchema.model_validate(data)
    except ValidationError as e:
        msg = f"Invalid API response format for {query_barcode}: {e}"
        raise OFFError(msg) from e

    # API-level errors
    if api_product_response.status == StatusEnum.failure:
        msg = f"Product {query_barcode} not found."
        raise OFFProductNotFoundError(msg)

    # `success_with_warnings` is the ordinary answer for a short barcode: OFF
    # pads codes to 13 digits and reports the padding as a
    # `different_normalized_product_code` warning. Only errors are fatal.
    if api_product_response.status == StatusEnum.success_with_errors:
        raise OFFError(str(api_product_response.errors))

    product = api_product_response.product

    if product is None:
        msg = (
            f"API response for {query_barcode} indicated success "
            "but returned no product."
        )
        raise OFFError(msg)

    # OFF answering with another product means it has none for this barcode.
    if normalize_barcode(query_barcode) != normalize_barcode(product.barcode):
        msg = (
            f"Barcode mismatch: requested {query_barcode}, "
            f"but got {product.barcode} from OpenFoodFacts"
        )
        raise OFFProductNotFoundError(msg)

    return product


def _off_ids(ingredients: list[OFFIngredientSchema] | None) -> set[str]:
    ids: set[str] = set()
    for ingredient in ingredients or []:
        if ingredient.off_id:
            ids.add(ingredient.off_id[:255])
        ids |= _off_ids(ingredient.ingredients)
    return ids


def to_ingredient_inputs(
    ingredients: list[OFFIngredientSchema] | None,
) -> list[IngredientInput]:
    """
    OpenFoodFacts' ingredient tree, as the services expect it.

    An ingredient is named by the taxonomy's English name for its OFF id (see
    IngredientTaxon), not by OFF's `text`, which is the label's wording in the
    product's language. The label's wording is the fallback when the taxonomy
    has no English name for it, or has not been loaded.

    OFF sometimes lists an ingredient with no text, or a percentage outside
    0-100 (an estimate gone wrong); the first is dropped and the second
    forgotten, rather than making the whole product unsavable.
    """
    ids = _off_ids(ingredients)
    english_names = (
        dict(
            IngredientTaxon.objects.filter(off_id__in=ids)
            .exclude(name_en="")
            .values_list("off_id", "name_en")
        )
        if ids
        else {}
    )
    return _ingredient_inputs(ingredients, english_names)


def _ingredient_inputs(
    ingredients: list[OFFIngredientSchema] | None,
    english_names: dict[str, str],
) -> list[IngredientInput]:
    inputs: list[IngredientInput] = []
    for ingredient in ingredients or []:
        off_id = ingredient.off_id[:255]
        name = english_names.get(off_id) or ingredient.name.strip()
        if not name:
            continue
        percentage = ingredient.percentage
        if percentage is not None and not 0 <= percentage <= 100:  # noqa: PLR2004
            percentage = None
        inputs.append(
            IngredientInput(
                name=name[:255],
                percentage=None if percentage is None else Decimal(str(percentage)),
                off_id=off_id,
                off_ciqual_food_code=(ingredient.ciqual_food_code or "")[:10],
                off_ciqual_proxy_food_code=(ingredient.ciqual_proxy_food_code or "")[
                    :10
                ],
                sub_ingredients=_ingredient_inputs(
                    ingredient.ingredients, english_names
                ),
            )
        )
    return inputs


# OpenFoodFacts stores every mass nutrient in grams: vitamin D of 3.4 µg is
# 3.4e-06. Factors from grams to each catalogue unit.
_FROM_GRAMS = {
    Nutrient.Unit.GRAM: Decimal(1),
    Nutrient.Unit.MILLIGRAM: Decimal(1_000),
    Nutrient.Unit.MICROGRAM: Decimal(1_000_000),
}
_FOUR_PLACES = Decimal("0.0001")


def declared_nutrients_from_off(nutriments: dict[str, Any]) -> dict[str, Decimal]:
    """
    Label values from an OpenFoodFacts product, keyed by Nutrient.code.

    Each catalogue nutrient with an off_key is read from `<off_key>_100g` and
    converted to its own unit. Energy is already in kJ. Missing, unreadable
    and negative values are left out.
    """
    values: dict[str, Decimal] = {}
    for nutrient in Nutrient.objects.exclude(off_key=None):
        raw = nutriments.get(f"{nutrient.off_key}_100g")
        if raw is None or raw == "":
            continue
        try:
            amount = Decimal(str(raw))
        except InvalidOperation:
            continue
        if not amount.is_finite() or amount < 0:
            continue
        unit = Nutrient.Unit(nutrient.unit)
        if unit is not Nutrient.Unit.KILOJOULE:
            amount *= _FROM_GRAMS[unit]
        values[nutrient.code] = amount.quantize(_FOUR_PLACES)
    return values
