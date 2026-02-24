from ninja import Schema
from ninja.errors import ValidationError
from pydantic import field_validator

from products.api.types import QuantityType
from products.fields import validate_ean13


class MacronutrientInput(Schema):
    """Data for a single macronutrient line in the form."""

    name: str
    amount: QuantityType


class NutritionalValuesInput(Schema):
    """The grouped nutritional block in the form."""

    energy: QuantityType
    macronutrients: list[MacronutrientInput] = []


class IngredientInput(Schema):
    name: str
    percentage: float | None = None

    # https://django-ninja.dev/guides/response/?h=self#self-referencing-schemes
    sub_ingredients: list["IngredientInput"] = []


IngredientInput.model_rebuild()


class ProductCreate(Schema):
    """The main schema received when the user clicks 'Save'."""

    barcode: str
    name: str
    image_url: str = ""
    description: str = ""
    group_level_1: str = ""
    group_level_2: str = ""
    nutritional_values: NutritionalValuesInput
    ingredients: list[IngredientInput] = []

    @field_validator("barcode")
    @classmethod
    def validate_barcode_format(cls, barcode: str) -> str:
        # On réutilise ta fonction de validation existante
        try:
            validate_ean13(value=barcode)
        except ValidationError as e:
            msg = f"Invalid product data format for {barcode}: {e}"
            raise ValueError(msg) from e
        return barcode


# -------------------------------------------------------------
# UPDATE SCHEMAS (PATCH) - Tout est optionnel pour permettre une mise à jour partielle
# -------------------------------------------------------------


# On réutilise MacronutrientIn ou on en crée un spécifique
class MacronutrientUpdate(Schema):
    name: str
    amount: float


class NutritionalValuesUpdate(Schema):
    # Tout est Optionnel ici pour permettre une mise à jour partielle
    energy: float | None = None
    macronutrients: list[MacronutrientUpdate] | None = None


class ProductUpdate(Schema):
    # On ne met pas le barcode ici car il ne change pas
    name: str | None = None
    description: str | None = None
    image_url: str | None = None
    group_level_1: str | None = None
    group_level_2: str | None = None
    nutritional_values: NutritionalValuesUpdate | None = None
    ingredients: list[IngredientInput] | None = None
