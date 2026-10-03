from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any

import requests
from pydantic import ValidationError

from products.api.openfoodfacts.schemas import OFFIngredientSchema
from products.api.openfoodfacts.schemas import OFFProductAPIResponseSchema
from products.api.openfoodfacts.schemas import OFFProductSchema
from products.api.openfoodfacts.schemas import StatusEnum
from products.models import Ingredient
from products.models import IngredientRef
from products.models import Product

if TYPE_CHECKING:
    from django.db.models.query import QuerySet


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


def get_schema_from_ingredients(product: Product) -> list[OFFIngredientSchema]:
    """
    Reconstructs the COMPLETE tree of a product's ingredients
    WITHOUT recursion, in 2 passes.
    """

    # 1) Load ALL ingredients of the product
    ingredients: QuerySet[Ingredient] = (
        product.ingredients.select_related("parent")
        .order_by("id")  # GLOBAL SORT
        .all()
    )

    # 2) Django → Schema mapping table
    schema_map: dict[int, OFFIngredientSchema] = {}

    for ing in ingredients:
        ingredient_schema = OFFIngredientSchema.model_validate(ing)
        schema_map[ing.id] = ingredient_schema

    # 3) Building the tree (parent → children relations)
    roots: list[OFFIngredientSchema] = []

    for ing in ingredients:
        schema = schema_map[ing.id]

        if ing.parent_id is None:
            # root ingredient
            roots.append(schema)
        else:
            # child ingredient
            parent_schema = schema_map[ing.parent_id]

            if parent_schema.ingredients is None:
                parent_schema.ingredients = []

            parent_schema.ingredients.append(schema)

    return roots


def save_ingredients_from_schema(
    ingredients_schema: list[OFFIngredientSchema],
    product: Product,
    parent: Ingredient | None = None,
) -> None:
    """
    Recursive saving of OFF ingredients into Django database.
    """

    for ing in ingredients_schema or []:
        # Search or create reference ingredient
        ingredient_ref: IngredientRef | None = IngredientRef.objects.filter(
            name=ing.name.strip()
        ).first()

        ingredient, _is_created = Ingredient.objects.update_or_create(
            product=product,
            parent=parent,
            name=ing.name,
            defaults={
                "percentage": getattr(ing, "percentage", None),
                "reference": ingredient_ref,
            },
        )

        # Recursive call on sub-ingredients
        if ing.ingredients:
            save_ingredients_from_schema(
                ingredients_schema=ing.ingredients,
                product=product,
                parent=ingredient,
            )


def build_ingredient_json_from_schema(
    ingredient: OFFIngredientSchema, reference_names: set[str]
) -> dict[str, Any]:
    """
    Build a JSON-serializable dictionary for a single ingredient,
    and inject a computed boolean field `has_reference`.

    The `has_reference` field is derived by checking if the ingredient name
    exists in the preloaded set of reference ingredient names.

    This avoids doing a database query inside a loop and greatly improves performance.

    :param ingredient: Ingredient schema or object with a `name` attribute
    :param reference_names: A set of normalized reference ingredient names
    :return: A dictionary ready for JSON serialization
    """

    # Dump the ingredient data into a plain Python dictionary
    data = ingredient.model_dump(by_alias=False)

    # Normalize the ingredient name for a reliable comparison
    normalized_name = (ingredient.name or "").strip().lower()

    # Compute whether this ingredient exists in the reference database
    data["has_reference"] = normalized_name in reference_names

    return data
