# products/signals.py
from typing import Any

from django.db.models import Model
from django.db.models.signals import m2m_changed
from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Additive
from .models import AdditiveNutrient
from .models import Ingredient
from .models import Nutrient
from .models import NutrientComponent
from .models import Preparation
from .models import Product
from .models import ProductNutrient
from .models import ReferenceIngredient
from .models import SourceFood
from .models import SourceFoodNutrient
from .services.stored_estimates import mark_stale


@receiver(post_delete, sender=Product)
def delete_product_image(instance: Product, **kwargs):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType, reportUnusedParameter]
    """Delete image file from storage when Product instance is deleted."""
    if instance.image:
        instance.image.delete(save=False)


# ----------------------------------------------------------------------------
# What makes a kept estimate stale (see services.stored_estimates)
# ----------------------------------------------------------------------------
def _product_changed(instance: Ingredient | ProductNutrient, **_kwargs: Any) -> None:
    # The id, not the product: when the product itself is being deleted, its
    # ingredients go first, and reading it back would fail.
    mark_stale(instance.product_id)


def _composition_changed(**_kwargs: Any) -> None:
    mark_stale()


for _sender in (Ingredient, ProductNutrient):
    post_save.connect(_product_changed, sender=_sender, weak=False)
    post_delete.connect(_product_changed, sender=_sender, weak=False)

# Whatever a composition is made of.
_COMPOSITION: tuple[type[Model], ...] = (
    ReferenceIngredient,
    Preparation,
    Additive,
    AdditiveNutrient,
    SourceFood,
    SourceFoodNutrient,
    Nutrient,
    NutrientComponent,
)
for _sender in _COMPOSITION:
    post_save.connect(_composition_changed, sender=_sender, weak=False)
    post_delete.connect(_composition_changed, sender=_sender, weak=False)
for _through in (
    ReferenceIngredient.source_foods.through,
    Preparation.components.through,
    Preparation.preparation_components.through,
    Preparation.source_foods.through,
    Additive.source_foods.through,
):
    m2m_changed.connect(_composition_changed, sender=_through, weak=False)
