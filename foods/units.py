from quantityfield.units import ureg
from django.db import models
from typing import Final


# Default Pint units definition file
# https://github.com/hgrecco/pint/blob/master/pint/default_en.txt
DEFAULT_ENERGY_UNIT: Final = f"{ureg.kJ:~P}" 
ENERGY_UNIT_CHOICES_VALUES = [DEFAULT_ENERGY_UNIT, f"{ureg.kcal:~P}"] 



# This class is used to define the choices for vitamin units with human-readable representations.
# Huan-readable representations are mandatory for the CharField choices of default_unit_in_form 
# And used as well in init_nutrients.py to create the Vitamin model instances.
class VitaminUnitChoices(models.TextChoices):
    # Value to set to the model field and human-readable representation
    # https://pint.readthedocs.io/en/stable/user/formatting.html
    MG = f"{ureg.mg:~P}", f"{ureg.mg:~P}"
    UG = f"{ureg.ug:~P}", f"{ureg.ug:~P}"
    
    # Those funcs of CharType are usefull : https://gitkraken.dev/link/dnNjb2RlOi8vZWFtb2Rpby5naXRsZW5zL2xpbmsvci9kZDcyYTZmN2U4MDA0MzE3Njk3ODViNzc5MTcyZTc1YjY5ZTJiZDZjL2YvLnZlbnYvbGliL3B5dGhvbjMuMTMvc2l0ZS1wYWNrYWdlcy9kamFuZ28vZGIvbW9kZWxzL2VudW1zLnB5P3VybD1odHRwcyUzQSUyRiUyRmdpdGh1Yi5jb20lMkZsYW56YWMlMkZPcGVuTnV0cmlhLmdpdCZsaW5lcz02Mi03OA%3D%3D?origin=gitlens
    # -> choices, labels, values
    

DEFAULT_MACRONUTRIENT_UNIT: Final[str] = f"{ureg.g:~P}"

DEFAULT_VITAMIN_UNIT: Final[str] = VitaminUnitChoices.MG.value
VITAMIN_UNIT_CHOICES = VitaminUnitChoices.choices # value (choice value) + label (human-readable)
VITAMIN_UNIT_CHOICES_VALUES = VitaminUnitChoices.values # only values (choice value)
