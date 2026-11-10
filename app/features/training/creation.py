"""Bounded routine-create transport, accepting multipart content or legacy JSON."""

from collections.abc import Awaitable
from json import JSONDecodeError
from typing import Protocol

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.features.training.schemas import RoutineCreate

# 500 exercise slots × 100 planned sets, including either supported weight format,
# fits below 16 MiB even with escaped names/notes. The image has a separate 5 MiB cap.
JSON_MEDIA_TYPE = "application/json"
CONTENT_TOO_LARGE_DETAIL = "Routine content exceeds 16 MiB limit"
MAX_ROUTINE_CONTENT_BYTES = 16 * 1024 * 1024
MAX_ROUTINE_REQUEST_BYTES = MAX_ROUTINE_CONTENT_BYTES + 5 * 1024 * 1024 + 64 * 1024


class _MultipartFormRequest(Protocol):
    """Public Starlette form interface consumed by the bounded multipart parser."""

    def form(
        self,
        *,
        max_files: int | float = 1000,
        max_fields: int | float = 1000,
        max_part_size: int = 1024 * 1024,
    ) -> Awaitable[FormData]: ...


def request_body_schema() -> dict:
    """Inline DTO definitions so refs remain valid within either media-type schema."""
    schema = RoutineCreate.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(value):
        if isinstance(value, dict):
            if "$ref" in value:
                return inline(definitions[value["$ref"].rsplit("/", 1)[-1]])
            return {key: inline(item) for key, item in value.items()}
        if isinstance(value, list):
            return [inline(item) for item in value]
        return value

    content_schema = inline(schema)
    return {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["content"],
                    "additionalProperties": False,
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "JSON-encoded routine content; maximum 16 MiB UTF-8.",
                            "contentMediaType": JSON_MEDIA_TYPE,
                            "contentSchema": content_schema,
                        },
                        "file": {"type": "string", "format": "binary"},
                    },
                },
            },
            JSON_MEDIA_TYPE: {"schema": content_schema},
        },
    }


async def _parse_multipart(
    request: _MultipartFormRequest,
) -> tuple[RoutineCreate, UploadFile | None]:
    try:
        form = await request.form(
            max_files=1, max_fields=2, max_part_size=MAX_ROUTINE_CONTENT_BYTES
        )
    except StarletteHTTPException as error:
        if "Part exceeded maximum size" in str(error.detail):
            raise HTTPException(413, CONTENT_TOO_LARGE_DETAIL) from None
        raise HTTPException(422, "Invalid multipart routine content") from None
    if len(form.getlist("content")) != 1 or len(form.getlist("file")) > 1:
        raise HTTPException(422, "Supply one content field and at most one image file")
    if set(form) - {"content", "file"}:
        raise HTTPException(422, "Supply routine content and optional file only")
    content = form.get("content")
    file = form.get("file")
    if not isinstance(content, str) or (file is not None and not isinstance(file, UploadFile)):
        raise HTTPException(422, "Supply JSON content and an optional image file")
    if len(content.encode("utf-8")) > MAX_ROUTINE_CONTENT_BYTES:
        raise HTTPException(413, CONTENT_TOO_LARGE_DETAIL)
    return RoutineCreate.model_validate_json(content), file


async def parse_create(request: Request) -> tuple[RoutineCreate, UploadFile | None]:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    try:
        if media_type == "multipart/form-data":
            return await _parse_multipart(request)
        if media_type == JSON_MEDIA_TYPE:
            body = await request.body()
            if len(body) > MAX_ROUTINE_CONTENT_BYTES:
                raise HTTPException(413, CONTENT_TOO_LARGE_DETAIL)
            return RoutineCreate.model_validate_json(body), None
        raise HTTPException(415, "Use multipart/form-data or application/json")
    except (ValidationError, JSONDecodeError) as error:
        errors = error.errors() if isinstance(error, ValidationError) else [{"msg": "Invalid JSON"}]
        raise RequestValidationError(errors) from None
