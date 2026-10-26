"""Atomic completed aggregates, owned history and deterministic retry recovery."""

import hashlib
import json
from datetime import UTC

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.models import User
from app.features.training.errors import IdempotencyConflict, InvalidSelection, TrainingNotFound
from app.features.training.models import (
    exercise,
    exercise_set,
    routine,
    session_draft,
    session_exercise,
    training_session,
)
from app.features.training.schemas import (
    DraftSnapshot,
    ExerciseResponse,
    SessionCreate,
    SessionExerciseResponse,
    SessionPage,
    SessionResponse,
    SetResponse,
    WeightResponse,
)
from app.features.training.service import selectable_exercise
from app.features.training.units import WeightUnit, canonical_weight, display_weight


def present_set(row, unit: WeightUnit) -> SetResponse:
    result = SetResponse.model_validate(row)
    if result.weight_kg is not None:
        result.weight = WeightResponse(value=display_weight(result.weight_kg, unit), unit=unit)
    return result


def normalized_payload(data: SessionCreate, *, legacy: bool = False) -> dict:
    return {
        "routine_id": data.routine_id,
        "started_at": data.started_at.astimezone(UTC).isoformat(),
        "ended_at": data.ended_at.astimezone(UTC).isoformat(),
        "exercises": [
            {
                "exercise_id": item.exercise_id,
                **({"routine_exercise_id": item.routine_exercise_id} if legacy else {}),
                "sets": [
                    {
                        "reps": value.reps,
                        "weight_kg": str(canonical_weight(value.weight.value, value.weight.unit)),
                    }
                    for value in item.sets
                ],
            }
            for item in data.exercises
        ],
    }


async def get_session(
    session: AsyncSession, user_id: int, session_id: int, unit: WeightUnit = "kg"
) -> SessionResponse:
    row = (
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
        .first()
    )
    if row is None:
        raise TrainingNotFound
    entries = (
        (
            await session.execute(
                sa.select(session_exercise)
                .where(session_exercise.c.session_id == session_id)
                .order_by(session_exercise.c.exercise_order, session_exercise.c.id)
            )
        )
        .mappings()
        .all()
    )
    # Historical visibility derives from the owned workout; catalogue visibility can change.
    exercises = {
        value["id"]: ExerciseResponse.model_validate(value)
        for value in (
            await session.execute(
                sa.select(exercise).where(
                    exercise.c.id.in_([entry["exercise_id"] for entry in entries])
                )
            )
        ).mappings()
    }
    sets = {}
    for value in (
        await session.execute(
            sa.select(exercise_set)
            .where(exercise_set.c.session_exercise_id.in_([entry["id"] for entry in entries]))
            .order_by(exercise_set.c.set_number, exercise_set.c.id)
        )
    ).mappings():
        sets.setdefault(value["session_exercise_id"], []).append(present_set(value, unit))
    return SessionResponse(
        **{
            key: row[key]
            for key in (
                "id",
                "client_session_id",
                "routine_id",
                "activity_type",
                "started_at",
                "ended_at",
            )
        },
        exercises=[
            SessionExerciseResponse(
                id=entry["id"],
                exercise_order=entry["exercise_order"],
                exercise=exercises[entry["exercise_id"]],
                sets=sets.get(entry["id"], []),
            )
            for entry in entries
        ],
    )


