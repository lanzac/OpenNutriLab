from typing import Any
from typing import cast

from ninja.orm import register_field
from pint.registry import Quantity
from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema
from quantityfield.units import ureg

from products.units import DEFAULT_UNIT


class QuantityType:
    """
    Pydantic-compatible type that accepts:
        - float
        - {"value": float, "unit": str}
        - pint.Quantity

    And always returns:
        pint.Quantity (rounded)
    """

    __precision__ = 2  # number of decimal places

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: GetCoreSchemaHandler):
        def validate(value: Any) -> Quantity | None:
            """
            Convert various inputs into a pint.Quantity.

            Always returns:
                pint.Quantity | None
            """
            if value is None:
                return None

            # Already a pint.Quantity (e.g., coming from ORM)
            if isinstance(value, ureg.Quantity):
                magnitude: float = cls._round_value(float(value.magnitude))
                return cast("Quantity", magnitude * value.units)

            # Dictionary input: {"value": float, "unit": str}
            if isinstance(value, dict):
                typed_value = cast("dict[str, Any]", value)
                magnitude = cls._round_value(float(typed_value["value"]))
                unit: str = typed_value["unit"]
                return magnitude * ureg(input_string=unit)

            # Float input: use default unit
            try:
                magnitude = cls._round_value(float(value))
                return magnitude * ureg(DEFAULT_UNIT)
            except (TypeError, ValueError) as err:
                msg = f"Invalid quantity format: {err}"
                raise ValueError(msg) from err

        def serialize(value: Quantity | None) -> dict[str, Any] | None:
            if value is None:
                return None
            return {
                "value": cls._round_value(float(value.magnitude)),
                "unit": f"{value.units:~P}",
            }

        return core_schema.json_or_python_schema(
            python_schema=core_schema.no_info_plain_validator_function(validate),
            json_schema=core_schema.typed_dict_schema(
                fields={
                    "value": core_schema.typed_dict_field(core_schema.float_schema()),
                    "unit": core_schema.typed_dict_field(core_schema.str_schema()),
                }
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(serialize),
        )

    @classmethod
    def _round_value(cls, val: float) -> float:
        return round(val, cls.__precision__)


# Register mapping for Django FloatField (used internally by QuantityField)
register_field(django_field="FloatField", python_type=QuantityType)
