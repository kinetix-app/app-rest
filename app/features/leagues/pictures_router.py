"""Authenticated member reads and admin writes for private league profile pictures."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, UploadFile
from fastapi.responses import Response

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.accounts.errors import (
    InvalidPicture,
    PictureMissing,
    PictureStorageUnavailable,
    PictureTooLarge,
    UnsupportedPicture,
)
from app.features.leagues import pictures
from app.features.leagues.errors import LeagueForbidden, LeagueNotFound
from app.features.leagues.schemas import LeagueDetail

router = APIRouter()
LeagueId = Annotated[int, Path(gt=0, le=2**63 - 1)]


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, LeagueNotFound):
        return HTTPException(404, "League not found")
    if isinstance(error, LeagueForbidden):
        return HTTPException(403, "League administrator required")
    if isinstance(error, PictureMissing):
        return HTTPException(404, "No league picture uploaded")
    if isinstance(error, PictureTooLarge):
        return HTTPException(413, "League picture exceeds 5 MiB limit")
    if isinstance(error, UnsupportedPicture):
        return HTTPException(415, "Use a JPEG, PNG or WebP image")
    if isinstance(error, InvalidPicture):
        return HTTPException(422, "Use a valid image with at most 16 million pixels")
    return HTTPException(503, "League picture storage is unavailable")


@router.post(
    "/{league_id}/picture",
    responses={
        403: {"description": "League administrator required"},
        404: {"description": "League not found"},
        413: {"description": "League picture exceeds 5 MiB limit"},
        415: {"description": "Use a JPEG, PNG or WebP image"},
        422: {"description": "Use a valid image with at most 16 million pixels"},
        503: {"description": "League picture storage is unavailable"},
    },
)
async def post_picture(
    league_id: LeagueId,
    user: CurrentUser,
    session: DatabaseSession,
    request: Request,
    file: UploadFile,
) -> LeagueDetail:
    try:
        data = await file.read(pictures.MAX_PICTURE_BYTES + 1)
        return await pictures.upload_picture(
            session, user.id, league_id, request.app.state.blob_storage, data, file.content_type
        )
    except (
        LeagueNotFound,
        LeagueForbidden,
        PictureTooLarge,
        UnsupportedPicture,
        InvalidPicture,
        PictureStorageUnavailable,
    ) as error:
        raise _http_error(error) from None
    finally:
        await file.close()


@router.get(
    "/{league_id}/picture",
    responses={
        404: {"description": "League or picture not found"},
        503: {"description": "League picture storage is unavailable"},
    },
)
async def get_picture(
    league_id: LeagueId, user: CurrentUser, session: DatabaseSession, request: Request
) -> Response:
    try:
        data = await pictures.read_picture(
            session, user.id, league_id, request.app.state.blob_storage
        )
        return Response(
            data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
        )
    except (LeagueNotFound, PictureMissing, PictureStorageUnavailable) as error:
        raise _http_error(error) from None


@router.delete(
    "/{league_id}/picture",
    responses={
        403: {"description": "League administrator required"},
        404: {"description": "League not found"},
    },
)
async def delete_picture(
    league_id: LeagueId, user: CurrentUser, session: DatabaseSession, request: Request
) -> LeagueDetail:
    try:
        return await pictures.remove_picture(
            session, user.id, league_id, request.app.state.blob_storage
        )
    except (LeagueNotFound, LeagueForbidden) as error:
        raise _http_error(error) from None


@router.get(
    "/{league_id}/members/{member_id}/picture",
    responses={
        404: {"description": "League, member or picture not found"},
        503: {"description": "Picture storage is unavailable"},
    },
)
async def get_member_picture(
    league_id: LeagueId,
    member_id: LeagueId,
    user: CurrentUser,
    session: DatabaseSession,
    request: Request,
) -> Response:
    try:
        data = await pictures.read_member_picture(
            session, user.id, league_id, member_id, request.app.state.blob_storage
        )
        return Response(
            data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
        )
    except (LeagueNotFound, PictureMissing, PictureStorageUnavailable) as error:
        raise _http_error(error) from None
