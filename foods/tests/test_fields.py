from django.db.models.fields import CharField


import pytest
from django.core.exceptions import ValidationError
from foods.fields import EAN13Field


@pytest.fixture
def ean13_field() -> CharField[str]:
    return EAN13Field()


def test_valid_ean13(ean13_field: EAN13Field) -> None:
    valid = "3560071429508"
    assert ean13_field.clean(value=valid, model_instance=None) == valid


@pytest.mark.parametrize(
    "value",
    [
        "3560071429501",  # mauvais checksum
        "356007142950",  # trop court
        "abcdefghijklm",  # non numérique
    ],
)
def test_invalid_ean13_values(ean13_field: EAN13Field, value: str) -> None:
    with pytest.raises(ValidationError):
        ean13_field.clean(value, None)
