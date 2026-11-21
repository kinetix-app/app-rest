from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.models import Profile
from app.features.goals.models import body_measurement

PROFILE_MEASUREMENT_FIELDS = ("height_cm", "weight_kg")


def profile_today(profile: Profile) -> date:
    return datetime.now(ZoneInfo(profile.timezone or "UTC")).date()


async def append_measurement(
    session: AsyncSession,
    profile: Profile,
    recorded_on: date,
    values: dict[str, Decimal],
    request_id: UUID | None = None,
) -> sa.RowMapping:
    """Append and sync inside the transaction holding the account row lock."""
    row = (
        (
            await session.execute(
                body_measurement.insert()
                .values(user_id=profile.user_id, date=recorded_on, request_id=request_id, **values)
                .returning(*body_measurement.c)
            )
        )
        .mappings()
        .one()
    )
    sync_fields = [name for name in PROFILE_MEASUREMENT_FIELDS if name in values]
    if sync_fields:
        newer = (
            await session.execute(
                sa.select(
                    *(
                        sa.func.bool_or(body_measurement.c[name].is_not(None))
                        for name in sync_fields
                    )
                ).where(
                    body_measurement.c.user_id == profile.user_id,
                    body_measurement.c.date > recorded_on,
                )
            )
        ).one()
        for name, has_newer_value in zip(sync_fields, newer, strict=True):
            if not has_newer_value:
                setattr(profile, name, values[name])
    return row
