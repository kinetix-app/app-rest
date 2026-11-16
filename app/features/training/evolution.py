"""Read-only daily aggregates over completed, owned exercise sets."""

from collections import defaultdict
from datetime import UTC
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.training.evolution_schemas import DistanceUnit, EvolutionDay, ExerciseEvolution
from app.features.training.models import exercise_set, session_exercise, training_session
from app.features.training.units import KG_PER_LB, WeightUnit

KM_PER_MILE = Decimal("1.609344")


def _display(value: Decimal | None, divisor: Decimal, quantum: str) -> Decimal | None:
    return (
        None
        if value is None
        else (value / divisor).quantize(Decimal(quantum), rounding=ROUND_HALF_UP)
    )


def aggregate(
    rows: list[Any], activity_type: str, weight_unit: WeightUnit, distance_unit: DistanceUnit
) -> list[EvolutionDay]:
    days: dict[Any, list[Any]] = defaultdict(list)
    for row in rows:
        days[row["ended_at"].astimezone(UTC).date()].append(row)
    result = []
    for day, sets in sorted(days.items()):
        weights: list[Decimal] = []
        reps: list[int] = []
        estimates: list[Decimal] = []
        volumes: list[Decimal] = []
        distances: list[Decimal] = []
        durations: list[int] = []
        partial = False
        for row in sets:
            weight, count = row["weight_kg"], row["reps"]
            if activity_type == "gym":
                valid_weight = weight is not None and weight.is_finite() and weight > 0
                valid_reps = count is not None and count > 0
                if valid_weight:
                    weights.append(weight)
                if valid_reps:
                    reps.append(count)
                if valid_weight and valid_reps:
                    volumes.append(weight * count)
                    if count <= 10:
                        estimates.append(
                            weight if count == 1 else weight * (1 + Decimal(count) / 30)
                        )
                else:
                    partial = True
            else:
                distance, duration = row["distance_km"], row["duration_seconds"]
                if distance is not None and distance.is_finite() and distance > 0:
                    distances.append(distance)
                if duration is not None and duration >= 0:
                    durations.append(duration)
        divisor = KG_PER_LB if weight_unit == "lb" else Decimal(1)
        result.append(
            EvolutionDay(
                date=day,
                estimated_1rm=_display(max(estimates, default=None), divisor, "0.1"),
                weight=_display(max(weights, default=None), divisor, "0.1"),
                volume=_display(sum(volumes) if volumes else None, divisor, "0.1"),
                reps=max(reps, default=None),
                distance=_display(
                    max(distances, default=None),
                    KM_PER_MILE if distance_unit == "mi" else Decimal(1),
                    "0.01",
                ),
                duration_seconds=max(durations, default=None),
                volume_partial=partial,
            )
        )
    return result


async def exercise_evolution(
    session: AsyncSession,
    user_id: int,
    exercise_id: int,
    activity_type: str,
    weight_unit: WeightUnit,
    distance_unit: DistanceUnit,
) -> ExerciseEvolution:
    rows = (
        (
            await session.execute(
                sa.select(
                    training_session.c.ended_at,
                    exercise_set.c.weight_kg,
                    exercise_set.c.reps,
                    exercise_set.c.distance_km,
                    exercise_set.c.duration_seconds,
                )
                .select_from(
                    training_session.join(
                        session_exercise, session_exercise.c.session_id == training_session.c.id
                    ).join(
                        exercise_set, exercise_set.c.session_exercise_id == session_exercise.c.id
                    )
                )
                .where(
                    training_session.c.user_id == user_id,
                    training_session.c.ended_at.is_not(None),
                    session_exercise.c.exercise_id == exercise_id,
                    exercise_set.c.completed.is_(True),
                )
            )
        )
        .mappings()
        .all()
    )
    return ExerciseEvolution(
        exercise_id=exercise_id,
        activity_type=activity_type,
        weight_unit=weight_unit,
        distance_unit=distance_unit,
        days=aggregate(rows, activity_type, weight_unit, distance_unit),
    )
