# Test OpenFoodFacts related fonctionalities
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from ninja.errors import HttpError
from requests import HTTPError
from requests import RequestException

from products.base_schema import MacronutrientsSchema
from products.base_schema import ProductSchema
from products.models import Ingredient
from products.models import IngredientRef
from products.models import Product
from products.openfoodfacts.schema import OFFIngredientSchema
from products.openfoodfacts.schema import OFFProductSchema
from products.openfoodfacts.schema import ProductFormSchema
from products.openfoodfacts.schema import product_schema_to_form_data
from products.openfoodfacts.utils import build_ingredient_json_from_schema
from products.openfoodfacts.utils import fetch_local_product
from products.openfoodfacts.utils import fetch_product
from products.openfoodfacts.utils import get_schema_from_ingredients
from products.openfoodfacts.utils import save_ingredients_from_schema


@pytest.fixture
def sample_data(tmp_path: Path) -> Path:
    """Create a temporary local JSON file mimicking OFF data."""
    data = {
        "product": {
            "code": "123456",
            "product_name": "Test Product",
            "image_small_url": "https://example.com/image.jpg",
            "nutriments": {
                "fat_100g": 10.0,
                "carbohydrates_100g": 20.0,
                "proteins_100g": 5.0,
            },
        },
    }
    data_dir = tmp_path / "products" / "tests" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / "123456.json"
    with Path.open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return file_path


def test_fetch_local_product_valid_data(sample_data: Path):
    """Test reading a local JSON and transforming it into a ProductSchema."""
    base_dir = sample_data.parents[3]  # root of the tmp project structure
    product: OFFProductSchema = fetch_local_product(
        barcode="123456",
        base_dir=base_dir,
    )

    expected_product: ProductSchema[MacronutrientsSchema, Any] = ProductSchema(
        barcode="123456",
        name="Test Product",
        image_url="https://example.com/image.jpg",
        macronutrients=MacronutrientsSchema(
            fat=10.0,
            carbohydrates=20.0,
            proteins=5.0,
        ),
    )

    assert isinstance(product, OFFProductSchema)
    assert product.dict() == expected_product.dict()


def test_fetch_local_product_invalid_data(sample_data: Path):
    """Test that invalid product data raises a ValueError."""
    # We volontarily corrupt the sample data
    with Path.open(sample_data, "r+", encoding="utf-8") as f:
        data = json.load(f)

        del data["product"]["product_name"]  # mandatory field removed
        data["product"]["nutriments"]["fat_100g"] = "not_a_number"

        f.seek(0)
        json.dump(data, f)
        f.truncate()

    base_dir = sample_data.parents[3]

    with pytest.raises(ValueError, match="Invalid product data format for 123456"):
        fetch_local_product("123456", base_dir)


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
    mock_response.raise_for_status.return_value = None

    with patch("products.openfoodfacts.utils.requests.get", return_value=mock_response):
        product: OFFProductSchema = fetch_product(query_barcode="999999")

    expected_product: ProductSchema[MacronutrientsSchema, Any] = ProductSchema(
        # Only fields present in mock_json set in form of expected ProductSchema
        # The rest will have their value by default
        barcode="999999",
        name="Remote Product",
        macronutrients=MacronutrientsSchema(
            fat=3.0,
            proteins=1.5,
        ),
    )

    assert isinstance(product, OFFProductSchema)
    assert product.dict() == expected_product.dict()


def test_fetch_product_http_error():
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = HTTPError("500 Server Error")

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product(query_barcode="999999")

    assert exc.value.status_code == 502  # noqa: PLR2004
    assert "External API returned an error" in exc.value.message


def test_fetch_product_request_exception():
    with (
        patch(
            "products.openfoodfacts.utils.requests.get",
            side_effect=RequestException("Connection timeout"),
        ),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 503  # noqa: PLR2004
    assert "External API unreachable" in exc.value.message


def test_fetch_product_invalid_json():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.side_effect = ValueError("Invalid JSON")

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 502  # noqa: PLR2004
    assert "Invalid JSON received" in exc.value.message


def test_fetch_product_invalid_schema():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"unexpected": "structure"}

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 500  # noqa: PLR2004
    assert "Invalid API response format" in exc.value.message


def test_fetch_product_not_found():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
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
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 404  # noqa: PLR2004


def test_fetch_product_success_with_warnings():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
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

    with (
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 400  # noqa: PLR2004
    assert "Incomplete data" in exc.value.message


def test_fetch_product_success_with_errors():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
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
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 400  # noqa: PLR2004
    assert "Invalid nutriments" in exc.value.message


def test_fetch_product_success_but_product_is_none():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
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
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(HttpError) as exc,
    ):
        fetch_product("999999")

    assert exc.value.status_code == 500  # noqa: PLR2004
    assert "returned no product" in exc.value.message


def test_fetch_product_barcode_mismatch():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
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
        patch("products.openfoodfacts.utils.requests.get", return_value=mock_response),
        pytest.raises(ValueError, match="Barcode mismatch"),
    ):
        fetch_product("999999")


