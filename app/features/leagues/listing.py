"""Batched private league cards with the viewer's current-week competition rank."""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.leagues.calculation import weekly_bounds
from app.features.leagues.models import league, league_member
from app.features.leagues.presentation import picture_url
from app.features.leagues.schemas import LeagueListItem
from app.features.leagues.scoring_models import league_daily_score, league_scoring_round


async def list_leagues(
    session: AsyncSession, user_id: int, *, now: datetime | None = None
) -> list[LeagueListItem]:
    # Aggregate memberships once; never fetch a complete standings payload per card.
    counts = (
        sa.select(league_member.c.league_id, sa.func.count().label("member_count"))
        .group_by(league_member.c.league_id)
        .subquery()
    )
    rows = (
        (
            await session.execute(
                sa.select(
                    league.c.id,
                    league.c.name,
                    league.c.timezone,
                    league.c.picture_blob_name,
                    league_member.c.role,
                    league_member.c.joined_at,
                    counts.c.member_count,
                )
                .join(league_member, league_member.c.league_id == league.c.id)
                .join(counts, counts.c.league_id == league.c.id)
                .where(league_member.c.user_id == user_id)
                .order_by(league.c.id)
            )
        )
        .mappings()
        .all()
    )
    instant = now if now is not None else datetime.now(UTC)
    valid = [row for row in rows if row.timezone is not None and row.joined_at is not None]
    positions = {}
    if valid:
        boundaries = (
            sa.values(
                sa.column("league_id", sa.BigInteger),
                sa.column("start_at", sa.DateTime(timezone=True)),
                sa.column("end_at", sa.DateTime(timezone=True)),
            )
            .data([(row.id, *weekly_bounds(instant, row.timezone)) for row in valid])
            .cte("current_week")
        )
        totals = (
            sa.select(
                league_daily_score.c.league_id,
                league_daily_score.c.user_id,
                sa.func.sum(league_daily_score.c.score).label("score"),
            )
            .join(
                league_scoring_round,
                sa.and_(
                    league_scoring_round.c.id == league_daily_score.c.round_id,
                    league_scoring_round.c.league_id == league_daily_score.c.league_id,
                ),
            )
            .join(
                boundaries,
                sa.and_(
                    boundaries.c.league_id == league_scoring_round.c.league_id,
                    boundaries.c.start_at == league_scoring_round.c.start_at,
                    boundaries.c.end_at == league_scoring_round.c.end_at,
                ),
            )
            .group_by(league_daily_score.c.league_id, league_daily_score.c.user_id)
            .cte("weekly_totals")
        )
        ranked = (
            sa.select(
                league_member.c.league_id,
                league_member.c.user_id,
                sa.func.rank()
                .over(
                    partition_by=league_member.c.league_id,
                    order_by=sa.func.coalesce(totals.c.score, 0).desc(),
                )
                .label("position"),
            )
            .join(boundaries, boundaries.c.league_id == league_member.c.league_id)
            .outerjoin(
                totals,
                sa.and_(
                    totals.c.league_id == league_member.c.league_id,
                    totals.c.user_id == league_member.c.user_id,
                ),
            )
            # Match current-round standings: unknown/future incorporation is ineligible.
            .where(league_member.c.joined_at < boundaries.c.end_at)
            .cte("weekly_rankings")
        )
        positions = dict(
            (
                await session.execute(
                    sa.select(ranked.c.league_id, ranked.c.position).where(
                        ranked.c.user_id == user_id
                    )
                )
            ).all()
        )
    return [
        LeagueListItem(
            **row,
            picture_url=picture_url(row.id, row.picture_blob_name),
            current_week_position=positions.get(row.id),
        )
        for row in rows
    ]
