from django.db import models
from django.core.exceptions import ValidationError

# EuropeanArticleNumber13
def validate_ean13(value):
    if len(value) != 13 or not value.isdigit():
        raise ValidationError("EAN-13 must be 13 digits.")
    checksum = (10 - sum((int(d) if i % 2 == 0 else int(d) * 3) for i, d in enumerate(value[:12])) % 10) % 10
    if checksum != int(value[-1]):
        raise ValidationError("Invalid EAN-13 checksum.")

class EAN13Field(models.CharField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 13)
        kwargs.setdefault("validators", [])
        kwargs["validators"].append(validate_ean13)
        super().__init__(*args, **kwargs)
