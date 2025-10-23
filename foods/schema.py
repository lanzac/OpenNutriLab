from typing import ClassVar

from django import forms
from django.db import models
from ninja import Field
from ninja import Schema

from .models import FoodMacronutrient
from .models import Macronutrient


# Fonction générique pour récupérer le title d'une annotation d'un schéma Pydantic/Ninja
def get_schema_title(schema_cls, field_name: str) -> str:
    """
    Retourne le titre (title) défini dans le model_json_schema pour un champ donné d'un schéma.
    Si aucun titre n'est défini, retourne le nom du champ.
    """  # noqa: E501
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
    field_category: ClassVar[str] = ""
    related_model_class: ClassVar[models.Model] = None
    through_model_class: ClassVar[models.Model] = None

    @classmethod
    def get_formfield(cls) -> forms.Field:
        """Retourne un form field basé sur le champ 'amount' de la table de jointure."""
        return cls.through_model_class._meta.get_field("amount").formfield(  # noqa: SLF001
            required=False,
        )

    @classmethod
    def get_form_field_name(cls, schema_field: str) -> str:
        """
        Retourne le nom du champ du formulaire pour un champ du schéma et la catégorie.
        Ex: cls.field_category='macronutrients', schema_field='fat' => 'macronutrients_fat'
        """  # noqa: E501
        if cls.field_category:
            return f"{cls.field_category}_{schema_field}"
        return schema_field


class MacronutrientsSchema(AnnotatedSchema):
    fat: float | None = None
    saturated_fat: float | None = None
    carbohydrates: float | None = None
    sugars: float | None = None
    fiber: float | None = None
    proteins: float | None = None

    annot: ClassVar = make_annot_class(
        "fat",
        "saturated_fat",
        "carbohydrates",
        "sugars",
        "fiber",
        "proteins",
    )
    field_category: ClassVar[str] = "macronutrients"
    related_model_class: ClassVar[models.Model] = Macronutrient
    through_model_class: ClassVar[models.Model] = FoodMacronutrient


class ProductSchema(AnnotatedSchema):
    barcode: str
    name: str
    image_url: str | None = None
    description: str | None = None
    energy: int | None = None
    macronutrients: MacronutrientsSchema

    annot: ClassVar = make_annot_class(
        "name",
        "image_url",
        "description",
        "energy",
        "macronutrients",
    )


class ProductFormSchema(Schema):
    barcode: str = Field(..., alias="barcode")
    name: str = Field(..., alias="name")
    image_url: str = Field(None, alias="image_url")
    description: str = Field(None, alias="description")
    energy: int = Field(None, alias="energy")
    macronutrients_fat: float = Field(None, alias="macronutrients.fat")
    macronutrients_saturated_fat: float = Field(
        None,
        alias="macronutrients.saturated_fat",
    )
    macronutrients_carbohydrates: float = Field(
        None,
        alias="macronutrients.carbohydrates",
    )
    macronutrients_sugars: float = Field(None, alias="macronutrients.sugars")
    macronutrients_fiber: float = Field(None, alias="macronutrients.fiber")
    macronutrients_proteins: float = Field(None, alias="macronutrients.proteins")


def product_schema_to_form_data(product: ProductSchema) -> ProductFormSchema:
    return ProductFormSchema.model_validate(product, by_alias=True)
