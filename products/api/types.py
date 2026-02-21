from typing import Any
from typing import cast

from ninja.orm import register_field
from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema


class QuantityType:
    __precision__ = 2  # rounded to 1 decimal place by default

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: GetCoreSchemaHandler):
        float_schema = core_schema.float_schema()

        dict_schema = core_schema.typed_dict_schema(
            fields={
                "value": core_schema.typed_dict_field(core_schema.float_schema()),
                "unit": core_schema.typed_dict_field(core_schema.str_schema()),
            }
        )

        union = core_schema.union_schema([float_schema, dict_schema])

        return core_schema.no_info_before_validator_function(
            function=cls.validate,
            schema=union,
        )

    @classmethod
    def validate(cls, value: Any) -> dict[str, float | str] | float | None:
        """
        Converts various inputs (Quantity, float, dict) into dict {value, unit} and
        rounds value.
        """
        if value is None:
            return None

        # if it's already a dict, we round value if present
        if isinstance(value, dict):
            typed_value = cast("dict[str, Any]", value)
            val: Any | None = typed_value.get("value")
            if val is not None:
                typed_value["value"] = cls._round_value(val)
            return typed_value

        # Django-Pint Quantity object
        if hasattr(value, "magnitude"):
            return {
                "value": cls._round_value(float(value.magnitude)),
                "unit": str(value.units),
            }

        # Simple FloatField
        try:
            return cls._round_value(float(value))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _round_value(cls, val: float) -> float:
        return round(val, cls.__precision__)


# >>> Product._meta.get_field("energy").get_internal_type() -> 'FloatField'
register_field(django_field="FloatField", python_type=QuantityType)
