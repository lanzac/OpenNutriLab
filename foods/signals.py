# foods/signals.py
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Food


@receiver(post_delete, sender=Food)
def delete_food_image(sender, instance, **kwargs):
    """Delete image file from storage when Food instance is deleted."""
    if instance.image:
        instance.image.delete(save=False)
