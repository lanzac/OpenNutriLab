import re
from collections.abc import Iterable
from decimal import Decimal
from decimal import InvalidOperation
from http import HTTPStatus
from typing import Any

import requests
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from pydantic import ValidationError

from opennutrilab.products.api.openfoodfacts.schemas import OFFProductAPIResponseSchema
from opennutrilab.products.api.openfoodfacts.schemas import OFFProductSchema
from opennutrilab.products.api.openfoodfacts.schemas import OFFSearchHitSchema
from opennutrilab.products.api.openfoodfacts.schemas import OFFWriteAnswerSchema
from opennutrilab.products.api.openfoodfacts.schemas import StatusEnum
from opennutrilab.products.api.schemas.inbound import IngredientInput
from opennutrilab.products.api.schemas.inbound import validate_off_image_url
from opennutrilab.products.fields import validate_ean13
from opennutrilab.products.models import Nutrient
from opennutrilab.products.models import Product
from opennutrilab.products.services.label_parser import LabelItem
from opennutrilab.products.services.label_parser import LabelWarning
from opennutrilab.products.services.label_parser import Span
from opennutrilab.products.services.label_parser import read_label
from opennutrilab.products.services.packages import read_package
from opennutrilab.products.services.servings import read_serving


class OFFError(Exception):
    """OpenFoodFacts could not give a usable answer for a barcode.

    Raised for an unreachable API, an upstream error status, or a response
    that does not parse. Callers turn it into whatever their layer speaks: a
    notice on the product form, an HTTP status in an API route.
    """


class OFFProductNotFoundError(OFFError):
    """OpenFoodFacts has no product for this barcode."""


# OpenFoodFacts rejects generic clients: without a User-Agent naming the
# application, the API answers 403 Forbidden. See
# https://openfoodfacts.github.io/openfoodfacts-server/api/#authentication
OFF_HEADERS = {
    "User-Agent": "OpenNutriLab/0.1.0 (https://github.com/lanzac/OpenNutriLab)",
}


def normalize_barcode(barcode: str) -> str:
    """
    Drop the leading zeros OFF adds when padding a short code to 13 digits.

    A 12-digit UPC-A queried as `322982079455` is stored as `0322982079455`,
    so the two spellings have to compare equal.
    """
    return barcode.strip().lstrip("0")


def fetch_from_off(
    query_barcode: str,
) -> OFFProductSchema:
    """
    Fetch product data from OpenFoodFacts API for a given barcode.
    """
    url = f"https://world.openfoodfacts.org/api/v3/product/{query_barcode}.json"

    try:
        response = requests.get(
            url,
            timeout=30,
            allow_redirects=True,
            headers=OFF_HEADERS,
        )
    except requests.RequestException as e:
        msg = f"External API unreachable: {e}"
        raise OFFError(msg) from e

    # OFF answers an unknown barcode with 404 *and* a well-formed failure body,
    # so the status line alone cannot tell "no such product" from a broken
    # gateway. Let 404 fall through to the body checks below, which turn
    # `status: failure` into a not-found; anything else is an upstream error.
    if response.status_code not in (HTTPStatus.OK, HTTPStatus.NOT_FOUND):
        msg = f"External API returned an error: {response.status_code} for url: {url}"
        raise OFFError(msg)

    # JSON parsing
    try:
        data = response.json()
    except ValueError as e:
        msg = f"Invalid JSON received from external API: {e}"
        raise OFFError(msg) from e

    # Validation Pydantic
    try:
        api_product_response = OFFProductAPIResponseSchema.model_validate(data)
    except ValidationError as e:
        msg = f"Invalid API response format for {query_barcode}: {e}"
        raise OFFError(msg) from e

    # API-level errors
    if api_product_response.status == StatusEnum.failure:
        msg = f"Product {query_barcode} not found."
        raise OFFProductNotFoundError(msg)

    # `success_with_warnings` is the ordinary answer for a short barcode: OFF
    # pads codes to 13 digits and reports the padding as a
    # `different_normalized_product_code` warning. Only errors are fatal.
    if api_product_response.status == StatusEnum.success_with_errors:
        raise OFFError(str(api_product_response.errors))

    product = api_product_response.product

    if product is None:
        msg = (
            f"API response for {query_barcode} indicated success "
            "but returned no product."
        )
        raise OFFError(msg)

    # OFF answering with another product means it has none for this barcode.
    if normalize_barcode(query_barcode) != normalize_barcode(product.barcode):
        msg = (
            f"Barcode mismatch: requested {query_barcode}, "
            f"but got {product.barcode} from OpenFoodFacts"
        )
        raise OFFProductNotFoundError(msg)

    return product


def off_write_configured() -> bool:
    """Whether an OpenFoodFacts account is set to send corrections with."""
    return bool(settings.OFF_USER_ID and settings.OFF_PASSWORD)


# A language code as OpenFoodFacts suffixes its fields with: "fr", "en", "haw".
_OFF_LANGUAGE = re.compile(r"[a-z]{2,3}")


def send_ingredients_text_to_off(barcode: str, text: str, language: str) -> bool:
    """
    Replace the ingredient list OpenFoodFacts has for a product by `text`.

    Public and signed with the configured account (see OFF_USER_ID): the caller
    decides who may. Only a product OpenFoodFacts already has is edited, since this
    would otherwise create one holding nothing but a list. Returns False, sending
    nothing, when its list already is `text`. Raises OFFError when nothing was
    sent: no account, a language that is not one, no such product, an answer that
    is not a success.
    """
    if not off_write_configured():
        msg = "No OpenFoodFacts account is configured."
        raise OFFError(msg)
    code = language.strip().lower()
    if not _OFF_LANGUAGE.fullmatch(code):
        msg = f"{language!r} is not a language OpenFoodFacts knows."
        raise OFFError(msg)
    text = text.strip()
    if not text:
        msg = "An empty list is not sent."
        raise OFFError(msg)

    current = fetch_from_off(query_barcode=barcode)
    if (current.ingredients_text or "").strip() == text:
        return False

    try:
        response = requests.post(
            settings.OFF_WRITE_URL,
            data={
                "code": barcode,
                "user_id": settings.OFF_USER_ID,
                "password": settings.OFF_PASSWORD,
                f"ingredients_text_{code}": text,
                "comment": "Ingredient list corrected from OpenNutriLab",
            },
            timeout=30,
            headers=OFF_HEADERS,
        )
    except requests.RequestException as e:
        msg = f"External API unreachable: {e}"
        raise OFFError(msg) from e
    if response.status_code != HTTPStatus.OK:
        msg = f"External API returned an error: {response.status_code}"
        raise OFFError(msg)
    try:
        answer = OFFWriteAnswerSchema.model_validate(response.json())
    except ValueError as e:
        # Not JSON, or not the shape of an answer: pydantic's error is a ValueError.
        msg = f"Invalid answer received from external API: {e}"
        raise OFFError(msg) from e
    # 1 is "saved"; a refused login or field comes back as 0 with the reason.
    if answer.status != 1:
        msg = f"OpenFoodFacts did not save the list: {answer.status_verbose}"
        raise OFFError(msg)
    return True


OFF_SEARCH_URL = "https://search.openfoodfacts.org/search"
# What a search of OpenFoodFacts is asked for, and how many of its products are kept.
OFF_SEARCH_FIELDS = "code,product_name,brands,quantity,image_small_url"
OFF_SEARCH_KEPT = 10


def off_product_url(barcode: str) -> str:
    """The page of a product on the OpenFoodFacts site."""
    return f"https://world.openfoodfacts.org/product/{barcode}"


def search_off(text: str) -> list[OFFSearchHitSchema]:
    """
    The products of OpenFoodFacts that a text (a name, a brand) finds, best first.

    Only those that can become a product here are kept: a barcode that is not a valid
    EAN-13 is refused by the form, so offering it would lead nowhere. Raises
    OFFError when OpenFoodFacts cannot be reached or does not make sense.
    """
    try:
        response = requests.get(
            OFF_SEARCH_URL,
            params={
                "q": text,
                # More than are kept, since some are left out below.
                "page_size": 2 * OFF_SEARCH_KEPT,
                "fields": OFF_SEARCH_FIELDS,
            },
            timeout=15,
            headers=OFF_HEADERS,
        )
    except requests.RequestException as e:
        msg = f"External API unreachable: {e}"
        raise OFFError(msg) from e

    if response.status_code != HTTPStatus.OK:
        msg = f"External API returned an error: {response.status_code}"
        raise OFFError(msg)

    try:
        hits = [OFFSearchHitSchema.model_validate(h) for h in response.json()["hits"]]
    except (ValueError, KeyError, TypeError) as e:
        msg = f"Invalid search response received from external API: {e}"
        raise OFFError(msg) from e

    kept: list[OFFSearchHitSchema] = []
    for hit in hits:
        try:
            validate_ean13(hit.barcode)
            hit.image_url = validate_off_image_url(hit.image_url)
        except DjangoValidationError:
            continue
        except ValueError:
            # A picture that is not OpenFoodFacts' own is not shown; the product is.
            hit.image_url = None
        kept.append(hit)
    return kept[:OFF_SEARCH_KEPT]


