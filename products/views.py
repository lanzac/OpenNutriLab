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
    from products.openfoodfacts.schema import OFFIngredientSchema


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
        initial: dict[str, Any] = {}
        if barcode:
            fetched_product: OFFProductSchema = fetch_product(query_barcode=barcode)
            initial, extra_data = prepare_product_form_data(
                fetched_product=fetched_product, extra_data=extra_data
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
        product_instance: Product | None = kwargs.get("instance")
        if product_instance is None:
            msg = "Product instance is required to edit a product."
            raise ValueError(msg)

        fetched_product: OFFProductSchema | None = None
        if reset:
            fetched_product = fetch_product(query_barcode=product_instance.barcode)

        initial, extra_data = prepare_product_form_data(
            product_instance=product_instance,
            fetched_product=fetched_product,
            extra_data=extra_data,
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


# Utilities


def prepare_product_form_data(
    product_instance: Product | None = None,
    fetched_product: OFFProductSchema | None = None,
    extra_data: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Prepare `initial` and `extra_data` for Product form.

    :param product_instance: Product from DB (for Edit)
    :param fetched_product: OFFProductSchema from API (for Create or Edit reset)
    :param reset: whether to force fetch_product even on Edit
    :param extra_data: existing extra_data dict
    :return: tuple(initial, extra_data)
    """
    initial: dict[str, Any] = {}
    extra_data = extra_data or {}

    # Use fetched_product if provided (Create or Edit reset)
    if fetched_product is not None:
        # convert to form schema
        product_form: ProductFormSchema = product_schema_to_form_data(fetched_product)
        initial.update(product_form.dict())
        extra_data["fetched_image_url"] = product_form.image_url

        # Ingredients from fetched_product
        extra_data["ingredients"] = fetched_product.ingredients
        if fetched_product.ingredients:
            reference_names = {
                name.lower()
                for name in IngredientRef.objects.values_list("name", flat=True)
            }
            extra_data["ingredients_json"] = json.dumps(
                [
                    build_ingredient_json_from_schema(ingredient, reference_names)
                    for ingredient in fetched_product.ingredients
                ]
            )
    elif product_instance is not None:
        # Edit normal (no reset) → ingredients from DB
        ingredients: list[OFFIngredientSchema] = get_schema_from_ingredients(
            product_instance
        )
        extra_data["ingredients"] = ingredients
        extra_data["ingredients_json"] = json.dumps(
            [ingredient.model_dump(by_alias=False) for ingredient in ingredients]
        )
    else:
        msg = "Either product_instance or fetched_product must be provided"
        raise ValueError(msg)

    return initial, extra_data