def test_product_schema_to_form_data():
    """Test conversion from ProductSchema to ProductFormSchema."""
    product: ProductSchema[MacronutrientsSchema, Any] = ProductSchema(
        barcode="123456",
        name="Test Product",
        image_url="https://example.com/image.jpg",
        macronutrients=MacronutrientsSchema(
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


@pytest.mark.django_db
def test_get_schema_from_ingredients_builds_tree_correctly():
    product = Product.objects.create(barcode="1234567890123", name="Test Product")

    # Roots
    salt = Ingredient.objects.create(product=product, name="Salt", percentage=1)  # noqa: F841
    sugar = Ingredient.objects.create(product=product, name="Sugar", percentage=2)  # noqa: F841
    flour = Ingredient.objects.create(product=product, name="Flour", percentage=50)

    # Children
    wheat = Ingredient.objects.create(
        product=product, name="Wheat", percentage=30, parent=flour
    )

    gluten = Ingredient.objects.create(  # noqa: F841
        product=product, name="Gluten", percentage=10, parent=wheat
    )

    roots = get_schema_from_ingredients(product)

    # ---- Assertions ----
    assert isinstance(roots, list)
    assert all(isinstance(r, OFFIngredientSchema) for r in roots)

    # Expect 3 roots
    root_names = {r.name for r in roots}
    assert root_names == {"Salt", "Sugar", "Flour"}

    flour_schema: OFFIngredientSchema = next(r for r in roots if r.name == "Flour")

    # Flour has Wheat child
    assert flour_schema.ingredients is not None
    assert len(flour_schema.ingredients) == 1
    assert flour_schema.ingredients[0].name == "Wheat"

    wheat_schema: OFFIngredientSchema = flour_schema.ingredients[0]

    # Wheat has Gluten child
    assert wheat_schema.ingredients is not None
    assert len(wheat_schema.ingredients) == 1
    assert wheat_schema.ingredients[0].name == "Gluten"


@pytest.mark.django_db
def test_get_schema_from_ingredients_empty_product():
    product = Product.objects.create(barcode="0000000000000", name="Empty Product")

    roots = get_schema_from_ingredients(product)

    assert roots == []


@pytest.mark.django_db
def test_get_schema_from_ingredients_flat_list():
    product = Product.objects.create(barcode="9999999999999", name="Flat Product")

    Ingredient.objects.create(product=product, name="A")
    Ingredient.objects.create(product=product, name="B")
    Ingredient.objects.create(product=product, name="C")

    roots: list[OFFIngredientSchema] = get_schema_from_ingredients(product)

    assert len(roots) == 3  # noqa: PLR2004
    assert all(r.ingredients is None for r in roots)


@pytest.mark.django_db
def test_no_duplicate_nodes_in_tree():
    product = Product.objects.create(
        barcode="1111111111111", name="No Duplicate Product"
    )

    parent = Ingredient.objects.create(product=product, name="Parent")
    child = Ingredient.objects.create(product=product, name="Child", parent=parent)  # noqa: F841

    roots: list[OFFIngredientSchema] = get_schema_from_ingredients(product)

    assert len(roots) == 1
    assert roots[0].name == "Parent"

    all_nodes: list[OFFIngredientSchema] = []

    def collect(node: OFFIngredientSchema) -> None:
        all_nodes.append(node)
        if node.ingredients:
            for c in node.ingredients:
                collect(node=c)

    collect(node=roots[0])

    ids: list[int] = [id(n) for n in all_nodes]
    assert len(ids) == len(set[int](ids))  # no duplicates


@pytest.mark.django_db
def test_save_ingredients_creates_tree():
    product = Product.objects.create(barcode="1234567890123", name="Test Product")

    schema_tree = [
        OFFIngredientSchema(
            name="Flour",
            percentage=50,
            ingredients=[
                OFFIngredientSchema(
                    name="Wheat",
                    percentage=30,
                    ingredients=[OFFIngredientSchema(name="Gluten", percentage=10)],
                )
            ],
        ),
        OFFIngredientSchema(name="Salt", percentage=2),
    ]

    save_ingredients_from_schema(schema_tree, product)

    # Roots
    roots = Ingredient.objects.filter(product=product, parent=None)
    assert roots.count() == 2  # noqa: PLR2004

    flour = roots.get(name="Flour")

    wheat = Ingredient.objects.get(name="Wheat", parent=flour)
    gluten = Ingredient.objects.get(name="Gluten", parent=wheat)

    assert flour.percentage == 50  # noqa: PLR2004
    assert wheat.percentage == 30  # noqa: PLR2004
    assert gluten.percentage == 10  # noqa: PLR2004


@pytest.mark.django_db
def test_save_ingredients_links_reference():
    product = Product.objects.create(barcode="1111111111111", name="Ref Product")

    ref = IngredientRef.objects.create(name="Sugar")

    schema_tree = [OFFIngredientSchema(name="Sugar", percentage=20)]

    save_ingredients_from_schema(schema_tree, product)

    ing = Ingredient.objects.get(name="Sugar")
    assert ing.reference == ref


@pytest.mark.django_db
def test_save_ingredients_does_not_duplicate():
    product = Product.objects.create(barcode="2222222222222", name="Duplicate Product")

    schema_tree = [OFFIngredientSchema(name="Salt", percentage=1)]

    save_ingredients_from_schema(schema_tree, product)
    save_ingredients_from_schema(schema_tree, product)

    assert Ingredient.objects.filter(product=product, name="Salt").count() == 1


@pytest.mark.django_db
def test_save_ingredients_updates_percentage():
    product = Product.objects.create(barcode="3333333333333", name="Update Product")

    save_ingredients_from_schema(
        [OFFIngredientSchema(name="Salt", percentage=1)], product
    )

    save_ingredients_from_schema(
        [OFFIngredientSchema(name="Salt", percentage=5)], product
    )

    ing = Ingredient.objects.get(name="Salt")
    assert ing.percentage == 5  # noqa: PLR2004


@pytest.mark.django_db
def test_save_ingredients_empty_list():
    product = Product.objects.create(barcode="4444444444444", name="Empty Product")

    save_ingredients_from_schema([], product)

    assert Ingredient.objects.count() == 0


@pytest.mark.django_db
def test_save_ingredients_deep_tree():
    product = Product.objects.create(barcode="5555555555555", name="Deep Product")

    node = OFFIngredientSchema(name="Level 0")
    current = node

    for i in range(1, 30):
        child = OFFIngredientSchema(name=f"Level {i}")
        current.ingredients = [child]
        current = child

    save_ingredients_from_schema([node], product)

    assert Ingredient.objects.count() == 30  # noqa: PLR2004


def schema(
    name: str,
    percentage: float | None = None,
    children: list[OFFIngredientSchema] | None = None,
) -> OFFIngredientSchema:
    return OFFIngredientSchema(
        name=name, percentage=percentage, ingredients=children or []
    )


def test_build_ingredient_json_sets_has_reference_true():
    ingredient: OFFIngredientSchema = schema(name="Sugar", percentage=10)

    reference_names: set[str] = {"sugar", "salt"}

    data: dict[str, Any] = build_ingredient_json_from_schema(
        ingredient, reference_names
    )

    assert isinstance(data, dict)
    assert data["name"] == "Sugar"
    assert data["percentage"] == 10  # noqa: PLR2004
    assert data["has_reference"] is True


def test_build_ingredient_json_sets_has_reference_false():
    ingredient: OFFIngredientSchema = schema(name="UnknownIngredient")

    reference_names: set[str] = {"sugar", "salt"}

    data: dict[str, Any] = build_ingredient_json_from_schema(
        ingredient, reference_names
    )

    assert data["has_reference"] is False


def test_build_ingredient_json_normalizes_name():
    ingredient: OFFIngredientSchema = schema(name="  SuGaR  ")

    reference_names: set[str] = {"sugar"}

    data: dict[str, Any] = build_ingredient_json_from_schema(
        ingredient, reference_names
    )

    assert data["has_reference"] is True


def test_build_ingredient_json_preserves_model_dump():
    ingredient: OFFIngredientSchema = schema(name="Flour", percentage=50)

    data: dict[str, Any] = build_ingredient_json_from_schema(
        ingredient, reference_names=set[str]()
    )

    dumped: dict[str, Any] = ingredient.model_dump(by_alias=False)

    # Must match dump + injected field
    assert data["name"] == dumped["name"]
    assert data["percentage"] == dumped["percentage"]
    assert "has_reference" in data


def test_build_ingredient_json_keeps_children():
    ingredient: OFFIngredientSchema = schema(
        name="Flour",
        children=[
            schema(name="Wheat"),
            schema(name="Gluten"),
        ],
    )

    data: dict[str, Any] = build_ingredient_json_from_schema(
        ingredient, reference_names=set[str]()
    )

    assert "ingredients" in data
    assert len(data["ingredients"]) == 2  # noqa: PLR2004
    assert data["ingredients"][0]["name"] == "Wheat"


def test_build_ingredient_json_empty_name():
    ingredient: OFFIngredientSchema = schema(name="")

    reference_names: set[str] = {"salt"}

    data: dict[str, Any] = build_ingredient_json_from_schema(
        ingredient, reference_names
    )

    assert data["has_reference"] is False


def test_build_ingredient_json_optional_fields():
    ingredient: OFFIngredientSchema = OFFIngredientSchema(name="Salt")

    data: dict[str, Any] = build_ingredient_json_from_schema(
        ingredient, reference_names={"salt"}
    )

    assert data["percentage"] is None
    assert data["has_reference"] is True


def test_build_ingredient_json_is_json_serializable():
    ingredient: OFFIngredientSchema = schema(name="Sugar", percentage=5)

    data: dict[str, Any] = build_ingredient_json_from_schema(
        ingredient, reference_names={"sugar"}
    )

    json.dumps(obj=data)  # must not raise
