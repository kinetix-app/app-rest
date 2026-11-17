"""Idempotent lazy closure and monotonic per-member acknowledgement.

A league row lock serializes closure, credit and acknowledgements. Reading pending
results never acknowledges display. No penalty, post or destructive reset occurs.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.leagues.errors import LeagueNotFound
from app.features.leagues.models import league_member
from app.features.leagues.result_models import league_result
from app.features.leagues.scoring_models import league_scoring_round
from app.features.leagues.standings import lock_league, materialize_rounds, round_standings


async def close_rounds(session: AsyncSession, row, now: datetime):
    await materialize_rounds(session, row, now)
    rounds = (
        (
            await session.execute(
                sa.select(league_scoring_round)
                .where(
                    league_scoring_round.c.league_id == row["id"],
                    league_scoring_round.c.end_at <= now,
                    ~sa.exists().where(league_result.c.round_id == league_scoring_round.c.id),
                )
                .order_by(league_scoring_round.c.start_at)
            )
        )
        .mappings()
        .all()
    )
    for period in rounds:
        detail = await round_standings(session, period, 0)
        standings = detail["standings"]
        minimum = min((int(member["score"]) for member in standings), default=0)
        losers = (
            [member["user_id"] for member in standings if int(member["score"]) == minimum]
            if len(standings) >= 2
            else []
        )
        snapshot = {
            "round_id": period["id"],
            "start_at": period["start_at"].isoformat(),
            "end_at": period["end_at"].isoformat(),
            "standings": standings,
            "loser_user_ids": losers,
        }
        await session.execute(
            league_result.insert().values(
                league_id=row["id"], round_id=period["id"], snapshot=snapshot
            )
        )


async def pending_results(session: AsyncSession, user_id: int, league_id: int, now=None):
    try:
        row = await lock_league(session, user_id, league_id)
        await close_rounds(session, row, now or datetime.now(UTC))
        member = (
            (
                await session.execute(
                    sa.select(league_member).where(
                        league_member.c.league_id == league_id, league_member.c.user_id == user_id
                    )
                )
            )
            .mappings()
            .one()
        )
        query = (
            (
                sa.select(league_result)
                .join(league_scoring_round, league_scoring_round.c.id == league_result.c.round_id)
                .where(
                    league_result.c.league_id == league_id,
                    league_scoring_round.c.end_at > member["joined_at"],
                )
                .order_by(league_result.c.id)
            )
            if member["joined_at"]
            else None
        )
        if query is not None and member["last_seen_result_id"] is not None:
            query = query.where(league_result.c.id > member["last_seen_result_id"])
        result = (
            []
            if query is None
            else [
                {"id": item["id"], **item["snapshot"]}
                for item in (await session.execute(query)).mappings()
            ]
        )
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise


async def acknowledge_result(session: AsyncSession, user_id: int, league_id: int, result_id: int):
    try:
        await lock_league(session, user_id, league_id)
        member = (
            (
                await session.execute(
                    sa.select(league_member).where(
                        league_member.c.league_id == league_id, league_member.c.user_id == user_id
                    )
                )
            )
            .mappings()
            .one()
        )
        result = (
            (
                await session.execute(
                    sa.select(league_result)
                    .join(
                        league_scoring_round, league_scoring_round.c.id == league_result.c.round_id
                    )
                    .where(
                        league_result.c.id == result_id,
                        league_result.c.league_id == league_id,
                        league_scoring_round.c.end_at > member["joined_at"],
                    )
                )
            )
            .mappings()
            .one_or_none()
            if member["joined_at"]
            else None
        )
        if result is None:
            raise LeagueNotFound
        if member["last_seen_result_id"] is None or result_id > member["last_seen_result_id"]:
            await session.execute(
                league_member.update()
                .where(league_member.c.league_id == league_id, league_member.c.user_id == user_id)
                .values(last_seen_result_id=result_id)
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
