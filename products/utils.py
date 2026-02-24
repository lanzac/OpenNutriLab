import io

import requests
from django.core.files.uploadedfile import InMemoryUploadedFile


def fetch_image_as_uploaded_file(
    image_url: str,
    filename: str,
    *,
    timeout: int = 10,
) -> InMemoryUploadedFile | None:
    """
    Download an image and return an InMemoryUploadedFile ready to assign to a model
    field. Caller must pass the desired filename (e.g. f"{barcode}.jpg").
    """
    if not image_url:
        return None

    resp = requests.get(image_url, timeout=timeout)
    resp.raise_for_status()
    content = resp.content
    file_io = io.BytesIO(content)

    return InMemoryUploadedFile(
        file=file_io,
        field_name="image",
        name=filename,
        content_type="image/jpeg",
        size=len(content),
        charset=None,
    )
