from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.service import get_profile, lock_active_user
from app.features.goals.errors import (
    FutureMeasurement,
    MeasurementRequestConflict,
    ObjectiveChanged,
)
from app.features.goals.measurement_records import append_measurement, profile_today
from app.features.goals.models import AccountObjective, body_measurement, physical_goal
from app.features.goals.progress_schemas import (
    MeasurementCreate,
    MeasurementHistory,
    MeasurementResponse,
    PhysicalTarget,
    PhysicalTargetPut,
    PhysicalTargetResponse,
)

WEIGHT_TARGET_METRIC = "weight_kg"


async def list_measurements(session: AsyncSession, user_id: int) -> MeasurementHistory:
    rows = (
        await session.execute(
            select(body_measurement)
            .where(body_measurement.c.user_id == user_id)
            .order_by(body_measurement.c.date, body_measurement.c.id)
        )
    ).mappings()
    return MeasurementHistory(items=[MeasurementResponse.model_validate(row) for row in rows])


async def create_measurement(
    session: AsyncSession, user_id: int, value: MeasurementCreate
) -> MeasurementResponse:
    try:
        await lock_active_user(session, user_id)
        columns = body_measurement.c
        saved = (
            (
                await session.execute(
                    select(body_measurement).where(
                        columns.user_id == user_id, columns.request_id == value.request_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if saved is not None:
            payload = value.model_dump(exclude={"request_id"})
            if any(saved[name] != item for name, item in payload.items()):
                raise MeasurementRequestConflict
            result = MeasurementResponse.model_validate(saved)
        else:
            profile = await get_profile(session, user_id)
            if value.date > profile_today(profile):
                raise FutureMeasurement
            row = await append_measurement(
                session, profile, value.date, value.measurements(), value.request_id
            )
            result = MeasurementResponse.model_validate(row)
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise


async def read_physical_target(session: AsyncSession, user_id: int) -> PhysicalTargetResponse:
    goal = physical_goal.c
    row = (
        await session.execute(
            select(AccountObjective.objective, goal.target_value, goal.target_date)
            .outerjoin(
                physical_goal,
                and_(
                    goal.user_id == AccountObjective.user_id,
                    goal.goal_type == AccountObjective.objective,
                    goal.target_metric == WEIGHT_TARGET_METRIC,
                ),
            )
            .where(AccountObjective.user_id == user_id)
        )
    ).one_or_none()
    if row is None:
        return PhysicalTargetResponse(objective=None, target=None)
    return PhysicalTargetResponse(
        objective=row.objective,
        target=(
            PhysicalTarget(weight_kg=row.target_value, target_date=row.target_date)
            if row.target_value is not None
            else None
        ),
    )


async def put_physical_target(
    session: AsyncSession, user_id: int, value: PhysicalTargetPut
) -> PhysicalTargetResponse:
    try:
        await lock_active_user(session, user_id)
        objective = await session.get(AccountObjective, user_id)
        if objective is None or value.objective != objective.objective:
            raise ObjectiveChanged
        profile = await get_profile(session, user_id)
        goal = physical_goal.c
        statement = insert(physical_goal).values(
            user_id=user_id,
            goal_type=value.objective,
            target_metric=WEIGHT_TARGET_METRIC,
            target_value=value.weight_kg,
            target_date=value.target_date,
            start_date=profile_today(profile),
        )
        row = (
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[goal.user_id, goal.goal_type, goal.target_metric],
                    set_={
                        goal.target_value: statement.excluded.target_value,
                        goal.target_date: statement.excluded.target_date,
                    },
                ).returning(goal.target_value, goal.target_date)
            )
        ).one()
        result = PhysicalTargetResponse(
            objective=value.objective,
            target=PhysicalTarget(weight_kg=row.target_value, target_date=row.target_date),
        )
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise
