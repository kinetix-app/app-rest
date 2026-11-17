"""Authenticated standings; no body weight or source details for other members."""

from fastapi import APIRouter, HTTPException

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.leagues.errors import LeagueNotFound
from app.features.leagues.router import LeagueId
from app.features.leagues.standings import LegacyLeagueUnavailable, get_standings

router = APIRouter(prefix="/leagues", tags=["leagues"])


@router.get("/{league_id}/standings")
async def standings(league_id: LeagueId, user: CurrentUser, session: DatabaseSession):
    try:
        return await get_standings(session, user.id, league_id)
    except LeagueNotFound:
        raise HTTPException(404, "League not found") from None
    except LegacyLeagueUnavailable:
        raise HTTPException(409, "Legacy league requires explicit calendar migration") from None
