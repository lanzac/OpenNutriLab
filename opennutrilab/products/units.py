from typing import Final

from django.db import models
from quantityfield.units import ureg


# Vitamin units, with pint's abbreviated spelling ("mg", "µg") as both the
# stored value and the human-readable label: CharField choices need a label,
# and QuantityField's own unit_choices do not provide a readable one.
# https://pint.readthedocs.io/en/stable/user/formatting.html
class VitaminUnitChoices(models.TextChoices):
    MG = f"{ureg.mg:~P}", f"{ureg.mg:~P}"
    UG = f"{ureg.ug:~P}", f"{ureg.ug:~P}"


DEFAULT_VITAMIN_UNIT: Final[str] = VitaminUnitChoices.MG.value
# (value, label) pairs, as a model field's `choices` expects.
VITAMIN_UNIT_CHOICES = VitaminUnitChoices.choices
