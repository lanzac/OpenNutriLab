from django.urls import reverse_lazy
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
            product: ProductSchema = fetch_product_data(barcode)
            product_form: ProductFormSchema = product_schema_to_form_data(product)

            initial.update(product_form.dict())  # pyright: ignore[reportUnknownMemberType]
            extra_data = {"fetched_image_url": product_form.image_url}

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
