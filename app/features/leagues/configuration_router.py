"""Bounded multipart transport for atomic league create and edit."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cache
from typing import Annotated
from zoneinfo import available_timezones

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, ValidationError
from python_multipart.exceptions import MultipartParseError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.accounts.errors import (
    InvalidPicture,
    PictureStorageUnavailable,
    PictureTooLarge,
    UnsupportedPicture,
)
from app.features.leagues import pictures, service
from app.features.leagues.errors import LeagueForbidden, LeagueNotFound
from app.features.leagues.pictures_router import picture_http_error
from app.features.leagues.schemas import (
    LeagueConfiguration,
    LeagueCreate,
    LeagueCreated,
    LeagueDetail,
)

router = APIRouter()
LeagueId = Annotated[int, Path(gt=0, le=2**63 - 1)]
_CONFIGURATION_ERRORS = (
    InvalidPicture,
    PictureStorageUnavailable,
    PictureTooLarge,
    UnsupportedPicture,
    LeagueForbidden,
    LeagueNotFound,
)
_MULTIPART_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["data"],
                    "additionalProperties": False,
                    "properties": {
                        "data": {
                            "type": "string",
                            "contentMediaType": "application/json",
                            "description": "JSON-encoded league configuration",
                        },
                        "file": {"type": "string", "format": "binary"},
                    },
                }
            }
        },
    }
}


@cache
def _supported_timezones() -> tuple[str, ...]:
    return tuple(sorted(available_timezones() | {"UTC"}))


@router.get("/timezones")
def timezones(user: CurrentUser) -> tuple[str, ...]:
    return _supported_timezones()


@asynccontextmanager
async def _configuration[T: BaseModel](
    request: Request, schema: type[T]
) -> AsyncIterator[tuple[T, UploadFile | None]]:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "multipart/form-data":
        raise HTTPException(415, "Use multipart/form-data")
    try:
        form = await MultiPartParser(
            request.headers, request.stream(), max_files=1, max_fields=1, max_part_size=16 * 1024
        ).parse()
    except MultiPartException as error:
        if "Part exceeded maximum size" in error.message:
            raise HTTPException(413, "League configuration exceeds 16 KiB limit") from None
        raise HTTPException(422, "Invalid multipart league configuration") from None
    except MultipartParseError:
        raise HTTPException(422, "Invalid multipart league configuration") from None
    try:
        data, file = form.get("data"), form.get("file")
        if (
            set(form) - {"data", "file"}
            or not isinstance(data, str)
            or (file is not None and not isinstance(file, UploadFile))
        ):
            raise HTTPException(422, "Supply JSON data and an optional image file")
        try:
            configuration = schema.model_validate_json(data)
        except ValidationError as error:
            raise HTTPException(
                422, error.errors(include_url=False, include_context=False, include_input=False)
            ) from None
        yield configuration, file
    finally:
        await form.close()


@router.post(
    "/configuration",
    status_code=201,
    openapi_extra=_MULTIPART_BODY,
    responses={
        413: {"description": "Configuration or picture too large"},
        415: {"description": "Unsupported media type"},
        422: {"description": "Invalid configuration"},
    },
)
async def create_configuration(
    user: CurrentUser, session: DatabaseSession, request: Request
) -> LeagueCreated:
    async with _configuration(request, LeagueCreate) as (data, file):
        if file is None:
            return await service.create_league(session, user.id, data)
        try:
            return await pictures.create_with_picture(
                session,
                user.id,
                data,
                request.app.state.blob_storage,
                await file.read(pictures.MAX_PICTURE_BYTES + 1),
                file.content_type,
            )
        except _CONFIGURATION_ERRORS as error:
            raise picture_http_error(error) from None


@router.post(
    "/{league_id}/configuration",
    openapi_extra=_MULTIPART_BODY,
    responses={
        413: {"description": "Configuration or picture too large"},
        415: {"description": "Unsupported media type"},
        422: {"description": "Invalid configuration"},
    },
)
async def edit_configuration(
    league_id: LeagueId, user: CurrentUser, session: DatabaseSession, request: Request
) -> LeagueDetail:
    async with _configuration(request, LeagueConfiguration) as (data, file):
        if file is not None and data.remove_picture:
            raise HTTPException(422, "Choose picture replacement or removal")
        try:
            return await pictures.update_configuration(
                session,
                user.id,
                league_id,
                data,
                request.app.state.blob_storage,
                await file.read(pictures.MAX_PICTURE_BYTES + 1) if file is not None else None,
                file.content_type if file is not None else None,
            )
        except _CONFIGURATION_ERRORS as error:
            raise picture_http_error(error) from None
