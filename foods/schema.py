from typing import Optional, ClassVar
from ninja import Schema, Field, File
from django.db import models
from django import forms
from ninja.files import UploadedFile
from quantityfield.fields import QuantityField
from .models import Macronutrient, FoodMacronutrient



# Fonction générique pour récupérer le title d'une annotation d'un schéma Pydantic/Ninja
def get_schema_title(schema_cls, field_name: str) -> str:
    """
    Retourne le titre (title) défini dans le model_json_schema pour un champ donné d'un schéma.
    Si aucun titre n'est défini, retourne le nom du champ.
    """
    props = schema_cls.model_json_schema().get("properties", {})
    return props.get(field_name, {}).get("title", field_name)

def make_annot_class(*fields, field_prefix: str = ""):
    class _Annot:
        pass
    for f in fields:
        setattr(_Annot, f, f"{field_prefix}_{f}" if field_prefix else f)
    return _Annot


class AnnotatedSchema(Schema):
    annot: ClassVar = None
    field_category: ClassVar[str] = ''
    related_model_class: ClassVar[models.Model] = None
    through_model_class: ClassVar[models.Model] = None
    
    @classmethod
    def get_formfield(cls) -> forms.Field:
        """Retourne un form field basé sur le champ 'amount' de la table de jointure."""
        return cls.through_model_class._meta.get_field('amount').formfield(required=False)
    
    @classmethod
    def get_form_field_name(cls, schema_field: str) -> str:
        """
        Retourne le nom du champ du formulaire pour un champ du schéma et la catégorie.
        Ex: cls.field_category='macronutrients', schema_field='fat' => 'macronutrients_fat'
        """
        if cls.field_category:
            return f"{cls.field_category}_{schema_field}"
        return schema_field


class MacronutrientsSchema(AnnotatedSchema):
    fat: Optional[float] = None
    saturated_fat: Optional[float] = None
    carbohydrates: Optional[float] = None
    sugars: Optional[float] = None
    fiber: Optional[float] = None
    proteins: Optional[float] = None

    annot: ClassVar = make_annot_class(
        "fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins"
    )
    field_category: ClassVar[str] = 'macronutrients'
    related_model_class: ClassVar[models.Model] = Macronutrient
    through_model_class: ClassVar[models.Model] = FoodMacronutrient
class ProductSchema(AnnotatedSchema):
    barcode: str
    name: str
    image_url: Optional[str] = None
    description: Optional[str] = None
    energy: Optional[int] = None
    macronutrients: MacronutrientsSchema
    
    annot: ClassVar = make_annot_class(
        "name", "image_url", "description", "energy", "macronutrients"
    )

class ProductFormSchema(Schema):
    barcode: str = Field(..., alias="barcode")
    name: str = Field(..., alias="name")
    image_url: str = Field(None, alias="image_url")
    description: str = Field(None, alias="description")
    energy: int = Field(None, alias="energy")
    macronutrients_fat: float = Field(None, alias="macronutrients.fat")
    macronutrients_saturated_fat: float = Field(None, alias="macronutrients.saturated_fat")
    macronutrients_carbohydrates: float = Field(None, alias="macronutrients.carbohydrates")
    macronutrients_sugars: float = Field(None, alias="macronutrients.sugars")
    macronutrients_fiber: float = Field(None, alias="macronutrients.fiber")
    macronutrients_proteins: float = Field(None, alias="macronutrients.proteins")
    
    
def product_schema_to_form_data(product: ProductSchema) -> ProductFormSchema:
    return ProductFormSchema.model_validate(product, by_alias=True)

