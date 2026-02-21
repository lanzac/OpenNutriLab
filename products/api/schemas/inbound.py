from ninja import Schema
from ninja.errors import ValidationError
from pydantic import field_validator

from products.fields import validate_ean13


class MacronutrientInput(Schema):
    """Data for a single macronutrient line in the form."""

    name: str
    amount: float  # Simple float for the user input


class NutritionalValuesInput(Schema):
    """The grouped nutritional block in the form."""

    energy: float
    macronutrients: list[MacronutrientInput] = []


class ProductCreate(Schema):
    """The main schema received when the user clicks 'Save'."""

    barcode: str
    name: str
    description: str
    group_level_1: str
    group_level_2: str
    nutritional_values: NutritionalValuesInput

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
    group_level_1: str | None = None
    group_level_2: str | None = None
    nutritional_values: NutritionalValuesUpdate | None = None
