from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from pytest_django.fixtures import SettingsWrapper

from opennutrilab.products.services.translation import translate
from opennutrilab.products.services.translation import translation_enabled

POST = "opennutrilab.products.services.translation.requests.post"


def answer(body: object = None, *, status_error: bool = False) -> MagicMock:
    response = MagicMock()
    response.json.return_value = body
    if status_error:
        response.raise_for_status.side_effect = requests.HTTPError("500")
    return response


@pytest.fixture
def server(settings: SettingsWrapper) -> SettingsWrapper:
    settings.TRANSLATION_URL = "http://translator:5000/"
    settings.TRANSLATION_API_KEY = ""
    settings.TRANSLATION_TIMEOUT = 7
    return settings


def test_nothing_is_asked_when_no_server_is_set(settings: SettingsWrapper):
    settings.TRANSLATION_URL = ""

    with patch(POST) as post:
        assert translate("oignon grillé") is None

    assert not translation_enabled()
    post.assert_not_called()


def test_the_name_is_posted_to_the_server_and_its_translation_returned(
    server: SettingsWrapper,
):
    with patch(POST, return_value=answer({"translatedText": "grilled onion"})) as post:
        found = translate("  oignon   grillé ")

    assert found == "grilled onion"
    post.assert_called_once_with(
        "http://translator:5000/translate",
        json={"q": "oignon grillé", "source": "fr", "target": "en", "format": "text"},
        timeout=7,
    )


def test_the_api_key_is_sent_when_there_is_one(server: SettingsWrapper):
    server.TRANSLATION_API_KEY = "secret"

    with patch(POST, return_value=answer({"translatedText": "onion"})) as post:
        translate("oignon")

    assert post.call_args.kwargs["json"]["api_key"] == "secret"


@pytest.mark.parametrize(
    ("original", "translated", "expected"),
    [
        # A name is written as the original is: no full stop, lower case.
        ("oignon grillé", "Grilled onion.", "grilled onion"),
        ("Oignon grillé", "Grilled onion", "Grilled onion"),
        # An acronym keeps its capitals.
        ("DHA", "DHA", "DHA"),
        ("dha pur", "DHA pure", "DHA pure"),
    ],
)
def test_the_translation_is_written_as_a_name(
    server: SettingsWrapper, original: str, translated: str, expected: str
):
    with patch(POST, return_value=answer({"translatedText": translated})):
        assert translate(original) == expected


@pytest.mark.parametrize(
    "response",
    [
        answer({"translatedText": ""}),
        answer({"translatedText": "  . "}),
        answer({"translatedText": 12}),
        answer({"error": "nope"}),
        answer(["not", "an", "object"]),
        answer({"translatedText": "x"}, status_error=True),
    ],
)
def test_an_answer_that_is_no_translation_gives_none(
    server: SettingsWrapper, response: MagicMock
):
    with patch(POST, return_value=response):
        assert translate("oignon") is None


@pytest.mark.parametrize("error", [requests.ConnectionError, requests.Timeout])
def test_a_server_that_does_not_answer_gives_none(
    server: SettingsWrapper, error: type[Exception]
):
    with patch(POST, side_effect=error("down")):
        assert translate("oignon") is None


def test_an_answer_that_is_not_json_gives_none(server: SettingsWrapper):
    response = answer()
    response.json.side_effect = requests.exceptions.JSONDecodeError("x", "", 0)

    with patch(POST, return_value=response):
        assert translate("oignon") is None
