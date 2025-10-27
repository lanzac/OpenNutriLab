import io

import requests
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.urls import reverse_lazy
from django.utils.datastructures import MultiValueDict
from vanilla import CreateView
from vanilla import DeleteView
from vanilla import ListView
from vanilla import UpdateView

from .forms import FoodForm
from .models import Food
from .off_utils import fetch_product_data
from .schema import ProductFormSchema
from .schema import ProductSchema
from .schema import product_schema_to_form_data


class FoodListView(ListView):
    model = Food


class FoodCreateView(CreateView):
    model = Food
    form_class = FoodForm
    success_url = reverse_lazy("list_foods")

    def get_form(
        self,
        data=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        files=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        extra_data: dict[str, str | None] | None = None,
        **kwargs,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    ):
        barcode: str | None = self.request.GET.get("barcode")
        initial = {}
        if barcode:
            product: ProductSchema = fetch_product_data(barcode, use_local=False)
            product_form: ProductFormSchema = product_schema_to_form_data(product)

            initial.update(product_form.dict())  # pyright: ignore[reportUnknownMemberType]
            extra_data = {"fetched_image_url": product_form.image_url}

        # This condition is only True when saving a new product
        # Otherwise is just GET request for form files is None
        if isinstance(files, MultiValueDict):
            # First step: fetch image from URL
            fetched_image_url: str | None = extra_data.get("fetched_image_url", "")  # pyright: ignore[reportOptionalMemberAccess]

            if fetched_image_url:
                resp = requests.get(fetched_image_url, timeout=10)
                resp.raise_for_status()  # Optional: check HTTP status

                filename = f"{barcode}.jpg"

                if default_storage.exists(f"image/products/{filename}"):
                    default_storage.delete(f"image/products/{filename}")

                image_file = InMemoryUploadedFile(
                    file=io.BytesIO(resp.content),
                    field_name="image",
                    name=filename,
                    content_type="image/jpeg",
                    size=len(resp.content),
                    charset=None,
                )
                files.setlist(key="image", list_=[image_file])  # pyright: ignore[reportUnknownMemberType]

        return self.form_class(
            data=data,
            files=files,
            initial=initial,
            extra_data=extra_data,
            **kwargs,  # pyright: ignore[reportUnknownArgumentType]
        )


class FoodEditView(UpdateView):
    model = Food
    form_class = FoodForm
    success_url = reverse_lazy("list_foods")


class FoodDeleteView(DeleteView):
    model = Food
    success_url = reverse_lazy("list_foods")
