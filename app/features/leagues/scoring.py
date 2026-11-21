"""Snapshot completed session inputs and credit one winner per local day.

Caller holds the account lock and owns the transaction. League locks are acquired
in ascending ID order; round closure uses the same lock.
"""

from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.models import Profile
from app.features.leagues.calculation import (
    FORMULA_VERSION,
    calculate_score,
    elapsed_microseconds,
    local_day,
    weekly_bounds,
)
from app.features.leagues.models import league, league_member, league_round, league_score
from app.features.training.models import exercise, exercise_set, session_exercise, training_session


async def ensure_round(session: AsyncSession, league_row, instant: datetime):
    """Find/create the source week; caller must hold the league row lock."""
    start, end = weekly_bounds(instant, league_row.timezone)
    await session.execute(
        insert(league_round)
        .values(league_id=league_row.id, start_at=start, end_at=end)
        .on_conflict_do_nothing(index_elements=["league_id", "start_at"])
    )
    return (
        (
            await session.execute(
                sa.select(league_round).where(
                    league_round.c.league_id == league_row.id,
                    league_round.c.start_at == start,
                )
            )
        )
        .mappings()
        .one()
    )


async def credit_completed_session(
    session: AsyncSession, user_id: int, session_id: int, now: datetime | None = None
) -> None:
    """Create one immutable snapshot and, while eligible, update daily winners."""
    source = (
        (
            await session.execute(
                sa.select(training_session).where(
                    training_session.c.id == session_id,
                    training_session.c.user_id == user_id,
                    training_session.c.ended_at.is_not(None),
                )
            )
        )
        .mappings()
        .one()
    )
    # Formula version, rather than score, marks processed ineligible sessions too.
    if source.league_formula_version is not None:
        return
    volume = await session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(exercise_set.c.reps * exercise_set.c.weight_kg), 0))
        .select_from(exercise_set.join(session_exercise).join(exercise))
        .where(
            session_exercise.c.session_id == session_id,
            exercise.c.activity_type == "gym",
            exercise_set.c.completed.is_(True),
            exercise_set.c.reps > 0,
            exercise_set.c.weight_kg > 0,
        )
    )
    volume = Decimal(volume)
    weight = await session.scalar(sa.select(Profile.weight_kg).where(Profile.user_id == user_id))
    duration = elapsed_microseconds(source.started_at, source.ended_at)
    score = (
        calculate_score(volume, duration, weight)
        if source.activity_type == "gym" and weight is not None
        else None
    )
    updated = await session.scalar(
        training_session.update()
        .where(
            training_session.c.id == session_id,
            training_session.c.user_id == user_id,
            training_session.c.league_formula_version.is_(None),
        )
        .values(
            league_score=score,
            league_volume_kg_reps=volume,
            league_duration_us=duration,
            league_body_weight_kg=weight,
            league_formula_version=FORMULA_VERSION,
        )
        .returning(training_session.c.id)
    )
    if updated is None or score is None:
        return
    leagues = (
        (
            await session.execute(
                sa.select(league.c.id, league.c.timezone)
                .join(league_member, league_member.c.league_id == league.c.id)
                .where(
                    league_member.c.user_id == user_id,
                    league_member.c.joined_at.is_not(None),
                    league_member.c.joined_at <= source.started_at,
                    league.c.timezone.is_not(None),
                )
                .order_by(league.c.id)
                .with_for_update(of=league)
            )
        )
        .mappings()
        .all()
    )
    for league_row in leagues:
        start, end = weekly_bounds(source.started_at, league_row.timezone)
        submitted_at = now if now is not None else datetime.now(UTC)
        if not (start <= submitted_at < end and source.ended_at < end):
            continue
        round_row = await ensure_round(session, league_row, source.started_at)
        values = {
            "league_id": league_row.id,
            "user_id": user_id,
            "local_day": local_day(source.started_at, league_row.timezone),
            "round_id": round_row.id,
            "session_id": session_id,
            "score": score,
            "volume_kg_reps": volume,
            "duration_us": duration,
            "body_weight_kg": weight,
            "ended_at": source.ended_at,
            "formula_version": FORMULA_VERSION,
        }
        statement = insert(league_score).values(**values)
        excluded = statement.excluded
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["league_id", "user_id", "local_day"],
                set_={
                    key: getattr(excluded, key)
                    for key in values
                    if key not in ("league_id", "user_id", "local_day")
                },
                where=sa.or_(
                    excluded.score > league_score.c.score,
                    sa.and_(
                        excluded.score == league_score.c.score,
                        sa.or_(
                            excluded.ended_at < league_score.c.ended_at,
                            sa.and_(
                                excluded.ended_at == league_score.c.ended_at,
                                excluded.session_id < league_score.c.session_id,
                            ),
                        ),
                    ),
                ),
            )
        )
