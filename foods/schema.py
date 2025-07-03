from typing import Optional, ClassVar
from ninja import Schema
from django.db import models
from foods.models import Macronutrient


MACRONUTRIENT_VALUE_TYPE = float


# Fonction générique pour récupérer le title d'une annotation d'un schéma Pydantic/Ninja
def get_schema_title(schema_cls: Schema, field_name: str) -> str:
    """
    Retourne le titre (title) défini dans le model_json_schema pour un champ donné d'un schéma.
    Si aucun titre n'est défini, retourne le nom du champ.
    """
    props = schema_cls.model_json_schema().get("properties", {})
    return props.get(field_name, {}).get("title", field_name)

def make_annot_class(*fields):
    class _Annot:
        pass
    for f in fields:
        setattr(_Annot, f, f)
    return _Annot


class AnnotatedSchema(Schema):
    annot: ClassVar = None
    field_category: ClassVar[str] = ''
    related_model_class: ClassVar[models.Model] = None


class MacronutrientsSchema(AnnotatedSchema):
    fat: Optional[MACRONUTRIENT_VALUE_TYPE] = None
    saturated_fat: Optional[MACRONUTRIENT_VALUE_TYPE] = None
    carbohydrates: Optional[MACRONUTRIENT_VALUE_TYPE] = None
    sugars: Optional[MACRONUTRIENT_VALUE_TYPE] = None
    fiber: Optional[MACRONUTRIENT_VALUE_TYPE] = None
    proteins: Optional[MACRONUTRIENT_VALUE_TYPE] = None

    annot: ClassVar = make_annot_class(
        "fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins"
    )
    field_category: ClassVar[str] = 'macronutrients'
    related_model_class: ClassVar[models.Model] = Macronutrient
        
class ProductSchema(AnnotatedSchema):
    name: str
    image_url: Optional[str] = None
    description: Optional[str] = None
    energy: Optional[int] = None
    macronutrients: MacronutrientsSchema
    
    annot: ClassVar = make_annot_class(
        "name", "image_url", "description", "energy", "macronutrients"
    )
