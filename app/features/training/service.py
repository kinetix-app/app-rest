"""Owned routine transactions and catalogue queries."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.features.training.models import (
    exercise,
    exercise_set,
    routine,
    routine_exercise,
    routine_exercise_set,
    session_exercise,
    training_session,
)
from app.features.training.schemas import (
    BodyPartList,
    ExercisePage,
    ExerciseResponse,
    ExerciseSelection,
    ExerciseSummary,
    MuscleGroupList,
    PlannedSet,
    RoutineCreate,
    RoutineExerciseResponse,
    RoutinePage,
    RoutinePatch,
    RoutineResponse,
    RoutineSummary,
    SetResponse,
)


class TrainingNotFound(Exception):
    """Missing or inaccessible resource."""


class InvalidSelection(Exception):
    """An exercise or template slot is unavailable for this routine."""


def selectable_exercise(user_id: int) -> ColumnElement[bool]:
    # Nullable ownership is not publication. Only the explicit seed's global
    # catalogue and the current account's gym exercises are selectable.
    return sa.and_(
        exercise.c.activity_type == "gym",
        sa.or_(
            exercise.c.user_id == user_id,
            sa.and_(
                exercise.c.user_id.is_(None),
                exercise.c.source == "ascend_edb_v2",
                exercise.c.external_id.is_not(None),
                exercise.c.imported_at.is_not(None),
            ),
        ),
    )


async def list_exercises(
    session: AsyncSession,
    user_id: int,
    limit: int,
    offset: int,
    muscle_group: str | None,
    name: str | None = None,
    body_part: Sequence[str] | str | None = None,
) -> ExercisePage:
    # Project only list-card data; instructions/media variants remain in detail.
    query = sa.select(*(exercise.c[key] for key in ExerciseSummary.model_fields)).where(
        selectable_exercise(user_id)
    )
    if name and name.strip():
        query = query.where(exercise.c.name.icontains(name.strip(), autoescape=True))
    parts = [body_part] if isinstance(body_part, str) else (body_part or [])
    for column, values in (
        (exercise.c.target_muscles, [muscle_group] if muscle_group else []),
        (exercise.c.body_parts, parts),
    ):
        selected = sorted({value.strip().lower() for value in values if value.strip()})
        if selected:
            category = sa.func.unnest(column).table_valued("value").render_derived()
            query = query.where(
                sa.exists(
                    sa.select(1)
                    .select_from(category)
                    .where(sa.func.lower(sa.func.trim(category.c.value)).in_(selected))
                )
            )
    rows = (
        await session.execute(query.order_by(exercise.c.id).limit(limit).offset(offset))
    ).mappings()
    return ExercisePage(
        items=[ExerciseSummary.model_validate(row) for row in rows], limit=limit, offset=offset
    )


async def _catalogue_options(session: AsyncSession, user_id: int, field: str) -> list[str]:
    visible = (
        sa.select(exercise.c[field].label("categories"))
        .where(selectable_exercise(user_id))
        .subquery()
    )
    category = sa.func.unnest(visible.c.categories).table_valued("value").render_derived()
    label = sa.func.trim(category.c.value)
    query = (
        sa.select(label)
        .select_from(visible.join(category, sa.true()))
        .where(label != "")
        .distinct()
        .order_by(label)
    )
    return list(await session.scalars(query))


async def list_muscle_groups(session: AsyncSession, user_id: int) -> MuscleGroupList:
    return MuscleGroupList(items=await _catalogue_options(session, user_id, "target_muscles"))


async def list_body_parts(session: AsyncSession, user_id: int) -> BodyPartList:
    return BodyPartList(items=await _catalogue_options(session, user_id, "body_parts"))


async def get_exercise(session: AsyncSession, user_id: int, exercise_id: int) -> ExerciseResponse:
    row = (
        (
            await session.execute(
                sa.select(exercise).where(
                    exercise.c.id == exercise_id, selectable_exercise(user_id)
                )
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise TrainingNotFound
    return ExerciseResponse.model_validate(row)


async def list_routines(
    session: AsyncSession, user_id: int, limit: int, offset: int, name: str | None = None
) -> RoutinePage:
    query = sa.select(routine.c.id, routine.c.name).where(routine.c.user_id == user_id)
    if name and name.strip():
        query = query.where(routine.c.name.icontains(name.strip(), autoescape=True))
    rows = (
        await session.execute(query.order_by(routine.c.id).limit(limit).offset(offset))
    ).mappings()
    return RoutinePage(
        items=[RoutineSummary.model_validate(row) for row in rows], limit=limit, offset=offset
    )


async def get_routine(session: AsyncSession, user_id: int, routine_id: int) -> RoutineResponse:
    # Keep the template consistent across the batched reads while updates lock its parent.
    owner_row = (
        (
            await session.execute(
                sa.select(routine)
                .where(routine.c.id == routine_id, routine.c.user_id == user_id)
                .with_for_update(read=True)
            )
        )
        .mappings()
        .first()
    )
    if owner_row is None:
        raise TrainingNotFound
    slots = (
        (
            await session.execute(
                sa.select(routine_exercise)
                .where(routine_exercise.c.routine_id == routine_id)
                .order_by(routine_exercise.c.exercise_order, routine_exercise.c.id)
            )
        )
        .mappings()
        .all()
    )
    ids = [slot["id"] for slot in slots]
    exercises = {
        row["id"]: ExerciseResponse.model_validate(row)
        for row in (
            await session.execute(
                sa.select(exercise).where(
                    exercise.c.id.in_([slot["exercise_id"] for slot in slots]),
                    selectable_exercise(user_id),
                )
            )
        ).mappings()
    }
    if any(slot["exercise_id"] not in exercises for slot in slots):
        raise TrainingNotFound
    defaults: dict[int, list[SetResponse]] = {}
    for row in (
        await session.execute(
            sa.select(routine_exercise_set)
            .where(routine_exercise_set.c.routine_exercise_id.in_(ids))
            .order_by(routine_exercise_set.c.set_number, routine_exercise_set.c.id)
        )
    ).mappings():
        defaults.setdefault(row["routine_exercise_id"], []).append(SetResponse.model_validate(row))
    latest = await session.scalar(
        sa.select(training_session.c.id)
        .where(
            training_session.c.user_id == user_id,
            training_session.c.routine_id == routine_id,
            training_session.c.ended_at.is_not(None),
        )
        .order_by(training_session.c.ended_at.desc(), training_session.c.id.desc())
        .limit(1)
    )
    previous: dict[tuple[int, int], list[SetResponse]] = {}
    if latest is not None:
        # Mark matching entries even when they have zero sets; do not merge older workouts.
        entries = (
            (
                await session.execute(
                    sa.select(session_exercise).where(
                        session_exercise.c.session_id == latest,
                        session_exercise.c.routine_exercise_id.in_(ids),
                    )
                )
            )
            .mappings()
            .all()
        )
        keys = {
            entry["id"]: (entry["routine_exercise_id"], entry["exercise_id"]) for entry in entries
        }
        previous = {key: [] for key in keys.values()}
        for row in (
            await session.execute(
                sa.select(exercise_set)
                .where(exercise_set.c.session_exercise_id.in_(keys))
                .order_by(exercise_set.c.set_number, exercise_set.c.id)
            )
        ).mappings():
            previous[keys[row["session_exercise_id"]]].append(SetResponse.model_validate(row))
    return RoutineResponse(
        id=owner_row["id"],
        name=owner_row["name"],
        exercises=[
            RoutineExerciseResponse(
                id=slot["id"],
                exercise_order=slot["exercise_order"],
                exercise=exercises[slot["exercise_id"]],
                notes=slot["notes"],
                default_sets=defaults.get(slot["id"], []),
                sets=previous.get((slot["id"], slot["exercise_id"]), defaults.get(slot["id"], [])),
                sets_source="latest_session"
                if (slot["id"], slot["exercise_id"]) in previous
                else "routine",
            )
            for slot in slots
        ],
    )


async def validate_exercises(
    session: AsyncSession, user_id: int, selections: Sequence[ExerciseSelection]
) -> None:
    requested = {item.exercise_id for item in selections}
    available = set(
        await session.scalars(
            sa.select(exercise.c.id).where(
                exercise.c.id.in_(requested), selectable_exercise(user_id)
            )
        )
    )
    if requested != available:
        raise InvalidSelection


async def create_routine(
    session: AsyncSession, user_id: int, data: RoutineCreate
) -> RoutineResponse:
    try:
        await validate_exercises(session, user_id, data.exercises)
        routine_id = await session.scalar(
            routine.insert().values(user_id=user_id, name=data.name).returning(routine.c.id)
        )
        for position, item in enumerate(data.exercises, 1):
            slot_id = await session.scalar(
                routine_exercise.insert()
                .values(
                    routine_id=routine_id, exercise_id=item.exercise_id, exercise_order=position
                )
                .returning(routine_exercise.c.id)
            )
            await replace_sets(session, slot_id, item.sets or [])
        response = await get_routine(session, user_id, routine_id)
        await session.commit()
        return response
    except Exception:
        await session.rollback()
        raise


async def update_routine(
    session: AsyncSession, user_id: int, routine_id: int, data: RoutinePatch
) -> RoutineResponse:
    try:
        found = await session.scalar(
            sa.select(routine.c.id)
            .where(routine.c.id == routine_id, routine.c.user_id == user_id)
            .with_for_update()
        )
        if found is None:
            raise TrainingNotFound
        if data.exercises is not None:
            await validate_exercises(session, user_id, data.exercises)
            existing = {
                row["id"]: row
                for row in (
                    await session.execute(
                        sa.select(routine_exercise).where(
                            routine_exercise.c.routine_id == routine_id
                        )
                    )
                ).mappings()
            }
            retained = {item.id for item in data.exercises if item.id is not None}
            if not retained.issubset(existing):
                raise InvalidSelection
            removed = existing.keys() - retained
            # Delete defaults before their parent; historical links use ON DELETE SET NULL.
            await session.execute(
                sa.delete(routine_exercise_set).where(
                    routine_exercise_set.c.routine_exercise_id.in_(removed)
                )
            )
            await session.execute(
                sa.delete(routine_exercise).where(routine_exercise.c.id.in_(removed))
            )
            for position, item in enumerate(data.exercises, 1):
                values = {"exercise_id": item.exercise_id, "exercise_order": position}
                if item.id is None:
                    slot_id = await session.scalar(
                        routine_exercise.insert()
                        .values(routine_id=routine_id, **values)
                        .returning(routine_exercise.c.id)
                    )
                    await replace_sets(session, slot_id, item.sets or [])
                else:
                    if existing[item.id]["exercise_id"] != item.exercise_id:
                        await session.execute(
                            sa.delete(routine_exercise_set).where(
                                routine_exercise_set.c.routine_exercise_id == item.id
                            )
                        )
                    await session.execute(
                        sa.update(routine_exercise)
                        .where(routine_exercise.c.id == item.id)
                        .values(**values)
                    )
                    if item.sets is not None:
                        await replace_sets(session, item.id, item.sets)
        if data.name is not None:
            await session.execute(
                sa.update(routine).where(routine.c.id == routine_id).values(name=data.name)
            )
        response = await get_routine(session, user_id, routine_id)
        await session.commit()
        return response
    except Exception:
        await session.rollback()
        raise


async def replace_sets(session: AsyncSession, slot_id: int, sets: Sequence[PlannedSet]) -> None:
    await session.execute(
        sa.delete(routine_exercise_set).where(routine_exercise_set.c.routine_exercise_id == slot_id)
    )
    if sets:
        await session.execute(
            routine_exercise_set.insert(),
            [
                {
                    "routine_exercise_id": slot_id,
                    "set_number": number,
                    "reps": item.reps,
                    "weight_kg": item.weight_kg,
                }
                for number, item in enumerate(sets, 1)
            ],
        )
