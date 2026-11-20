from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.features.leagues.calculation import calculate_score, elapsed_microseconds, weekly_bounds


def test_hand_calculation_and_integer_half_up():
    assert calculate_score(Decimal(6000), 3_600_000_000, Decimal(75)) == 80
    assert calculate_score(Decimal(75), 1_800_000_000, Decimal(75)) == 1
    assert calculate_score(Decimal(74), 1_800_000_000, Decimal(75)) == 0
    assert (
        elapsed_microseconds(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, 1, 0, 0, 1, tzinfo=UTC)
        )
        == 3_600_000_001
    )


@pytest.mark.parametrize("volume,weight,duration", [(0, 75, 1), (10, 0, 1), (10, 75, 0)])
def test_missing_inputs_do_not_score(volume, weight, duration):
    assert calculate_score(Decimal(volume), duration, Decimal(weight)) is None


@pytest.mark.parametrize("month,day,hours", [(3, 29, 167), (10, 25, 169), (11, 17, 168)])
def test_calendar_weeks_include_sunday_and_dst(month, day, hours):
    instant = datetime(2026, month, day, 12, tzinfo=UTC)
    start, end = weekly_bounds(instant, "Europe/Madrid")
    assert end - start == timedelta(hours=hours)
    assert start <= instant < end
    assert weekly_bounds(end - timedelta(microseconds=1), "Europe/Madrid") == (start, end)
    assert weekly_bounds(end, "Europe/Madrid")[0] == end
