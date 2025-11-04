from django.http import HttpRequest
from django.http import JsonResponse
from django.urls import reverse_lazy
from vanilla import CreateView
from vanilla import DeleteView
from vanilla import ListView
from vanilla import UpdateView
from vanilla import View

from .forms import ProductForm
from .models import Product
from .off_utils import fetch_product_data
from .schema import ProductFormSchema
from .schema import ProductSchema
from .schema import product_schema_to_form_data


class ProductListView(ListView):
    model = Product


class ProductCreateView(CreateView):
    model = Product
    form_class = ProductForm
    success_url = reverse_lazy("list_products")

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
            product: ProductSchema = fetch_product_data(barcode)
            product_form: ProductFormSchema = product_schema_to_form_data(product)

            # not sure here if I should do : product_form.dict(exclude_none=True)
            initial.update(product_form.dict())  # pyright: ignore[reportUnknownMemberType]
            extra_data = {"fetched_image_url": product_form.image_url}

        return self.form_class(
            data=data,
            files=files,
            initial=initial,
            extra_data=extra_data,
            **kwargs,  # pyright: ignore[reportUnknownArgumentType]
        )


class ProductEditView(UpdateView):
    model = Product
    form_class = ProductForm
    success_url = reverse_lazy("list_products")


class ProductDeleteView(DeleteView):
    model = Product
    success_url = reverse_lazy("list_products")


class ProductPlotDataView(View):
    def get(self, request: HttpRequest) -> JsonResponse:
        try:
            fat = float(request.GET.get("macronutrients_fat_0", 0))
            saturated_fat = float(request.GET.get("macronutrients_saturated_fat_0", 0))
            carbohydrates = float(request.GET.get("macronutrients_carbohydrates_0", 0))
            sugars = float(request.GET.get("macronutrients_sugars_0", 0))
            fiber = float(request.GET.get("macronutrients_fiber_0", 0))
            proteins = float(request.GET.get("macronutrients_proteins_0", 0))
        except ValueError:
            return JsonResponse({"error": "invalid input"}, status=400)

        return JsonResponse(
            {
                "fat": fat,
                "saturated_fat": saturated_fat,
                "carbohydrates": carbohydrates,
                "sugars": sugars,
                "fiber": fiber,
                "proteins": proteins,
            }
        )
