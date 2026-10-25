from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.core.auth.dependencies import CurrentUser
from app.core.storage.azure import AzureStorage
from app.db.session import DatabaseSession
from app.features.accounts import pictures
from app.features.accounts.errors import (
    InvalidPicture,
    PictureMissing,
    PictureStorageUnavailable,
    PictureTooLarge,
    UnsupportedPicture,
)
from app.features.accounts.schemas import AccountResponse, ProfilePatch
from app.features.accounts.service import AccountDenied, read_account, update_profile

auth_router = APIRouter(prefix="/auth", tags=["accounts"])

router = APIRouter(prefix="/me", tags=["accounts"])


@auth_router.get("/me", responses={403: {"description": "Account access denied"}})
@router.get("", responses={403: {"description": "Account access denied"}})
async def get_me(user: CurrentUser, session: DatabaseSession) -> AccountResponse:
    try:
        return await read_account(session, user.id)
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None


@router.patch("/profile", responses={403: {"description": "Account access denied"}})
async def patch_profile(
    changes: ProfilePatch, user: CurrentUser, session: DatabaseSession, request: Request
) -> AccountResponse:
    try:
        return await update_profile(session, user.id, changes, request.app.state.blob_storage)
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None


@router.post("/profile/picture")
async def post_profile_picture(
    user: CurrentUser, session: DatabaseSession, storage: AzureStorage, file: UploadFile
) -> AccountResponse:
    try:
        data = await file.read(pictures.MAX_PICTURE_BYTES + 1)
        return await pictures.upload_picture(session, user.id, storage, data, file.content_type)
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None
    except PictureTooLarge:
        raise HTTPException(413, "Profile picture exceeds 5 MiB limit") from None
    except UnsupportedPicture:
        raise HTTPException(415, "Use a JPEG, PNG or WebP image") from None
    except InvalidPicture:
        raise HTTPException(422, "Use a valid image with at most 16 million pixels") from None
    except PictureStorageUnavailable:
        raise HTTPException(503, "Profile picture storage is unavailable") from None
    finally:
        await file.close()


@router.get("/profile/picture")
async def get_profile_picture(
    user: CurrentUser, session: DatabaseSession, storage: AzureStorage
) -> Response:
    try:
        data = await pictures.read_picture(session, user.id, storage)
        return Response(
            data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
        )
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None
    except PictureMissing:
        raise HTTPException(404, "No profile picture uploaded") from None
    except PictureStorageUnavailable:
        raise HTTPException(503, "Profile picture storage is unavailable") from None


@router.delete("/profile/picture")
async def delete_profile_picture(
    user: CurrentUser, session: DatabaseSession, request: Request
) -> AccountResponse:
    try:
        return await pictures.remove_picture(session, user.id, request.app.state.blob_storage)
    except AccountDenied:
        raise HTTPException(403, "Account access denied") from None
