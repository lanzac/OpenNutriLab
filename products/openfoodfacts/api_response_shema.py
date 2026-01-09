# https://world.openfoodfacts.org/files/redocly/api-v3.redoc-static.html#schema/shape
from enum import Enum

from ninja import Schema

from products.openfoodfacts.schema import OFFProductSchema

# ---- ENUMS ----


class StatusEnum(str, Enum):
    success = "success"
    success_with_warnings = "success_with_warnings"
    success_with_errors = "success_with_errors"
    failure = "failure"


# ---- BLOCK: message ----


class Message(Schema):
    id: str
    name: str
    lc_name: str | None = None
    description: str | None = None
    lc_description: str | None = None


# ---- BLOCK: field ----


class FieldInfo(Schema):
    id: str
    value: str


# ---- BLOCK: impact ----


class Impact(Schema):
    id: str
    name: str
    lc_name: str | None = None
    description: str | None = None
    lc_description: str | None = None


# ---- BLOCK: warning/error entry ----


class WarningOrError(Schema):
    message: Message
    field: FieldInfo
    impact: Impact


# ---- BLOCK: result ----


class Result(Schema):
    id: str
    name: str
    lc_name: str | None = None


# ---- ROOT RESPONSE ----


class OFFProductAPIResponseSchema(Schema):
    status: StatusEnum
    result: Result
    warnings: list[WarningOrError] | None = None
    errors: list[WarningOrError] | None = None
    product: OFFProductSchema | None = None


# If API returns an error (e.g., 500), we return this schema
class OFFAPIErrorSchema(Schema):
    error: str
