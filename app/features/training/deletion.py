"""Owned routine retirement keeps completed history and excludes active draft sources."""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage.azure import BlobStorage
from app.features.training.drafts import lock_account
from app.features.training.errors import RoutineInUse, TrainingNotFound
from app.features.training.models import routine, session_draft
from app.features.training.pictures import _cleanup, _prefix


async def delete_routine(
    session: AsyncSession, user_id: int, routine_id: int, storage: BlobStorage | None
) -> None:
    previous = None
    try:
        # Match draft save/finish/discard and legacy completion lock order. The
        # parent write lock also serializes against shared source validation locks.
        await lock_account(session, user_id)
        row = (
            await session.execute(
                sa.select(routine.c.deleted_at, routine.c.picture_blob_name)
                .where(routine.c.id == routine_id, routine.c.user_id == user_id)
                .with_for_update()
            )
        ).first()
        if row is None:
            raise TrainingNotFound
        if row.deleted_at is not None:
            await session.commit()
            return
        active = await session.scalar(
            sa.select(session_draft.c.id).where(
                session_draft.c.user_id == user_id,
                session_draft.c.completed_session_id.is_(None),
                session_draft.c.snapshot["routine_id"].astext == str(routine_id),
            )
        )
        if active is not None:
            raise RoutineInUse
        previous = row.picture_blob_name
        await session.execute(
            sa.update(routine)
            .where(routine.c.id == routine_id)
            .values(deleted_at=datetime.now(UTC), picture_blob_name=None)
        )
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    # Deletion remains successful when the provider is absent or unavailable.
    await _cleanup(storage, previous, _prefix(user_id, routine_id))
