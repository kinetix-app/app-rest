"""Daily evolution calculations retain precision until display."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.features.training.evolution import aggregate


def row(weight=None, reps=None, distance=None, duration=None, at=None):
    return {
        "ended_at": at or datetime(2026, 1, 1, tzinfo=UTC),
        "weight_kg": Decimal(weight) if weight else None,
        "reps": reps,
        "distance_km": Decimal(distance) if distance else None,
        "duration_seconds": duration,
    }


def test_gym_daily_aggregation_rounding_and_partial_sets():
    days = aggregate(
        [
            row("60", 5),
            row("40", 10),
            row("70", 1),
            row("80", 11),
            row(None, 20),
            row("1.05", 2, at=datetime(2026, 1, 2, tzinfo=UTC)),
        ],
        "gym",
        "kg",
        "km",
    )
    assert len(days) == 2
    assert (
        days[0].estimated_1rm,
        days[0].weight,
        days[0].volume,
        days[0].reps,
        days[0].volume_partial,
    ) == (Decimal("70.0"), Decimal("80.0"), Decimal("1650.0"), 20, True)
    assert days[1].weight == Decimal("1.1")
    assert days[1].estimated_1rm == Decimal("1.1")


def test_units_utc_and_independent_cardio_measures():
    at = datetime(2026, 1, 2, 0, 30, tzinfo=UTC) - timedelta(hours=1)
    days = aggregate(
        [row(distance="1.609344", duration=30, at=at), row(distance="1", duration=90, at=at)],
        "cardio",
        "lb",
        "mi",
    )
    assert str(days[0].date) == "2026-01-01"
    assert (days[0].distance, days[0].duration_seconds) == (Decimal("1.00"), 90)
    assert days[0].weight is None
    assert aggregate([], "gym", "kg", "km") == []
    assert aggregate([row("0.45359237", 1)], "gym", "lb", "km")[0].weight == Decimal("1.0")


@pytest.mark.parametrize(
    ("weight", "reps", "expected"),
    [("60", 1, "60.0"), ("60", 2, "64.0"), ("40", 10, "53.3"), ("60", 11, None)],
)
def test_estimate_eligibility_boundaries(weight, reps, expected):
    source = [row(weight, reps)]
    original = deepcopy(source)
    day = aggregate(source, "gym", "kg", "km")[0]
    assert day.estimated_1rm == (Decimal(expected) if expected else None)
    assert source == original


@pytest.mark.parametrize("weight", [None, "0", "-1", "NaN", "Infinity"])
def test_invalid_legacy_weight_is_unavailable(weight):
    day = aggregate([row(weight, 5)], "gym", "kg", "km")[0]
    assert day.estimated_1rm is None
    assert day.weight is None
    assert day.volume is None
    assert day.reps == 5
    assert day.volume_partial is True


def test_legacy_cardio_and_offset_date_boundary():
    at = datetime(2026, 1, 2, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    source = [row(distance="-1", duration=0, at=at)]
    original = deepcopy(source)
    day = aggregate(source, "cardio", "kg", "km")[0]
    assert str(day.date) == "2026-01-01"
    assert day.distance is None
    assert day.duration_seconds == 0
    assert source == original
