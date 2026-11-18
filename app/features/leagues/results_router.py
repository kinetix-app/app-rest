"""Authenticated result reads and explicit acknowledgement after display."""

from fastapi import APIRouter, HTTPException, Response

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.leagues.errors import LeagueNotFound
from app.features.leagues.results import acknowledge_result, pending_results
from app.features.leagues.router import LeagueId
from app.features.leagues.standings import LegacyLeagueUnavailable

router = APIRouter(prefix="/leagues", tags=["leagues"])


@router.get(
    "/{league_id}/results/pending",
    responses={
        404: {"description": "League not found"},
        409: {"description": "League calendar requires migration"},
    },
)
async def pending(league_id: LeagueId, user: CurrentUser, session: DatabaseSession):
    try:
        return await pending_results(session, user.id, league_id)
    except LeagueNotFound:
        raise HTTPException(404, "League not found") from None
    except LegacyLeagueUnavailable:
        raise HTTPException(409, "Legacy league requires explicit calendar migration") from None


@router.post(
    "/{league_id}/results/{result_id}/acknowledge",
    status_code=204,
    responses={
        404: {"description": "Result not found"},
        409: {"description": "League calendar requires migration"},
    },
)
async def acknowledge(
    league_id: LeagueId, result_id: LeagueId, user: CurrentUser, session: DatabaseSession
):
    try:
        await acknowledge_result(session, user.id, league_id, result_id)
        return Response(status_code=204)
    except LeagueNotFound:
        raise HTTPException(404, "Result not found") from None
    except LegacyLeagueUnavailable:
        raise HTTPException(409, "Legacy league requires explicit calendar migration") from None
