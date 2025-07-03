from django.shortcuts import render
from vanilla import ListView, DetailView, CreateView, UpdateView, DeleteView, GenericModelView
from django.db.models.base import ModelBase
from django.urls import reverse_lazy
from django.forms import ModelForm
from .models import Food, Vitamin
from .forms import FoodForm
from django.http import JsonResponse
import requests
from typing import Any, Dict, Optional

from .off_utils import fetch_product_data
from .schema import ProductSchema, MacronutrientsSchema

from django.core.files.uploadedfile import InMemoryUploadedFile
from io import BytesIO
import mimetypes
import os

def get_views_for_model(new_model: ModelBase, new_model_form: ModelForm):

    reverse_url = reverse_lazy("list_" + new_model.__name__.lower() + "s")

    class ModelListView(ListView):
        model = new_model

    class ModelCreateView(CreateView):
        model = new_model
        form_class = new_model_form
        success_url = reverse_url

        # def get_context_data(self, **kwargs):
        #     context = super().get_context_data(**kwargs)
        #     context['vitamins'] = Vitamin.objects.all()
        #     return context
        
        def get_form(self, data=None, files=None, **kwargs):
            # 👇 Initialiser les données
            initial = {}
            product_image_url = None

            barcode = self.request.GET.get('barcode')
            if barcode:
                initial['barcode'] = barcode
                try:
                    product = fetch_product_data(barcode)
                    initial.update(product_schema_to_form_data(product))
                    product_image_url = getattr(product, 'image_url', None)
                    print("Préremplissage réussi :", initial)
                except Exception as e:
                    print("Erreur lors du préremplissage :", e)

            # 👇 Passe les données initiales à ton formulaire
            form = self.form_class(data=data, files=files, initial=initial)
            # Ajoute l'URL de l'image distante dans l'objet form pour le template
            form.product_image_url = product_image_url
            return form

    class ModelEditView(UpdateView):
        model = new_model
        form_class = new_model_form
        success_url = reverse_url

        # def get_context_data(self, **kwargs):
        #     context = super().get_context_data(**kwargs)
        #     context['vitamins'] = Vitamin.objects.all()
        #     return context

    class ModelDeleteView(DeleteView):
        model = new_model
        success_url = reverse_url

    return ModelListView, ModelCreateView, ModelEditView, ModelDeleteView

# Générer les vues pour chaque modèle
FoodListView, FoodCreateView, FoodEditView, FoodDeleteView = get_views_for_model(
    Food,
    FoodForm
)


def fetch_image(url: str) -> InMemoryUploadedFile:
    response = requests.get(url)
    if response.status_code == 200:
        content_type = response.headers.get('Content-Type', 'application/octet-stream')
        extension = mimetypes.guess_extension(content_type.split(';')[0].strip())
        if not extension:
            extension = '.jpg'  # Default to jpg if unknown type

        image_file = InMemoryUploadedFile(
            file=BytesIO(response.content),
            field_name='image',
            name=f'image{extension}',
            content_type=content_type,
            size=len(response.content),
            charset=None
        )
        return image_file
    raise ValueError("Could not fetch image from URL")


def product_schema_to_form_data(product: ProductSchema) -> dict:
    form_data = {
        "name": product.name,
        "description": product.description,
        "energy": product.energy,
    }
    
    if product.image_url:
        try:
            image = fetch_image()
            form_data["image"] = image
        except Exception as e:
            print(f"Erreur lors de la récupération de l'image : {e}")
    
    for macro_name, amount in product.macronutrients.dict().items():
        if amount is not None:
            form_data[f"{MacronutrientsSchema.field_category}_{macro_name}"] = amount
    return form_data