async def list_sessions(
    session: AsyncSession, user_id: int, limit: int, offset: int, unit: WeightUnit = "kg"
) -> SessionPage:
    ids = list(
        await session.scalars(
            sa.select(training_session.c.id)
            .where(training_session.c.user_id == user_id, training_session.c.ended_at.is_not(None))
            .order_by(training_session.c.ended_at.desc(), training_session.c.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return SessionPage(
        items=[await get_session(session, user_id, value, unit) for value in ids],
        limit=limit,
        offset=offset,
    )


async def validate_sources(
    session: AsyncSession, user_id: int, data: SessionCreate | DraftSnapshot
) -> None:
    if data.routine_id is not None:
        owner = await session.scalar(
            sa.select(routine.c.user_id)
            .where(routine.c.id == data.routine_id)
            .with_for_update(read=True)
        )
        if owner != user_id:
            raise InvalidSelection
    requested = {item.exercise_id for item in data.exercises}
    available = set(
        await session.scalars(
            sa.select(exercise.c.id).where(
                exercise.c.id.in_(requested), selectable_exercise(user_id)
            )
        )
    )
    if requested != available:
        raise InvalidSelection


def _accepted_session_fingerprints(data: SessionCreate) -> set[str]:
    payloads = (normalized_payload(data), normalized_payload(data, legacy=True))
    return {
        hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for payload in payloads
    }


async def _lock_user_without_active_draft(
    session: AsyncSession, user_id: int, client_session_id
) -> None:
    await session.execute(sa.select(User.id).where(User.id == user_id).with_for_update())
    active_draft = await session.scalar(
        sa.select(session_draft.c.id).where(
            session_draft.c.user_id == user_id,
            session_draft.c.client_session_id == client_session_id,
            session_draft.c.completed_session_id.is_(None),
        )
    )
    if active_draft:
        raise IdempotencyConflict


async def _find_session_by_client_id(session: AsyncSession, user_id: int, client_session_id):
    result = await session.execute(
        sa.select(training_session.c.id, training_session.c.payload_fingerprint).where(
            training_session.c.user_id == user_id,
            training_session.c.client_session_id == client_session_id,
        )
    )
    return result.mappings().first()


async def _completed_retry(
    session: AsyncSession,
    user_id: int,
    existing,
    accepted_fingerprints: set[str],
    unit: WeightUnit,
) -> SessionResponse:
    if existing["payload_fingerprint"] not in accepted_fingerprints:
        raise IdempotencyConflict
    return await get_session(session, user_id, existing["id"], unit)


async def _insert_session(
    session: AsyncSession, user_id: int, data: SessionCreate, fingerprint: str
) -> int | None:
    return await session.scalar(
        insert(training_session)
        .values(
            user_id=user_id,
            routine_id=data.routine_id,
            activity_type="gym",
            client_session_id=data.client_session_id,
            payload_fingerprint=fingerprint,
            started_at=data.started_at,
            ended_at=data.ended_at,
        )
        .on_conflict_do_nothing(
            index_elements=[training_session.c.user_id, training_session.c.client_session_id]
        )
        .returning(training_session.c.id)
    )


async def _insert_session_exercises(
    session: AsyncSession, session_id: int, data: SessionCreate
) -> None:
    for position, item in enumerate(data.exercises, 1):
        entry_id = await session.scalar(
            session_exercise.insert()
            .values(
                session_id=session_id,
                exercise_id=item.exercise_id,
                exercise_order=position,
            )
            .returning(session_exercise.c.id)
        )
        if item.sets:
            await session.execute(
                exercise_set.insert(),
                [
                    {
                        "session_exercise_id": entry_id,
                        "set_number": number,
                        "reps": value.reps,
                        "weight_kg": canonical_weight(value.weight.value, value.weight.unit),
                        "completed": True,
                    }
                    for number, value in enumerate(item.sets, 1)
                ],
            )


async def _concurrent_session_id(
    session: AsyncSession,
    user_id: int,
    data: SessionCreate,
    accepted_fingerprints: set[str],
) -> int:
    result = await session.execute(
        sa.select(training_session.c.id, training_session.c.payload_fingerprint).where(
            training_session.c.user_id == user_id,
            training_session.c.client_session_id == data.client_session_id,
        )
    )
    existing = result.mappings().one()
    if existing["payload_fingerprint"] not in accepted_fingerprints:
        raise IdempotencyConflict
    return existing["id"]


async def create_session(
    session: AsyncSession,
    user_id: int,
    data: SessionCreate,
    unit: WeightUnit = "kg",
    *,
    commit: bool = True,
) -> tuple[SessionResponse, bool]:
    accepted_fingerprints = _accepted_session_fingerprints(data)
    fingerprint = hashlib.sha256(
        json.dumps(normalized_payload(data), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    try:
        if commit:
            # Legacy submission cannot bypass an active snapshot's finish transition.
            await _lock_user_without_active_draft(session, user_id, data.client_session_id)
        # Check the key first: retries remain valid even after source templates/catalogue change.
        existing = await _find_session_by_client_id(session, user_id, data.client_session_id)
        if existing is not None:
            result = await _completed_retry(session, user_id, existing, accepted_fingerprints, unit)
            if commit:
                await session.commit()
            return result, False
        await validate_sources(session, user_id, data)
        identifier = await _insert_session(session, user_id, data, fingerprint)
        created = identifier is not None
        if identifier is None:
            identifier = await _concurrent_session_id(session, user_id, data, accepted_fingerprints)
        else:
            await _insert_session_exercises(session, identifier, data)
        result = await get_session(session, user_id, identifier, unit)
        if commit:
            await session.commit()
        return result, created
    except Exception:
        await session.rollback()
        raise
