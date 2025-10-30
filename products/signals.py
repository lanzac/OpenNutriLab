# products/signals.py
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Product


@receiver(post_delete, sender=Product)
def delete_product_image(instance: Product, **kwargs):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType, reportUnusedParameter]
    """Delete image file from storage when Product instance is deleted."""
    if instance.image:
        instance.image.delete(save=False)
