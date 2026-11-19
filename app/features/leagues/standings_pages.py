"""Bounded standings and credited score history for private leagues."""

from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.models import Profile
from app.features.leagues.errors import LeagueNotFound
from app.features.leagues.models import league_member, league_round, league_score
from app.features.leagues.presentation import member_picture_url
from app.features.leagues.standings import lock_league, materialize_rounds
from app.features.leagues.standings_schemas import (
    CalculationInputs,
    ContributionItem,
    ContributionsPage,
    MemberScoreHistory,
    MemberScoreItem,
    RoundCatalog,
    RoundSummary,
    StandingItem,
    StandingsPage,
)

rounds = league_round
daily = league_score
members = league_member


class RoundNotFound(Exception):
    """The requested scoring round is outside this league's available calendar."""


async def get_round_catalog(session: AsyncSession, viewer_id: int, league_id: int) -> RoundCatalog:
    async with session.begin():
        league = await lock_league(session, viewer_id, league_id)
        current = await materialize_rounds(session, league, datetime.now(UTC))
        rows = (
            await session.execute(
                sa.select(rounds.c.id, rounds.c.start_at, rounds.c.end_at)
                .where(rounds.c.league_id == league_id, rounds.c.start_at <= current.start_at)
                .order_by(rounds.c.start_at.desc())
            )
        ).mappings()
        return RoundCatalog(
            timezone=league.timezone,
            current_round_id=current.id,
            rounds=[RoundSummary(**row) for row in rows],
        )


async def _resolve_round(
    session: AsyncSession, league_id: int, round_id: int | None
) -> RowMapping | None:
    if round_id is None:
        return None
    selected_round = (
        (
            await session.execute(
                sa.select(rounds).where(rounds.c.league_id == league_id, rounds.c.id == round_id)
            )
        )
        .mappings()
        .one_or_none()
    )
    if selected_round is None:
        raise RoundNotFound
    return selected_round


def _scoped_scores(league_id: int, selected_round: RowMapping | None):
    score_members = members.alias("score_members")
    query = (
        sa.select(
            daily.c.user_id,
            daily.c.local_day,
            daily.c.round_id,
            rounds.c.start_at,
            rounds.c.end_at,
            daily.c.score,
            daily.c.session_id,
            daily.c.ended_at,
        )
        .select_from(daily)
        .join(rounds, rounds.c.id == daily.c.round_id)
        .join(
            score_members,
            sa.and_(
                score_members.c.league_id == daily.c.league_id,
                score_members.c.user_id == daily.c.user_id,
            ),
        )
        .where(daily.c.league_id == league_id, score_members.c.joined_at < rounds.c.end_at)
    )
    if selected_round is not None:
        return query.where(daily.c.round_id == selected_round.id)
    return query


def _ranking_page_query(
    league_id: int,
    selected_round: RowMapping | None,
    offset: int,
    limit: int,
):
    totals_query = (
        _scoped_scores(league_id, selected_round)
        .with_only_columns(daily.c.user_id, sa.func.sum(daily.c.score).label("score"))
        .group_by(daily.c.user_id)
    )
    candidates = sa.select(members.c.user_id).where(members.c.league_id == league_id)
    if selected_round is not None:
        candidates = candidates.where(members.c.joined_at < selected_round.end_at)
    totals = totals_query.subquery()
    score = sa.func.coalesce(totals.c.score, 0)
    ranked = (
        candidates.add_columns(
            score.label("score"),
            sa.func.rank().over(order_by=score.desc()).label("position"),
        )
        .outerjoin(totals, totals.c.user_id == members.c.user_id)
        .subquery()
    )
    order = (ranked.c.position, ranked.c.user_id)
    page = sa.select(ranked).order_by(*order).offset(offset).limit(limit + 1).subquery()
    return (
        sa.select(page, Profile.display_name, Profile.picture_blob_name, Profile.picture_url)
        .outerjoin(Profile, Profile.user_id == page.c.user_id)
        .order_by(page.c.position, page.c.user_id)
    )


