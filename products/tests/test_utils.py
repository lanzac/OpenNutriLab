from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import InMemoryUploadedFile

from products.utils import fetch_image_as_uploaded_file


def test_fetch_image_as_uploaded_file_success():
    fake_content = b"fake-image-bytes"
    filename = "test.jpg"
    image_url = "http://example.com/test.jpg"

    mock_response = Mock()
    mock_response.content = fake_content
    mock_response.raise_for_status = Mock()  # no HTTP error
    with patch("products.utils.requests.get", return_value=mock_response) as mock_get:
        uploaded_file: InMemoryUploadedFile | None = fetch_image_as_uploaded_file(
            image_url, filename
        )

    mock_get.assert_called_once_with(image_url, timeout=10)
    assert isinstance(uploaded_file, InMemoryUploadedFile)
    assert uploaded_file.name == filename
    assert uploaded_file.size == len(fake_content)
    assert uploaded_file.content_type == "image/jpeg"

    uploaded_file.file.seek(0)
    assert uploaded_file.file.read() == fake_content


def test_fetch_image_as_uploaded_file_none_for_empty_url():
    result: InMemoryUploadedFile | None = fetch_image_as_uploaded_file("", "test.jpg")
    assert result is None


def test_fetch_image_as_uploaded_file_raises_for_http_error():
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = Exception("HTTP Error")
    with (
        patch("products.utils.requests.get", return_value=mock_response),
        pytest.raises(Exception, match="HTTP Error"),
    ):
        fetch_image_as_uploaded_file("http://example.com/error.jpg", "error.jpg")