def ingredient_inputs_from_label(
    text: str | None, language: str | None, ignored: Iterable[Span] = ()
) -> tuple[list[IngredientInput], list[LabelWarning]]:
    """
    The ingredients a label's text lists, ready to save, and what looks wrong in it.

    Only the text is read (see services.label_parser), in the language
    OpenFoodFacts says it is in, without the places of it that `ignored` are. A text
    that looks badly read gives no ingredient and a warning that says so.
    """
    inputs, warnings, _used = read_inputs_from_label(text, language, ignored)
    return inputs, warnings


def read_inputs_from_label(
    text: str | None, language: str | None, ignored: Iterable[Span] = ()
) -> tuple[list[IngredientInput], list[LabelWarning], tuple[Span, ...]]:
    """
    ingredient_inputs_from_label, and the places of the text they were read from.
    """
    reading = read_label(text, ignored)
    code = (language or "").strip().lower()
    inputs = [_ingredient_input(item, code) for item in reading.items]
    return inputs, reading.warnings, reading.used


def _ingredient_input(item: LabelItem, language: str) -> IngredientInput:
    return IngredientInput(
        name=item.name[:255],
        percentage=item.percentage,
        function=item.function,
        code=item.code,
        language=language[:10],
        sub_ingredients=[_ingredient_input(part, language) for part in item.parts],
    )


# OpenFoodFacts stores every mass nutrient in grams: vitamin D of 3.4 µg is
# 3.4e-06. Factors from grams to each catalogue unit.
_FROM_GRAMS = {
    Nutrient.Unit.GRAM: Decimal(1),
    Nutrient.Unit.MILLIGRAM: Decimal(1_000),
    Nutrient.Unit.MICROGRAM: Decimal(1_000_000),
}
_FOUR_PLACES = Decimal("0.0001")


def declared_nutrients_from_off(nutriments: dict[str, Any]) -> dict[str, Decimal]:
    """
    Label values from an OpenFoodFacts product, keyed by Nutrient.code.

    Each catalogue nutrient with an off_key is read from `<off_key>_100g` and
    converted to its own unit. Energy is already in kJ. Missing, unreadable
    and negative values are left out.
    """
    values: dict[str, Decimal] = {}
    for nutrient in Nutrient.objects.exclude(off_key=None):
        raw = nutriments.get(f"{nutrient.off_key}_100g")
        if raw is None or raw == "":
            continue
        try:
            amount = Decimal(str(raw))
        except InvalidOperation:
            continue
        if not amount.is_finite() or amount < 0:
            continue
        unit = Nutrient.Unit(nutrient.unit)
        if unit is not Nutrient.Unit.KILOJOULE:
            amount *= _FROM_GRAMS[unit]
        values[nutrient.code] = amount.quantize(_FOUR_PLACES)
    return values


def nutrition_unit_from_off(
    per: str | None, quantity: str | None = None, serving_size: str | None = None
) -> str:
    """
    What the nutrition table of an OpenFoodFacts product is given per 100 of: "ml"
    when it says "100ml", or when the product is a liquid and says nothing of the
    kind, else "g".

    OpenFoodFacts keeps a table per 100 ml under the same `_100g` keys, with the
    values as the label prints them, so the unit has to be read from here. A table
    per serving is already worked out per 100 by OpenFoodFacts and is read as it is.

    Most liquids are said to be "100g" all the same, OpenFoodFacts having no
    other choice for them, while the label is per 100 ml (a drink of "4 x 200 ml"):
    what the product is sold by tells. The package is read first, then the serving;
    a text that is not read (see services.packages, services.servings) tells nothing.
    """
    if (per or "").replace(" ", "").lower() == "100ml":
        return Product.ServingUnit.MILLILITRE.value
    package = read_package(quantity)
    if package is not None:
        return package.unit
    serving = read_serving(serving_size)
    if serving is not None:
        return serving.unit
    return Product.ServingUnit.GRAM.value
