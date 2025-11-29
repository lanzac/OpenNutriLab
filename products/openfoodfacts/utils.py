import json
from pathlib import Path

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

from .schema import OFFIngredientsSchema
from .schema import OFFProductSchema


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
        # Eventually use AliasChoices from pydantic lib
        product = OFFProductSchema.model_validate(product_data)
    except ValidationError as e:
        msg = f"Invalid product data format for {query_barcode}: {e}"
        raise ValueError(msg) from e

    # Check barcode consistency
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


def render_ingredients_table(
    ingredients: list["OFFIngredientsSchema"] | None,
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


def get_schema_from_ingredients(product: Product) -> list[OFFIngredientsSchema]:
    """
    Reconstructs the COMPLETE tree of a product's ingredients
    WITHOUT recursion, in 2 passes.
    """

    # 1) Load ALL ingredients of the product
    ingredients = (
        product.ingredients.select_related("parent")
        .order_by("id")  # GLOBAL SORT
        .all()
    )

    # 2) Django → Schema mapping table
    schema_map: dict[int, OFFIngredientsSchema] = {}

    for ing in ingredients:
        schema_map[ing.id] = OFFIngredientsSchema(
            text=ing.name,
            percent=ing.percentage,
            ingredients=None,  # will be filled later
        )

    # 3) Building the tree (parent → children relations)
    roots: list[OFFIngredientsSchema] = []

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
    ingredients_schema: list[OFFIngredientsSchema],
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

        # Recursive call on sub-ingredients
        if ing.ingredients:
            save_ingredients_from_schema(
                ing.ingredients,
                product=product,
                parent=ingredient,
            )
