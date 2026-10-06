"""
Machine translation of a short text, through a LibreTranslate-compatible server.

The only thing here that depends on which translator is used: a name goes in, its
translation comes out, and anything else (no server set, the server down, an
answer that is not one) is None. Nothing is written from what it says. It is
a proposal for a person to accept (see english_names), so a wrong or missing one
costs a click, not a wrong name in the database.

The server is a separate program that is called over HTTP (LibreTranslate, which
is AGPL-licensed, run apart; its `LT_LOAD_ONLY=en,fr` keeps it light). To use
another translator, replace `translate`.
"""

import logging
from typing import cast

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def translation_enabled() -> bool:
    return bool(settings.TRANSLATION_URL)


def translate(text: str, *, source: str = "fr", target: str = "en") -> str | None:
    """The translation of `text`, or None if it cannot be had."""
    text = " ".join(text.split())
    if not translation_enabled() or not text:
        return None
    payload = {"q": text, "source": source, "target": target, "format": "text"}
    if settings.TRANSLATION_API_KEY:
        payload["api_key"] = settings.TRANSLATION_API_KEY
    url = f"{settings.TRANSLATION_URL.rstrip('/')}/translate"
    try:
        response = requests.post(
            url, json=payload, timeout=settings.TRANSLATION_TIMEOUT
        )
        response.raise_for_status()
        body: object = response.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Could not translate %r: %s", text, e)
        return None
    translated = (
        cast("dict[str, object]", body).get("translatedText")
        if isinstance(body, dict)
        else None
    )
    if not isinstance(translated, str):
        logger.warning("The translator's answer for %r has no translation.", text)
        return None
    return _written_like(text, translated)


def _written_like(original: str, translated: str) -> str | None:
    """
    The translation as a name is written: no final full stop, and its first letter
    in the case of the original's ("oignon grillé" gives "grilled onion", not
    "Grilled onion."), unless it starts like an acronym ("DHA").
    """
    name = translated.strip().rstrip(".").strip()
    if not name:
        return None
    if original[0].islower() and name[0].isupper() and not name[1:2].isupper():
        name = name[0].lower() + name[1:]
    return name
