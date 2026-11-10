"""Seed an idempotent three-month Exercise Evolution demo for one local account."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.features.training.models import exercise, exercise_set, session_exercise, training_session

USER_ID = 2
EXERCISE_ID = 191
MARKER = "codex-exercise-evolution-demo-v1"


async def seed(*, dry_run: bool) -> int:
    settings = Settings()
    engine = create_async_engine(settings.database_connection_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session, session.begin():
            owner = await session.scalar(
                sa.select(sa.literal(True))
                .select_from(sa.table("users", sa.column("id")))
                .where(sa.column("id") == USER_ID)
            )
            target = (
                await session.execute(
                    sa.select(exercise.c.activity_type).where(exercise.c.id == EXERCISE_ID)
                )
            ).scalar_one_or_none()
            if owner is None:
                raise SystemExit(f"User {USER_ID} does not exist in the configured database")
            if target is None:
                raise SystemExit(
                    f"Exercise {EXERCISE_ID} does not exist in the configured database"
                )
            if target != "gym":
                raise SystemExit(f"Exercise {EXERCISE_ID} is not a resistance exercise")

            existing = await session.scalar(
                sa.select(sa.func.count())
                .select_from(training_session)
                .where(
                    training_session.c.user_id == USER_ID,
                    training_session.c.notes.like(f"{MARKER}:%"),
                )
            )
            if existing:
                print(f"Demo data already exists ({existing} workouts); no records changed.")
                return 0
            if dry_run:
                print("Would create 12 completed demo workouts with 2 sets each.")
                return 12

            now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
            for index in range(12):
                ended_at = now - timedelta(days=7 * (11 - index))
                workout_id = await session.scalar(
                    training_session.insert()
                    .values(
                        user_id=USER_ID,
                        activity_type="gym",
                        started_at=ended_at - timedelta(minutes=45),
                        ended_at=ended_at,
                        notes=f"{MARKER}:{index + 1:02d}",
                    )
                    .returning(training_session.c.id)
                )
                slot_id = await session.scalar(
                    session_exercise.insert()
                    .values(session_id=workout_id, exercise_id=EXERCISE_ID, exercise_order=1)
                    .returning(session_exercise.c.id)
                )
                load = Decimal(35 + index * 2)
                values = [
                    {
                        "session_exercise_id": slot_id,
                        "set_number": 1,
                        "reps": 8,
                        "weight_kg": load,
                        "completed": True,
                    },
                    {
                        "session_exercise_id": slot_id,
                        "set_number": 2,
                        "reps": 10,
                        "weight_kg": load - Decimal(5),
                        "completed": True,
                    },
                ]
                await session.execute(exercise_set.insert(), values)
            print("Created 12 completed demo workouts (24 sets) for user 2, exercise 191.")
            return 12
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate targets without writing")
    args = parser.parse_args()
    asyncio.run(seed(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
