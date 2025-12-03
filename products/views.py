import json
from typing import TYPE_CHECKING
from typing import Any

from django.urls import reverse_lazy
from vanilla import CreateView
from vanilla import DeleteView
from vanilla import ListView
from vanilla import UpdateView

from .forms import ProductForm
from .models import IngredientRef
from .models import Product
from .openfoodfacts.schema import OFFProductSchema
from .openfoodfacts.schema import ProductFormSchema
from .openfoodfacts.schema import product_schema_to_form_data
from .openfoodfacts.utils import build_ingredient_json_from_schema
from .openfoodfacts.utils import fetch_product
from .openfoodfacts.utils import get_schema_from_ingredients

if TYPE_CHECKING:
    from products.openfoodfacts.schema import OFFIngredientsSchema


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
        extra_data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> form_class:
        barcode: str | None = self.request.GET.get("barcode")
        initial = {}
        if barcode:
            product: OFFProductSchema = fetch_product(barcode)
            product_form: ProductFormSchema = product_schema_to_form_data(product)

            # not sure here if I should do : product_form.dict(exclude_none=True)
            initial.update(product_form.dict())  # pyright: ignore[reportUnknownMemberType]
            extra_data = {"fetched_image_url": product_form.image_url}

            # Add ingradients in extra_data
            extra_data["ingredients"] = product.ingredients

            if product.ingredients:
                # Preload all reference ingredient names once (single DB query)
                reference_names = {
                    name.lower()
                    for name in IngredientRef.objects.values_list("name", flat=True)
                }

                # Build the final JSON-ready list
                extra_data["ingredients_json"] = json.dumps(
                    [
                        build_ingredient_json_from_schema(ingredient, reference_names)
                        for ingredient in product.ingredients
                    ]
                )

        return self.form_class(
            data=data,
            files=files,
            initial=initial,
            extra_data=extra_data,
            **kwargs,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        context["macronutrients_api_url"] = reverse_lazy(
            "api-1.0.0:get_macronutrients_form_data"
        )
        return context


class ProductEditView(UpdateView):
    model = Product
    form_class = ProductForm
    success_url = reverse_lazy("list_products")

    def get_form(
        self,
        data=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        files=None,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        extra_data: dict[str, Any] | None = None,
        **kwargs: Any,  # https://adamj.eu/tech/2021/05/11/python-type-hints-args-and-kwargs/
    ) -> form_class:
        reset: bool = self.request.GET.get("reset") == "1"
        initial = {}

        product_instance: Product | None = kwargs.get("instance")

        if product_instance is None:
            msg = "Product instance is required to edit a product."
            raise ValueError(msg)

        barcode: str = product_instance.barcode

        if barcode and reset:
            product: OFFProductSchema = fetch_product(barcode)
            product_form: ProductFormSchema = product_schema_to_form_data(product)

            # not sure here if I should do : product_form.dict(exclude_none=True)
            initial.update(product_form.dict())  # pyright: ignore[reportUnknownMemberType]
            extra_data = {"fetched_image_url": product_form.image_url}

            # Add ingradients in extra_data
            extra_data["ingredients"] = product.ingredients

            if product.ingredients:
                # Preload all reference ingredient names once (single DB query)
                reference_names = {
                    name.lower()
                    for name in IngredientRef.objects.values_list("name", flat=True)
                }

                # Build the final JSON-ready list
                extra_data["ingredients_json"] = json.dumps(
                    [
                        build_ingredient_json_from_schema(ingredient, reference_names)
                        for ingredient in product.ingredients
                    ]
                )

        else:
            if extra_data is None:
                extra_data = {}
            ingredients: list[OFFIngredientsSchema] = get_schema_from_ingredients(
                product=product_instance
            )
            extra_data["ingredients"] = ingredients
            extra_data["ingredients_json"] = json.dumps(
                [ingredient.model_dump(by_alias=False) for ingredient in ingredients]
            )

        return self.form_class(
            data=data,
            files=files,
            initial=initial,
            extra_data=extra_data,
            **kwargs,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        context["macronutrients_api_url"] = reverse_lazy(
            "api-1.0.0:get_macronutrients_form_data"
        )
        return context


class ProductDeleteView(DeleteView):
    model = Product
    success_url = reverse_lazy("list_products")
