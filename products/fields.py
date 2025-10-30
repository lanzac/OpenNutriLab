from typing import final

from django.core.exceptions import ValidationError
from django.db import models


# EuropeanArticleNumber13
def validate_ean13(value: str) -> None:
    ean13_len = 13
    if len(value) != ean13_len or not value.isdigit():
        raise ValidationError(message="EAN-13 must be 13 digits.")
    checksum = (
        10
        - sum(
            (int(d) if i % 2 == 0 else int(d) * 3)
            for i, d in enumerate[str](value[:12])
        )
        % 10
    ) % 10
    if checksum != int(value[-1]):
        raise ValidationError(message="Invalid EAN-13 checksum.")


@final
class EAN13Field(models.CharField[str]):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.max_length = 13
        self.validators.append(validate_ean13)
