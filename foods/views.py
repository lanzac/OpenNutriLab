from django.shortcuts import render
from vanilla import ListView, DetailView, CreateView, UpdateView, DeleteView, GenericModelView
from django.db.models.base import ModelBase
from django.urls import reverse_lazy
from django.forms import ModelForm
from .models import Food, Vitamin
from .forms import FoodForm
from django.http import JsonResponse
import requests

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

    data = response.json()
    if data.get('status') != 1:
        return JsonResponse({'success': False, 'error': 'Product not found'})

    product = data.get('product', {})
    nutriments = product.get('nutriments', {})

    # 🔸 Exemple de correspondance avec ton modèle Django
    name = product.get('product_name') or ''
    image_url = product.get('image_small_url') or ''
    description = product.get('categories') or ''

    # 🔸 Extraction de l'énergie (en kJ / 100g)
    energy_kj = get_first(
        nutriments.get('energy-kj_100g'),
        nutriments.get('energy_100g'),
        nutriments.get('energy')
    )

    macronutrient_keys = {
        'fiber': ['fiber_100g', 'fiber', 'fiber_value'],
        'carbohydrates': ['carbohydrates_100g', 'carbohydrates', 'carbohydrates_value'],
        'sugars': ['sugars_100g', 'sugars', 'sugars_value'],
        'fat': ['fat_100g', 'fat', 'fat_value'],
        'saturated_fat': ['saturated-fat_100g', 'saturated-fat', 'saturated-fat_value'],
        'proteins': ['proteins_100g', 'proteins', 'proteins_value'],
    }

    macronutrients = {
        key: get_first(*(nutriments.get(k) for k in keys))
        for key, keys in macronutrient_keys.items()
    }


    return JsonResponse({
        'success': True,
        'name': name,
        'image_url': image_url,
        'description': description,
        'energy': energy_kj,
        'macronutrients': macronutrients,
    })
