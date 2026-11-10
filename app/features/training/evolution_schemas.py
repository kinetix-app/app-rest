"""Public daily exercise evolution response."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.features.training.units import WeightUnit

DistanceUnit = Literal["km", "mi"]


class EvolutionDay(BaseModel):
    date: date
    estimated_1rm: Decimal | None = None
    weight: Decimal | None = None
    volume: Decimal | None = None
    reps: int | None = None
    distance: Decimal | None = None
    duration_seconds: int | None = None
    volume_partial: bool = False


class ExerciseEvolution(BaseModel):
    exercise_id: int
    activity_type: str
    weight_unit: WeightUnit
    distance_unit: DistanceUnit
    days: list[EvolutionDay]
