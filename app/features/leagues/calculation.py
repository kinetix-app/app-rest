"""Approved fixed league formula and local calendar (version 1).

Inputs use kg, repetitions and elapsed microseconds, including pauses. Only the
final score is rounded, to an integer with Decimal ROUND_HALF_UP. No float math.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from zoneinfo import ZoneInfo

FORMULA_VERSION = "gym-volume-elapsed-profile-v1-integer"


def weekly_bounds(instant: datetime, timezone: str) -> tuple[datetime, datetime]:
    """Monday inclusive to next Monday exclusive; preserve local DST transitions."""
    zone = ZoneInfo(timezone)
    day = instant.astimezone(zone).date()
    monday = day - timedelta(days=day.weekday())
    return (
        datetime.combine(monday, time.min, zone).astimezone(UTC),
        datetime.combine(monday + timedelta(days=7), time.min, zone).astimezone(UTC),
    )


def local_day(instant: datetime, timezone: str) -> date:
    return instant.astimezone(ZoneInfo(timezone)).date()


def elapsed_microseconds(start: datetime, end: datetime) -> int:
    elapsed = end.astimezone(UTC) - start.astimezone(UTC)
    return (elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


def calculate_score(
    volume_kg_reps: Decimal, duration_us: int, body_weight_kg: Decimal
) -> int | None:
    """Missing/nonpositive inputs are ineligible, rather than synthetic zero credit."""
    if (
        not volume_kg_reps.is_finite()
        or not body_weight_kg.is_finite()
        or volume_kg_reps <= 0
        or duration_us <= 0
        or body_weight_kg <= 0
    ):
        return None
    with localcontext() as context:
        context.prec = 60
        score = volume_kg_reps * Decimal(duration_us) / Decimal(3_600_000_000) / body_weight_kg
        return int(score.quantize(Decimal(1), rounding=ROUND_HALF_UP))
