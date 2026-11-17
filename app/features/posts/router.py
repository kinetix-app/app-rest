"""Workout posts feed, likes, comments and authenticated image delivery."""

from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Path, Query, Request, UploadFile
from fastapi.responses import Response

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.accounts.errors import InvalidPicture, PictureTooLarge, UnsupportedPicture
from app.features.posts import service
from app.features.posts.errors import (
    CommentNotFound,
    EmptyPost,
    MediaMissing,
    MediaStorageUnavailable,
    PostActionForbidden,
    PostNotFound,
    WorkoutAlreadyShared,
    WorkoutUnavailable,
)
from app.features.posts.media import MAX_POST_IMAGE_BYTES, MAX_POST_IMAGES
from app.features.posts.models import PostVisibility
from app.features.posts.schemas import (
    MAX_POST_TEXT,
    CommentCreate,
    CommentPage,
    CommentResponse,
    LikeResponse,
    PostPage,
    PostResponse,
)

router = APIRouter(prefix="/posts", tags=["posts"])
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]
Cursor = Annotated[int | None, Query(gt=0, le=2**63 - 1)]
POST_NOT_FOUND = "Post not found"
NOT_FOUND = {404: {"description": POST_NOT_FOUND}}
STORAGE_UNAVAILABLE = "Post image storage is unavailable"
TOO_MANY_IMAGES = f"Attach at most {MAX_POST_IMAGES} images"


@router.get("")
async def get_feed(
    user: CurrentUser,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    before_id: Cursor = None,
    scope: Literal["everyone", "friends"] = "everyone",
) -> PostPage:
    return await service.list_feed(session, user.id, limit, before_id, scope)


