import json
from pathlib import Path

import requests
from django.conf import settings
from ninja.errors import HttpError
from pydantic import ValidationError

from .schema import OFFProductSchema


def fetch_local_product(
    barcode: str,
    base_dir: Path | None = None,
) -> OFFProductSchema:
    """
    Load a local OFF-style JSON file and convert it to a OFFProductSchema.

    Args:
        barcode: The product barcode.
        base_dir: Optional base directory, defaults to Django's BASE_DIR.
    """
    base_dir = base_dir or Path(settings.BASE_DIR)
    local_path = base_dir / "products" / "tests" / "data" / f"{barcode}.json"

    with Path.open(local_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    try:
        product = OFFProductSchema.model_validate(data["product"])
    except ValidationError as e:
        msg = f"Invalid product data format for {barcode}: {e}"
        raise ValueError(msg) from e
    return product


def fetch_product_data(query_barcode: str):
    # https://openfoodfacts.github.io/openfoodfacts-server/api/#api-deployments
    # Production: https://world.openfoodfacts.org
    # Staging: https://world.openfoodfacts.net (but looks to have deprecated data?)
    url = f"https://world.openfoodfacts.org/api/v2/product/{query_barcode}.json"

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if "product" not in data:
            raise HttpError(
                status_code=404, message=f"Product {query_barcode} not found"
            )
        return data["product"]
    except requests.RequestException as e:
        raise HttpError(status_code=500, message=f"External API error: {e}") from e


def fetch_product(query_barcode: str) -> OFFProductSchema:
    product_data = fetch_product_data(query_barcode)

    try:
        # We keep it in case if we need later more than one alias for one field:
        # from .data_mapping import openfoodfacts_data_mapping as spec  # noqa: ERA001
        # result = cast("dict[str, Any]", glom(target=data, spec=spec))  # noqa: ERA001
        # Eventually use AliasChoices from pydandic lib
        product = OFFProductSchema.model_validate(product_data)
    except ValidationError as e:
        msg = f"Invalid product data format for {query_barcode}: {e}"
        raise ValueError(msg) from e

    # Vérifie la cohérence du code-barres
    if not product.barcode:
        msg = f"Product {query_barcode} has no barcode in response"
        raise ValueError(msg)

    if query_barcode != product.barcode:
        msg = (
            f"Barcode mismatch: requested {query_barcode}, "
            f"but got {product.barcode} from OpenFoodFacts"
        )
        raise ValueError(msg)

    return product
