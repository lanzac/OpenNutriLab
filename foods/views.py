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
from .schema import ProductSchema, ProductFormSchema, product_schema_to_form_data

from django.core.files.uploadedfile import InMemoryUploadedFile
import mimetypes
import os
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.datastructures import MultiValueDict
from django.conf import settings
import uuid

def get_views_for_model(new_model: ModelBase, new_model_form: ModelForm):

    reverse_url = reverse_lazy("list_" + new_model.__name__.lower() + "s")

    class ModelListView(ListView):
        model = new_model

    class ModelCreateView(CreateView):
        model = new_model
        form_class = new_model_form
        success_url = reverse_url
        
        
        def get(self, request, *args, **kwargs):
            barcode = request.GET.get("barcode")
            refresh = request.GET.get("refresh_data") == "1"

            if barcode and refresh:
                try:
                    product = fetch_product_data(barcode, use_local=True)
                    product_form: ProductFormSchema = product_schema_to_form_data(product)
                    
                    # Fetch image
                    if product_form.image_url:
                        image_path = fetch_image_to_tempfile(product_form.image_url, barcode=barcode)
                        self.request.session['fetched_image_path'] = image_path
                    
                    
                    request.session["prefill_data"] = product_form.dict()
                except Exception as e:
                    messages.warning(request, f"Erreur API : {e}")

                # Rediriger vers l'URL sans `refresh_data=1`
                base_url = reverse("create_food")
                return redirect(f"{base_url}?barcode={barcode}")

            return super().get(request, *args, **kwargs)
        
        def get_form(self, data=None, files=None, **kwargs):
            initial = {}

            barcode = self.request.GET.get("barcode")
            refresh_data = self.request.GET.get("refresh_data")

            if barcode and not refresh_data:  # évite le double fetch
                prefill = self.request.session.pop("prefill_data", None)
                if prefill:
                    initial.update(prefill)

                
                # This condition is only True when saving a new product
                # Otherwise is just GET request for form files is None
                if isinstance(files, MultiValueDict):
                    # fetched_image = self.request.session.pop("fetched_image", None)
                    # if fetched_image and files:
                    #     files.setlist("image", [fetched_image])
                    
                    image_path = self.request.session.get("fetched_image_path")
                    if image_path and os.path.exists(image_path):
                        
                        check_image_path = os.path.join(settings.MEDIA_ROOT, "images/products", os.path.basename(image_path))
                        if os.path.exists(check_image_path):
                            os.remove(check_image_path)
                        
                        from django.core.files.uploadedfile import SimpleUploadedFile
                        with open(image_path, 'rb') as f:
                            uploaded = SimpleUploadedFile(
                                name=os.path.basename(image_path),
                                content=f.read(),
                                content_type="image/jpeg"
                            )
                            files.setlist("image", [uploaded])
                    


            return self.form_class(data=data, files=files, initial=initial, **kwargs)
        
        def form_valid(self, form):
            self.request.session.pop("prefill_data", None)
            
            # Suppression du fichier temporaire s'il existe
            image_path = self.request.session.pop("fetched_image_path", None)
            if image_path and os.path.exists(image_path):
                os.remove(image_path)
            
            
            return super().form_valid(form)

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
        # Utilise BytesIO pour le contenu binaire
        from io import BytesIO
        from django.core.files.uploadedfile import InMemoryUploadedFile
         
        return InMemoryUploadedFile(
            file=BytesIO(response.content),
            field_name='image',
            name=f'image{extension}',
            content_type=content_type,
            size=len(response.content),
            charset=None
        )
    raise ValueError("Could not fetch image from URL")

def fetch_image_to_tempfile(image_url, barcode=None):
    response = requests.get(image_url)
    response.raise_for_status()

    # Déterminer l'extension via le type MIME
    content_type = response.headers.get('Content-Type', 'application/octet-stream')
    extension = mimetypes.guess_extension(content_type.split(';')[0].strip())
    if not extension:
        extension = '.jpg'  # fallback

    # Créer un nom de fichier
    base_name = f"{barcode}" if barcode else str(uuid.uuid4())
    filename = f"{base_name}{extension}"
    

    # Dossier temporaire sous MEDIA_ROOT/tmp
    temp_dir = os.path.join(settings.MEDIA_ROOT, "tmp")
    os.makedirs(temp_dir, exist_ok=True)

    file_path = os.path.join(temp_dir, filename)
    
    # Écriture du fichier
    with open(file_path, 'wb') as f:
        f.write(response.content)

    return file_path  # chemin absolu