@router.post(
    "",
    status_code=201,
    responses={
        409: {"description": "This workout has already been shared"},
        413: {"description": "Each image must be at most 5 MiB (25 MiB per upload)"},
        415: {"description": "Use JPEG, PNG or WebP images"},
        422: {"description": "Empty post, or invalid workout, text, visibility or image"},
        503: {"description": STORAGE_UNAVAILABLE},
    },
)
async def post_post(
    user: CurrentUser,
    session: DatabaseSession,
    request: Request,
    training_session_id: Annotated[int | None, Form(gt=0, le=2**63 - 1)] = None,
    text: Annotated[str, Form(max_length=MAX_POST_TEXT)] = "",
    visibility: Annotated[Literal["PUBLIC", "FRIENDS", "PRIVATE"], Form()] = "PUBLIC",
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> PostResponse:
    uploads = files or []
    try:
        if len(uploads) > MAX_POST_IMAGES:
            raise HTTPException(422, TOO_MANY_IMAGES)
        images = [
            (await upload.read(MAX_POST_IMAGE_BYTES + 1), upload.content_type) for upload in uploads
        ]
        return await service.create_post(
            session,
            user.id,
            request.app.state.blob_storage,
            text=text.strip(),
            training_session_id=training_session_id,
            visibility=PostVisibility(visibility),
            images=images,
        )
    except EmptyPost:
        raise HTTPException(422, "Add a caption, a photo or a workout") from None
    except WorkoutUnavailable:
        raise HTTPException(422, "Share one of your completed workouts") from None
    except WorkoutAlreadyShared:
        raise HTTPException(409, "This workout has already been shared") from None
    except PictureTooLarge:
        raise HTTPException(413, "Each image must be at most 5 MiB") from None
    except UnsupportedPicture:
        raise HTTPException(415, "Use JPEG, PNG or WebP images") from None
    except InvalidPicture:
        raise HTTPException(422, "Use valid images with at most 16 million pixels") from None
    except MediaStorageUnavailable:
        raise HTTPException(503, STORAGE_UNAVAILABLE) from None
    finally:
        for upload in uploads:
            await upload.close()


@router.get("/{post_id}", responses=NOT_FOUND)
async def get_post(
    post_id: ResourceId, user: CurrentUser, session: DatabaseSession
) -> PostResponse:
    try:
        return await service.get_post(session, user.id, post_id)
    except PostNotFound:
        raise HTTPException(404, POST_NOT_FOUND) from None


@router.delete(
    "/{post_id}",
    status_code=204,
    responses={**NOT_FOUND, 403: {"description": "Only the author can delete a post"}},
)
async def delete_post(
    post_id: ResourceId, user: CurrentUser, session: DatabaseSession, request: Request
) -> Response:
    try:
        await service.delete_post(session, user.id, post_id, request.app.state.blob_storage)
        return Response(status_code=204)
    except PostNotFound:
        raise HTTPException(404, POST_NOT_FOUND) from None
    except PostActionForbidden:
        raise HTTPException(403, "Only the author can delete a post") from None


@router.put("/{post_id}/like", responses=NOT_FOUND)
async def put_like(
    post_id: ResourceId, user: CurrentUser, session: DatabaseSession
) -> LikeResponse:
    try:
        return await service.set_like(session, user.id, post_id, True)
    except PostNotFound:
        raise HTTPException(404, POST_NOT_FOUND) from None


@router.delete("/{post_id}/like", responses=NOT_FOUND)
async def delete_like(
    post_id: ResourceId, user: CurrentUser, session: DatabaseSession
) -> LikeResponse:
    try:
        return await service.set_like(session, user.id, post_id, False)
    except PostNotFound:
        raise HTTPException(404, POST_NOT_FOUND) from None


@router.get("/{post_id}/comments", responses=NOT_FOUND)
async def get_comments(
    post_id: ResourceId,
    user: CurrentUser,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after_id: Cursor = None,
) -> CommentPage:
    try:
        return await service.list_comments(session, user.id, post_id, limit, after_id)
    except PostNotFound:
        raise HTTPException(404, POST_NOT_FOUND) from None


@router.post("/{post_id}/comments", status_code=201, responses=NOT_FOUND)
async def post_comment(
    post_id: ResourceId, data: CommentCreate, user: CurrentUser, session: DatabaseSession
) -> CommentResponse:
    try:
        return await service.create_comment(session, user.id, post_id, data.comment)
    except PostNotFound:
        raise HTTPException(404, POST_NOT_FOUND) from None


@router.delete(
    "/{post_id}/comments/{comment_id}",
    status_code=204,
    responses={
        404: {"description": "Post or comment not found"},
        403: {"description": "Only the comment author or post author can delete a comment"},
    },
)
async def delete_comment(
    post_id: ResourceId, comment_id: ResourceId, user: CurrentUser, session: DatabaseSession
) -> Response:
    try:
        await service.delete_comment(session, user.id, post_id, comment_id)
        return Response(status_code=204)
    except PostNotFound:
        raise HTTPException(404, POST_NOT_FOUND) from None
    except CommentNotFound:
        raise HTTPException(404, "Comment not found") from None
    except PostActionForbidden:
        raise HTTPException(
            403, "Only the comment author or post author can delete a comment"
        ) from None


@router.get(
    "/{post_id}/media/{file_id}",
    responses={
        404: {"description": "Post or image not found"},
        503: {"description": STORAGE_UNAVAILABLE},
    },
)
async def get_media(
    post_id: ResourceId,
    file_id: ResourceId,
    user: CurrentUser,
    session: DatabaseSession,
    request: Request,
) -> Response:
    try:
        data = await service.read_media(
            session, user.id, post_id, file_id, request.app.state.blob_storage
        )
    except PostNotFound:
        raise HTTPException(404, POST_NOT_FOUND) from None
    except MediaMissing:
        raise HTTPException(404, "Image not found") from None
    except MediaStorageUnavailable:
        raise HTTPException(503, STORAGE_UNAVAILABLE) from None
    # Blob names are never reused, so a viewer may cache an image briefly.
    return Response(
        data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
    )
