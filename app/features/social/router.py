"""Friend requests, friend lists and people search."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Response

from app.core.auth.dependencies import CurrentUser
from app.core.storage.azure import AzureStorage
from app.db.session import DatabaseSession
from app.features.accounts import pictures
from app.features.accounts.errors import PictureMissing, PictureStorageUnavailable
from app.features.accounts.service import AccountDenied
from app.features.social import service
from app.features.social.errors import PersonNotFound, RequestNotFound, SelfFriendship
from app.features.social.schemas import (
    FriendPage,
    FriendRequestCreate,
    FriendRequests,
    PersonPage,
    PersonProfile,
    RelationshipResponse,
)

friends_router = APIRouter(prefix="/friends", tags=["social"])
people_router = APIRouter(prefix="/people", tags=["social"])
PersonId = Annotated[int, Path(gt=0, le=2**63 - 1)]
PERSON_NOT_FOUND = "Person not found"


@people_router.get("")
async def search_people(
    user: CurrentUser,
    session: DatabaseSession,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> PersonPage:
    text = q.strip()
    if len(text) < 2:
        raise HTTPException(422, "Type at least 2 characters")
    return await service.search_people(session, user.id, text, limit)


@people_router.get("/{person_id}", responses={404: {"description": PERSON_NOT_FOUND}})
async def get_person(
    person_id: PersonId, user: CurrentUser, session: DatabaseSession
) -> PersonProfile:
    try:
        return await service.get_person(session, user.id, person_id)
    except PersonNotFound:
        raise HTTPException(404, PERSON_NOT_FOUND) from None


@people_router.get(
    "/{person_id}/picture",
    responses={
        404: {"description": "No profile picture"},
        503: {"description": "Profile picture storage is unavailable"},
    },
)
async def get_person_picture(
    person_id: PersonId, user: CurrentUser, session: DatabaseSession, storage: AzureStorage
) -> Response:
    """Any signed-in account may see an active person's photo, to tell same-named people apart."""
    try:
        data = await pictures.read_picture(session, person_id, storage)
    except AccountDenied, PictureMissing:
        raise HTTPException(404, "No profile picture") from None
    except PictureStorageUnavailable:
        raise HTTPException(503, "Profile picture storage is unavailable") from None
    # Short private caching: a replaced photo shows up within minutes.
    return Response(
        data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"}
    )


@friends_router.get("")
async def get_friends(
    user: CurrentUser,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
) -> FriendPage:
    return await service.list_friends(session, user.id, limit, offset)


@friends_router.get("/requests")
async def get_requests(user: CurrentUser, session: DatabaseSession) -> FriendRequests:
    return await service.list_requests(session, user.id)


@friends_router.post(
    "/requests",
    responses={
        404: {"description": PERSON_NOT_FOUND},
        422: {"description": "You cannot add yourself"},
    },
)
async def post_request(
    data: FriendRequestCreate, user: CurrentUser, session: DatabaseSession
) -> RelationshipResponse:
    try:
        return await service.send_request(session, user.id, data.user_id)
    except SelfFriendship:
        raise HTTPException(422, "You cannot add yourself") from None
    except PersonNotFound:
        raise HTTPException(404, PERSON_NOT_FOUND) from None


@friends_router.post(
    "/requests/{person_id}/accept",
    responses={404: {"description": "No friend request from this person"}},
)
async def accept_request(
    person_id: PersonId, user: CurrentUser, session: DatabaseSession
) -> RelationshipResponse:
    try:
        return await service.accept_request(session, user.id, person_id)
    except PersonNotFound, RequestNotFound:
        raise HTTPException(404, "No friend request from this person") from None


@friends_router.delete("/{person_id}", status_code=204)
async def delete_friend(
    person_id: PersonId, user: CurrentUser, session: DatabaseSession
) -> Response:
    """Unfriend, decline or cancel; succeeds even when nothing exists."""
    await service.remove(session, user.id, person_id)
    return Response(status_code=204)
