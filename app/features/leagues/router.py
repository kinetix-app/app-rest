"""Authenticated private league endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.leagues import service
from app.features.leagues.errors import (
    InvitationExpired,
    InvitationNotFound,
    LeagueForbidden,
    LeagueNotFound,
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
)

router = APIRouter(prefix="/leagues", tags=["leagues"])
LeagueId = Annotated[int, Path(gt=0, le=2**63 - 1)]
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
    token: str, user: CurrentUser, session: DatabaseSession
) -> InvitationPreview:
    try:
        return await service.preview_invitation(session, token)
    except InvitationNotFound:
        raise HTTPException(404, "Invitation not found") from None
    except InvitationExpired:
        raise HTTPException(410, "Invitation expired") from None


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
