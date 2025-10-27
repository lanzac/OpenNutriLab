import json
from pathlib import Path
from typing import Any
from typing import cast

import requests
from django.conf import settings
from glom import glom  # pyright: ignore[reportUnknownVariableType]

from .data_mapping import openfoodfacts_data_mapping as spec
from .schema import ProductSchema


def fetch_local_product_data(
    barcode: str,
    base_dir: Path | None = None,
) -> ProductSchema:
    """
    Load a local OFF-style JSON file and convert it to a ProductSchema.

    Args:
        barcode: The product barcode.
        base_dir: Optional base directory, defaults to Django's BASE_DIR.
    """
    base_dir = base_dir or Path(settings.BASE_DIR)
    local_path = base_dir / "foods" / "tests" / "data" / f"{barcode}.json"

    with Path.open(local_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = cast("dict[str, Any]", glom(target=data, spec=spec))
    result["barcode"] = barcode
    return ProductSchema(**result)


def fetch_product_data(barcode: str) -> ProductSchema:
    url = f"https://world.openfoodfacts.net/api/v2/product/{barcode}.json"
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    data = response.json()
    result = cast("dict[str, Any]", glom(target=data, spec=spec))
    result["barcode"] = barcode  # Add barcode field to the result
    return ProductSchema(**result)
