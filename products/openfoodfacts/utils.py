import json
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import requests
from django.conf import settings
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.utils.safestring import SafeText
from ninja.errors import HttpError
from pydantic import ValidationError

from products.models import Ingredient
from products.models import IngredientRef
from products.models import Product
from products.openfoodfacts.api_response_shema import OFFProductAPIResponseSchema
from products.openfoodfacts.api_response_shema import StatusEnum

from .schema import OFFIngredientSchema
from .schema import OFFProductSchema

if TYPE_CHECKING:
    from django.db.models.query import QuerySet


def fetch_local_product(
    barcode: str,
    base_dir: Path | None = None,
) -> OFFProductSchema:
    """
    Load a local OFF-style JSON file and convert it to an OFFProductSchema.

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


def fetch_product(query_barcode: str):
    """
    Fetch product data from OpenFoodFacts API for a given barcode.
    """
    url = f"https://world.openfoodfacts.org/api/v3/product/{query_barcode}.json"

    try:
        response = requests.get(url, timeout=5, allow_redirects=True)
        response.raise_for_status()
    except requests.HTTPError as e:
        raise HttpError(
            status_code=502,  # Bad Gateway → API externe en erreur
            message=f"External API returned an error: {e}",
        ) from e
    except requests.RequestException as e:
        raise HttpError(
            status_code=503,  # Service Unavailable → connexion impossible
            message=f"External API unreachable: {e}",
        ) from e

    # JSON parsing
    try:
        data = response.json()
    except ValueError as e:
        raise HttpError(
            status_code=502,
            message=f"Invalid JSON received from external API: {e}",
        ) from e

    # Validation Pydantic
    try:
        # We keep it in case if we need later more than one alias for one field:
        # from .data_mapping import openfoodfacts_data_mapping as spec  # noqa: ERA001
        # result = cast("dict[str, Any]", glom(target=data, spec=spec))  # noqa: ERA001
        # Eventually use AliasChoices from pydantic lib
        api_product_response = OFFProductAPIResponseSchema.model_validate(data)
    except ValidationError as e:
        raise HttpError(
            status_code=500,
            message=f"Invalid API response format for {query_barcode}: {e}",
        ) from e

    # API-level errors
    if api_product_response.status == StatusEnum.failure:
        raise HttpError(status_code=404, message="Product not found.")

    if api_product_response.status in (
        StatusEnum.success_with_errors,
        StatusEnum.success_with_warnings,
    ):
        raise HttpError(
            status_code=400,
            message=str(api_product_response.errors or api_product_response.warnings),
        )

    product = api_product_response.product

    if product is None:
        raise HttpError(
            status_code=500,
            message=(
                f"API response for {query_barcode} indicated success "
                "but returned no product."
            ),
        )

    if query_barcode != product.barcode:
        msg = (
            f"Barcode mismatch: requested {query_barcode}, "
            f"but got {product.barcode} from OpenFoodFacts"
        )
        raise ValueError(msg)

    return product


def render_ingredients_table(
    ingredients: list["OFFIngredientSchema"] | None,
) -> SafeText:
    """Recursively renders a SAFE HTML table of nested ingredients."""
    if not ingredients:
        return format_html("<p><em>No ingredients listed.</em></p>")

    rows: list[SafeText] = []

    for ing in ingredients:
        if ing.ingredients:
            sub_table = render_ingredients_table(ing.ingredients)
            sub_cell = format_html("<td colspan='2'>{}</td>", sub_table)
        else:
            sub_cell = format_html("<td colspan='2'><em>None</em></td>")

        row = format_html(
            "<tr><td>{}</td><td>{}</td>{}</tr>",
            ing.name,  # automatically escaped
            ing.percentage,  # automatically escaped
            sub_cell,  # already safe
        )

        rows.append(row)

    body = format_html_join("", "{}", ((row,) for row in rows))

    return format_html(
        """
        <table class="table table-striped table-bordered mb-0">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Percent</th>
                    <th>Sub-Ingredients</th>
                </tr>
            </thead>
            <tbody>
                {}
            </tbody>
        </table>
        """,
        body,
    )


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
        try:
            ingredient_ref = IngredientRef.objects.get(name=ing.name.strip())
        except IngredientRef.DoesNotExist:
            ingredient_ref = None

        # Create linked ingredient for the product
        ingredient = Ingredient.objects.create(
            name=ing.name,
            product=product,
            parent=parent,
            reference=ingredient_ref,
            percentage=getattr(ing, "percentage", None),  # if available
        )

        ingredient, _is_created = Ingredient.objects.update_or_create(
            product=product,
            parent=parent,
            name=ing.name,
            defaults={"percentage": getattr(ing, "percentage", None)},
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
    normalized_name = ingredient.name.strip().lower()

    # Compute whether this ingredient exists in the reference database
    data["has_reference"] = normalized_name in reference_names

    return data