async def get_standings_page(
    session: AsyncSession,
    viewer_id: int,
    league_id: int,
    round_id: int | None,
    offset: int,
    limit: int,
) -> StandingsPage:
    async with session.begin():
        await lock_league(session, viewer_id, league_id)
        selected_round = await _resolve_round(session, league_id, round_id)
        rows = (
            await session.execute(_ranking_page_query(league_id, selected_round, offset, limit))
        ).all()
        return StandingsPage(
            items=[
                StandingItem(
                    user_id=row.user_id,
                    display_name=row.display_name,
                    position=row.position,
                    score=str(int(row.score)),
                    picture_url=member_picture_url(
                        league_id, row.user_id, row.picture_blob_name, row.picture_url
                    ),
                )
                for row in rows[:limit]
            ],
            next_offset=offset + limit if len(rows) > limit else None,
        )


_CALCULATION_COLUMNS = (
    daily.c.volume_kg_reps,
    daily.c.duration_us,
    daily.c.body_weight_kg,
    daily.c.formula_version,
)


def _score_item(row: RowMapping, *, owner: bool) -> MemberScoreItem:
    entry = MemberScoreItem(
        local_day=row.local_day,
        round_id=row.round_id,
        start_at=row.start_at,
        end_at=row.end_at,
        score=str(int(row.score)),
        session_id=row.session_id,
        ended_at=row.ended_at,
    )
    if owner:
        entry.calculation = CalculationInputs(
            session_id=row.session_id,
            volume_kg_reps=str(row.volume_kg_reps),
            duration_us=str(row.duration_us),
            body_weight_kg=str(row.body_weight_kg),
            formula_version=row.formula_version,
        )
    return entry


async def get_contributions_page(
    session: AsyncSession,
    viewer_id: int,
    league_id: int,
    round_id: int | None,
    offset: int,
    limit: int,
) -> ContributionsPage:
    async with session.begin():
        await lock_league(session, viewer_id, league_id)
        selected_round = await _resolve_round(session, league_id, round_id)
        # Only the viewer's private calculation columns are read into the application.
        calculation = [
            sa.case((daily.c.user_id == viewer_id, column)).label(column.key)
            for column in _CALCULATION_COLUMNS
        ]
        page = (
            _scoped_scores(league_id, selected_round)
            .add_columns(*calculation)
            .order_by(daily.c.local_day.desc(), daily.c.user_id)
            .offset(offset)
            .limit(limit + 1)
            .subquery()
        )
        rows = (
            (
                await session.execute(
                    sa.select(
                        page, Profile.display_name, Profile.picture_blob_name, Profile.picture_url
                    )
                    .outerjoin(Profile, Profile.user_id == page.c.user_id)
                    .order_by(page.c.local_day.desc(), page.c.user_id)
                )
            )
            .mappings()
            .all()
        )
        return ContributionsPage(
            items=[
                ContributionItem(
                    **_score_item(row, owner=row.user_id == viewer_id).model_dump(
                        exclude_unset=True
                    ),
                    user_id=row.user_id,
                    display_name=row.display_name,
                    picture_url=member_picture_url(
                        league_id, row.user_id, row.picture_blob_name, row.picture_url
                    ),
                )
                for row in rows[:limit]
            ],
            next_offset=offset + limit if len(rows) > limit else None,
        )


async def get_score_history(
    session: AsyncSession,
    viewer_id: int,
    league_id: int,
    member_id: int,
    before: date | None,
    limit: int,
) -> MemberScoreHistory:
    async with session.begin():
        await lock_league(session, viewer_id, league_id)
        target_exists = await session.scalar(
            sa.select(
                sa.exists().where(members.c.league_id == league_id, members.c.user_id == member_id)
            )
        )
        if not target_exists:
            raise LeagueNotFound
        query = (
            sa.select(
                daily.c.local_day,
                daily.c.round_id,
                rounds.c.start_at,
                rounds.c.end_at,
                daily.c.score,
                daily.c.session_id,
                daily.c.ended_at,
            )
            .join(rounds, rounds.c.id == daily.c.round_id)
            .where(daily.c.league_id == league_id, daily.c.user_id == member_id)
        )
        owner = viewer_id == member_id
        if owner:
            query = query.add_columns(*_CALCULATION_COLUMNS)
        if before is not None:
            query = query.where(daily.c.local_day < before)
        rows = (
            (await session.execute(query.order_by(daily.c.local_day.desc()).limit(limit + 1)))
            .mappings()
            .all()
        )
        items = [_score_item(row, owner=owner) for row in rows[:limit]]
        return MemberScoreHistory(
            items=items, next_before=items[-1].local_day if len(rows) > limit else None
        )
