"""Owned resumable snapshots and atomic transition to immutable workout history."""

from datetime import UTC
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.models import User
from app.features.training import sessions
from app.features.training.models import routine, session_draft, training_session
from app.features.training.schemas import (
    DraftFinish,
    DraftResponse,
    DraftSnapshot,
    SessionCreate,
    SessionResponse,
)
from app.features.training.service import (
    InvalidSelection,
    TrainingNotFound,
    replace_routine_from_session,
)
from app.features.training.units import WeightUnit


async def lock_account(session: AsyncSession, user_id: int):
    # Serialize different UUIDs as well as concurrent save/finish/discard operations.
    await session.execute(sa.select(User.id).where(User.id == user_id).with_for_update())


async def find_draft(session: AsyncSession, user_id: int, key: UUID):
    return (
        (
            await session.execute(
                sa.select(session_draft).where(
                    session_draft.c.user_id == user_id,
                    session_draft.c.client_session_id == key,
                )
            )
        )
        .mappings()
        .first()
    )


def present(row) -> DraftResponse:
    return DraftResponse(**row["snapshot"], client_session_id=row["client_session_id"])


async def latest_draft(session: AsyncSession, user_id: int) -> DraftResponse | None:
    row = (
        (
            await session.execute(
                sa.select(session_draft).where(
                    session_draft.c.user_id == user_id,
                    session_draft.c.completed_session_id.is_(None),
                )
            )
        )
        .mappings()
        .first()
    )
    return present(row) if row is not None else None


async def save_draft(
    session: AsyncSession, user_id: int, key: UUID, data: DraftSnapshot
) -> DraftResponse:
    snapshot = data.model_dump(mode="json")
    snapshot["started_at"] = data.started_at.astimezone(UTC).isoformat()
    try:
        await lock_account(session, user_id)
        row = await find_draft(session, user_id, key)
        if row is not None:
            if row["completed_session_id"] is not None:
                raise sessions.IdempotencyConflict
            if row["snapshot"] == snapshot:
                result = present(row)
                await session.commit()
                return result
            original = DraftSnapshot.model_validate(row["snapshot"])
            if original.started_at != data.started_at or original.routine_id != data.routine_id:
                raise sessions.IdempotencyConflict
        else:
            if await session.scalar(
                sa.select(session_draft.c.id).where(
                    session_draft.c.user_id == user_id,
                    session_draft.c.completed_session_id.is_(None),
                )
            ) or await session.scalar(
                sa.select(training_session.c.id).where(
                    training_session.c.user_id == user_id,
                    training_session.c.client_session_id == key,
                )
            ):
                raise sessions.IdempotencyConflict
        # Validate private catalogue access and session-level routine origin before saving.
        await sessions.validate_sources(session, user_id, data)
        if row is None:
            await session.execute(
                session_draft.insert().values(
                    user_id=user_id, client_session_id=key, snapshot=snapshot
                )
            )
        else:
            await session.execute(
                session_draft.update()
                .where(session_draft.c.id == row["id"])
                .values(snapshot=snapshot)
            )
        await session.commit()
        return DraftResponse(**snapshot, client_session_id=key)
    except Exception:
        await session.rollback()
        raise


async def discard_draft(session: AsyncSession, user_id: int, key: UUID):
    try:
        await lock_account(session, user_id)
        row = await find_draft(session, user_id, key)
        if row is not None:
            if row["completed_session_id"] is not None:
                raise sessions.IdempotencyConflict
            await session.execute(session_draft.delete().where(session_draft.c.id == row["id"]))
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def finish_draft(
    session: AsyncSession,
    user_id: int,
    key: UUID,
    data: DraftFinish,
    unit: WeightUnit = "kg",
) -> SessionResponse:
    try:
        await lock_account(session, user_id)
        row = await find_draft(session, user_id, key)
        if row is None:
            raise TrainingNotFound
        if row["completed_session_id"] is not None:
            result = await sessions.get_session(session, user_id, row["completed_session_id"], unit)
            if (
                result.ended_at != data.ended_at
                or row["finish_update_routine"] != data.update_routine
            ):
                raise sessions.IdempotencyConflict
            await session.commit()
            return result
        snapshot = DraftSnapshot.model_validate(row["snapshot"])
        if data.ended_at < snapshot.started_at or (
            data.update_routine and (snapshot.routine_id is None or not snapshot.exercises)
        ):
            raise InvalidSelection
        if data.update_routine:
            # Acquire the write lock before source validation's shared lock. This
            # prevents lock-upgrade deadlocks with concurrent routine PATCH calls.
            origin = await session.scalar(
                sa.select(routine.c.id)
                .where(routine.c.id == snapshot.routine_id, routine.c.user_id == user_id)
                .with_for_update()
            )
            if origin is None:
                raise InvalidSelection
        # A completed snapshot contains only explicitly confirmed measurements.
        snapshot = snapshot.model_copy(
            update={
                "exercises": [
                    item.model_copy(
                        update={"sets": [value for value in item.sets if value.completed]}
                    )
                    for item in snapshot.exercises
                ]
            }
        )
        completed = SessionCreate(
            client_session_id=key,
            routine_id=snapshot.routine_id,
            started_at=snapshot.started_at,
            ended_at=data.ended_at,
            exercises=[
                {
                    "exercise_id": item.exercise_id,
                    "sets": [{"reps": value.reps, "weight": value.weight} for value in item.sets],
                }
                for item in snapshot.exercises
            ],
        )
        result, _ = await sessions.create_session(session, user_id, completed, unit, commit=False)
        if data.update_routine:
            await replace_routine_from_session(session, user_id, result)
        await session.execute(
            session_draft.update()
            .where(session_draft.c.id == row["id"])
            .values(
                completed_session_id=result.id,
                finish_update_routine=data.update_routine,
                snapshot=snapshot.model_dump(mode="json"),
            )
        )
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise
