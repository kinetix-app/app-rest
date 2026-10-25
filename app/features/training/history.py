"""Account-scoped latest nonempty exercise configurations shared by guidance APIs."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.training.models import exercise_set, session_exercise, training_session
from app.features.training.schemas import SetResponse, WeightResponse
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
