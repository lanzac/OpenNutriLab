from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from foods.models import Food


@pytest.mark.django_db
def test_delete_food_image_signal():
    """Test that the Food post_delete signal deletes the image file."""

    uploaded_file = SimpleUploadedFile(
        name="test.jpg", content=b"fake image bytes", content_type="image/jpeg"
    )

    # Patch save to avoid PermissionError during creation
    with (
        patch("django.core.files.storage.FileSystemStorage.save") as mock_save,
        patch("django.core.files.storage.FileSystemStorage.delete") as mock_delete,
    ):
        # save should just return the file path
        mock_save.return_value = "images/products/test.jpg"

        food = Food.objects.create(barcode="123456", name="Apple", image=uploaded_file)

        # Delete the instance (triggers post_delete signal)
        food.delete()

        # Verify that delete was called on the storage
        mock_delete.assert_called_once_with("images/products/test.jpg")
