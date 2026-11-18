"""Authenticated private league endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, Response

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.accounts.errors import PictureMissing, PictureStorageUnavailable
from app.features.leagues import pictures, service
from app.features.leagues.configuration_router import router as configuration_router
from app.features.leagues.errors import (
    InvitationExpired,
    InvitationNotFound,
    LeagueForbidden,
    LeagueNotFound,
    LeagueRoleChangeForbidden,
)
from app.features.leagues.pictures_router import router as pictures_router
from app.features.leagues.schemas import (
    InvitationCreated,
    InvitationPreview,
    LeagueCreate,
    LeagueCreated,
    LeagueDetail,
    LeagueListItem,
    LeaguePatch,
    LeagueRoleUpdate,
)

router = APIRouter(prefix="/leagues", tags=["leagues"])
LeagueId = Annotated[int, Path(gt=0, le=2**63 - 1)]
router.include_router(configuration_router)
router.include_router(pictures_router)


@router.get("")
async def list_leagues(user: CurrentUser, session: DatabaseSession) -> list[LeagueListItem]:
    return await service.list_leagues(session, user.id)


@router.post("", status_code=201)
async def create_league(
    data: LeagueCreate, user: CurrentUser, session: DatabaseSession
) -> LeagueCreated:
    return await service.create_league(session, user.id, data)


@router.get("/{league_id}")
async def get_league(
    league_id: LeagueId, user: CurrentUser, session: DatabaseSession
) -> LeagueDetail:
    try:
        return await service.get_league(session, user.id, league_id)
    except LeagueNotFound:
        raise HTTPException(404, "League not found") from None


@router.patch("/{league_id}")
async def rename_league(
    league_id: LeagueId, data: LeaguePatch, user: CurrentUser, session: DatabaseSession
) -> LeagueDetail:
    try:
        return await service.rename_league(session, user.id, league_id, data)
    except LeagueNotFound:
        raise HTTPException(404, "League not found") from None
    except LeagueForbidden:
        raise HTTPException(403, "League administrator required") from None


@router.patch("/{league_id}/members/{member_id}/role")
async def update_member_role(
    league_id: LeagueId,
    member_id: LeagueId,
    data: LeagueRoleUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> LeagueDetail:
    try:
        return await service.update_member_role(session, user.id, league_id, member_id, data.role)
    except LeagueNotFound:
        raise HTTPException(404, "League or member not found") from None
    except LeagueForbidden:
        raise HTTPException(403, "League administrator required") from None
    except LeagueRoleChangeForbidden as error:
        raise HTTPException(403, str(error)) from None


@router.post("/{league_id}/invitations", status_code=201)
async def create_invitation(
    league_id: LeagueId, user: CurrentUser, session: DatabaseSession
) -> InvitationCreated:
    try:
        return await service.create_invitation(session, user.id, league_id)
    except LeagueNotFound:
        raise HTTPException(404, "League not found") from None
    except LeagueForbidden:
        raise HTTPException(403, "League administrator required") from None


invitation_router = APIRouter(prefix="/league-invitations", tags=["leagues"])


@invitation_router.get("/{token}")
async def preview_invitation(
    token: str, user: CurrentUser, session: DatabaseSession, response: Response
) -> InvitationPreview:
    try:
        response.headers["Cache-Control"] = "private, no-store"
        return await service.preview_invitation(session, user.id, token)
    except InvitationNotFound:
        raise HTTPException(404, "Invitation not found") from None
    except InvitationExpired:
        raise HTTPException(410, "Invitation expired") from None


@invitation_router.get("/{token}/picture")
async def get_invitation_picture(
    token: str, user: CurrentUser, session: DatabaseSession, request: Request
) -> Response:
    try:
        data = await pictures.read_invitation_picture(
            session, token, request.app.state.blob_storage
        )
        return Response(
            data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
        )
    except InvitationNotFound, PictureMissing:
        raise HTTPException(404, "Invitation picture not found") from None
    except InvitationExpired:
        raise HTTPException(410, "Invitation expired") from None
    except PictureStorageUnavailable:
        raise HTTPException(503, "League picture storage is unavailable") from None


@invitation_router.post("/{token}/accept")
async def accept_invitation(
    token: str, user: CurrentUser, session: DatabaseSession
) -> LeagueDetail:
    try:
        return await service.accept_invitation(session, user.id, token)
    except InvitationNotFound:
        raise HTTPException(404, "Invitation not found") from None
    except InvitationExpired:
        raise HTTPException(410, "Invitation expired") from None
