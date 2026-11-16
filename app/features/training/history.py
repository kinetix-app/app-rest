"""Account-scoped latest nonempty exercise configurations shared by guidance APIs."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.training.models import exercise_set, routine, session_exercise, training_session
from app.features.training.schemas import (
    ExerciseHistoryItem,
    ExerciseHistoryPage,
    SetResponse,
    WeightResponse,
)
from app.features.training.units import WeightUnit, display_weight


async def last_configurations(
    session: AsyncSession, user_id: int, exercise_ids: list[int], unit: WeightUnit = "kg"
) -> dict[int, list[SetResponse]]:
    if not exercise_ids:
        return {}
    entries = (
        (
            await session.execute(
                sa.select(session_exercise.c.exercise_id, session_exercise.c.id)
                .join(training_session, training_session.c.id == session_exercise.c.session_id)
                .where(
                    training_session.c.user_id == user_id,
                    training_session.c.ended_at.is_not(None),
                    session_exercise.c.exercise_id.in_(exercise_ids),
                    sa.exists(
                        sa.select(1).where(
                            exercise_set.c.session_exercise_id == session_exercise.c.id
                        )
                    ),
                )
                .ext(distinct_on(session_exercise.c.exercise_id))
                .order_by(
                    session_exercise.c.exercise_id,
                    training_session.c.ended_at.desc(),
                    training_session.c.id.desc(),
                    session_exercise.c.exercise_order.desc(),
                    session_exercise.c.id.desc(),
                )
            )
        )
        .mappings()
        .all()
    )
    by_entry = {row["id"]: row["exercise_id"] for row in entries}
    result: dict[int, list[SetResponse]] = {row["exercise_id"]: [] for row in entries}
    if by_entry:
        for row in (
            await session.execute(
                sa.select(exercise_set)
                .where(exercise_set.c.session_exercise_id.in_(by_entry))
                .order_by(exercise_set.c.set_number, exercise_set.c.id)
            )
        ).mappings():
            value = SetResponse.model_validate(row)
            if value.weight_kg is not None:
                value.weight = WeightResponse(
                    value=display_weight(value.weight_kg, unit), unit=unit
                )
            result[by_entry[row["session_exercise_id"]]].append(value)
    return result


async def exercise_history(
    session: AsyncSession,
    user_id: int,
    exercise_id: int,
    activity_type: str,
    limit: int,
    offset: int,
    unit: WeightUnit,
) -> ExerciseHistoryPage:
    matching_entry = sa.exists(
        sa.select(1).where(
            session_exercise.c.session_id == training_session.c.id,
            session_exercise.c.exercise_id == exercise_id,
        )
    )
    rows = (
        (
            await session.execute(
                sa.select(
                    training_session.c.id,
                    training_session.c.started_at,
                    training_session.c.ended_at,
                    routine.c.name.label("routine_name"),
                )
                .outerjoin(
                    routine,
                    sa.and_(
                        routine.c.id == training_session.c.routine_id, routine.c.user_id == user_id
                    ),
                )
                .where(
                    training_session.c.user_id == user_id,
                    training_session.c.ended_at.is_not(None),
                    matching_entry,
                )
                .order_by(training_session.c.ended_at.desc(), training_session.c.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .mappings()
        .all()
    )
    ids = [row["id"] for row in rows]
    by_session: dict[int, list[SetResponse]] = {id_: [] for id_ in ids}
    if ids:
        sets = (
            await session.execute(
                sa.select(session_exercise.c.session_id, exercise_set)
                .join(exercise_set, exercise_set.c.session_exercise_id == session_exercise.c.id)
                .where(
                    session_exercise.c.session_id.in_(ids),
                    session_exercise.c.exercise_id == exercise_id,
                )
                .order_by(
                    session_exercise.c.session_id,
                    session_exercise.c.exercise_order,
                    session_exercise.c.id,
                    exercise_set.c.set_number,
                    exercise_set.c.id,
                )
            )
        ).mappings()
        for row in sets:
            value = SetResponse.model_validate(row)
            if value.weight_kg is not None:
                value.weight = WeightResponse(
                    value=display_weight(value.weight_kg, unit), unit=unit
                )
            by_session[row["session_id"]].append(value)
    return ExerciseHistoryPage(
        items=[
            ExerciseHistoryItem(
                session_id=row["id"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                name=row["routine_name"] or "Workout",
                activity_type=activity_type,
                sets=by_session[row["id"]],
            )
            for row in rows
        ],
        limit=limit,
        offset=offset,
    )
