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

# Mapping général pour tous les champs à extraire (nom, image, description, nutriments...)
PRODUCT_LABELS = {
    'name': (['product_name'], str),
    'image_url': (['image_small_url'], str),
    'description': (['categories'], str),
    'energy': (['energy-kj_100g', 'energy_100g', 'energy_value'], int),
    'macronutrients': {
        'fiber': (['fiber_100g', 'fiber', 'fiber_value'], float),
        'carbohydrates': (['carbohydrates_100g', 'carbohydrates', 'carbohydrates_value'], float),
        'sugars': (['sugars_100g', 'sugars', 'sugars_value'], float),
        'fat': (['fat_100g', 'fat', 'fat_value'], float),
        'saturated_fat': (['saturated-fat_100g', 'saturated-fat', 'saturated-fat_value'], float),
        'proteins': (['proteins_100g', 'proteins', 'proteins_value'], float),
    }
}

def extract_typed_fields(d: dict, fields: dict) -> dict:
    """
    Extrait récursivement les valeurs du dict d selon la structure de fields,
    qui associe à chaque champ une liste de labels et un type cible.
    Exemple d'utilisation :
        merged_data = extract_typed_fields(nutrients, NUTRIENT_LABELS)
        energy_kj = merged_data['energy']
        macronutrients = merged_data['macronutrients']
    """
    result = {}
    for key, value in fields.items():
        if isinstance(value, dict):
            result[key] = extract_typed_fields(d, value)
        else:
            labels, typ = value
            raw = get_first_key_found(d, labels)
            try:
                result[key] = typ(raw)
            except (TypeError, ValueError):
                result[key] = typ()  # valeur par défaut du type
    return result

def get_first_key_found(d: dict, keys, default=0):
    """
    Retourne la première valeur trouvée dans le dict d pour la première clé présente dans keys.
    """
    for k in keys:
        value = d.get(k)
        if value not in (None, ''):
            return value
    return default

def get_views_for_model(new_model: ModelBase, new_model_form: ModelForm):

    reverse_url = reverse_lazy("list_" + new_model.__name__.lower() + "s")

    class ModelListView(ListView):
        model = new_model

    class ModelCreateView(CreateView):
        model = new_model
        form_class = new_model_form
        success_url = reverse_url

        def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            context['vitamins'] = Vitamin.objects.all()
            return context

    class ModelEditView(UpdateView):
        model = new_model
        form_class = new_model_form
        success_url = reverse_url

        def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            context['vitamins'] = Vitamin.objects.all()
            return context

    class ModelDeleteView(DeleteView):
        model = new_model
        success_url = reverse_url

    return ModelListView, ModelCreateView, ModelEditView, ModelDeleteView

# Générer les vues pour chaque modèle
FoodListView, FoodCreateView, FoodEditView, FoodDeleteView = get_views_for_model(
    Food,
    FoodForm
)


def get_first(*values):
    return next((v for v in values if v not in (None, '')), 0)

def fetch_food_info(request, barcode):
    url = f"https://world.openfoodfacts.net/api/v2/product/{barcode}.json"
    response = requests.get(url)

    if response.status_code != 200:
        return JsonResponse({'success': False, 'error': 'API error'})

    data: Dict[str, Any] = response.json()
    if data.get('status') != 1:
        return JsonResponse({'success': False, 'error': 'Product not found'})

    product: Dict[str, Any] = data.get('product', {})
    nutrients: Dict[str, Any] = product.get('nutriments', {})

    # Extraction généralisée
    merged_data = extract_typed_fields({**product, **nutrients}, PRODUCT_LABELS)

    # Ingredients --------------------------------------------------------------
    ingredients: Any = product.get('ingredients', '')

    return JsonResponse({
        'success': True,
        **merged_data,
    })
