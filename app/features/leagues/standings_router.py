"""Authenticated standings and league-scoped credited score history."""

from collections.abc import Awaitable
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.leagues.errors import LeagueNotFound
from app.features.leagues.router import LeagueId
from app.features.leagues.standings import LegacyLeagueUnavailable, get_standings
from app.features.leagues.standings_pages import (
    RoundNotFound,
    get_contributions_page,
    get_round_catalog,
    get_score_history,
    get_standings_page,
)
from app.features.leagues.standings_schemas import (
    ContributionsPage,
    MemberScoreHistory,
    RoundCatalog,
    StandingsPage,
    StandingsPageQuery,
)

router = APIRouter(prefix="/leagues", tags=["leagues"])
PageSize = Annotated[int, Query(ge=1, le=50)]


async def _league_read[T](result: Awaitable[T]) -> T:
    try:
        return await result
    except LeagueNotFound:
        raise HTTPException(404, "League not found") from None
    except RoundNotFound:
        raise HTTPException(404, "Round not found") from None
    except LegacyLeagueUnavailable:
        raise HTTPException(409, "Legacy league requires explicit calendar migration") from None


@router.get("/{league_id}/standings")
async def standings(league_id: LeagueId, user: CurrentUser, session: DatabaseSession):
    return await _league_read(get_standings(session, user.id, league_id))


@router.get("/{league_id}/standings/rounds")
async def standings_rounds(
    league_id: LeagueId, user: CurrentUser, session: DatabaseSession
) -> RoundCatalog:
    return await _league_read(get_round_catalog(session, user.id, league_id))


@router.get("/{league_id}/standings/page")
async def standings_page(
    league_id: LeagueId,
    user: CurrentUser,
    session: DatabaseSession,
    query: Annotated[StandingsPageQuery, Query()],
) -> StandingsPage:
    return await _league_read(
        get_standings_page(session, user.id, league_id, query.round_id, query.offset, query.limit)
    )


@router.get("/{league_id}/standings/contributions", response_model_exclude_unset=True)
async def standings_contributions(
    league_id: LeagueId,
    user: CurrentUser,
    session: DatabaseSession,
    query: Annotated[StandingsPageQuery, Query()],
) -> ContributionsPage:
    return await _league_read(
        get_contributions_page(
            session, user.id, league_id, query.round_id, query.offset, query.limit
        )
    )


@router.get("/{league_id}/members/{member_id}/score-history", response_model_exclude_unset=True)
async def member_score_history(
    league_id: LeagueId,
    member_id: LeagueId,
    user: CurrentUser,
    session: DatabaseSession,
    before: date | None = None,
    limit: PageSize = 20,
) -> MemberScoreHistory:
    return await _league_read(
        get_score_history(session, user.id, league_id, member_id, before, limit)
    )
