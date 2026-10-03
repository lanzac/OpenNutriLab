from decimal import Decimal
from http import HTTPStatus

import requests
from pydantic import ValidationError

from products.api.openfoodfacts.schemas import OFFIngredientSchema
from products.api.openfoodfacts.schemas import OFFProductAPIResponseSchema
from products.api.openfoodfacts.schemas import OFFProductSchema
from products.api.openfoodfacts.schemas import StatusEnum
from products.api.schemas.inbound import IngredientInput


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


def to_ingredient_inputs(
    ingredients: list[OFFIngredientSchema] | None,
) -> list[IngredientInput]:
    """
    OpenFoodFacts' ingredient tree, as the services expect it.

    OFF sometimes lists an ingredient with no text, or a percentage outside
    0-100 (an estimate gone wrong); the first is dropped and the second
    forgotten, rather than making the whole product unsavable.
    """
    inputs: list[IngredientInput] = []
    for ingredient in ingredients or []:
        name = ingredient.name.strip()
        if not name:
            continue
        percentage = ingredient.percentage
        if percentage is not None and not 0 <= percentage <= 100:  # noqa: PLR2004
            percentage = None
        inputs.append(
            IngredientInput(
                name=name[:255],
                percentage=None if percentage is None else Decimal(str(percentage)),
                sub_ingredients=to_ingredient_inputs(ingredient.ingredients),
            )
        )
    return inputs
