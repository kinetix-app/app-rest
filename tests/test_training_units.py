"""Boundary and exact conversion checks independent of PostgreSQL."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.features.training.schemas import PlannedSet, WeightInput
from app.features.training.units import canonical_weight, display_weight


def test_exact_pounds_and_presentation_do_not_requantize_storage():
    kg = canonical_weight(Decimal("100.00"), "lb")
    assert kg == Decimal("45.359237")
    for _ in range(50):
        assert display_weight(kg, "lb") == Decimal("100.00")
        assert display_weight(kg, "kg") == Decimal("45.36")
    assert canonical_weight(Decimal("0.0000005"), "kg") == Decimal("0.000001")
    zero = Decimal("0")
    rounds_to_zero = Decimal("0.0000001")
    with pytest.raises(ValueError):
        canonical_weight(zero, "lb")
    with pytest.raises(ValueError):
        canonical_weight(rounds_to_zero, "kg")


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "1000000", True, 1, 1.5])
def test_invalid_mass_and_decimal_input(value):
    with pytest.raises(ValidationError):
        WeightInput.model_validate({"value": value, "unit": "kg"})


def test_legacy_mass_compatibility_rejects_ambiguous_inputs():
    assert PlannedSet(reps=8, weight_kg="80.25").canonical_kg() == Decimal("80.250000")
    with pytest.raises(ValidationError):
        PlannedSet(reps=8, weight_kg="80.25", weight={"value": "80.25", "unit": "kg"})


def test_sets_match_authoritative_activity_type():
    gym = PlannedSet(reps=8, weight={"value": "20", "unit": "kg"})
    cardio = PlannedSet(duration_seconds=0, distance_km="0.00")
    gym.validate_activity("gym")
    cardio.validate_activity("cardio")
    for value, activity in [(gym, "cardio"), (cardio, "gym"), (PlannedSet(), "cardio")]:
        with pytest.raises(ValueError):
            value.validate_activity(activity)
    PlannedSet().validate_activity("cardio", incomplete=True)


@pytest.mark.parametrize(
    "values",
    [
        {"duration_seconds": -1, "distance_km": "0"},
        {"duration_seconds": 1.5, "distance_km": "0"},
        {"duration_seconds": 1, "distance_km": "NaN"},
        {"duration_seconds": 1, "distance_km": "0.001"},
        {"duration_seconds": 1, "distance_km": "1000000"},
    ],
)
def test_invalid_cardio_boundaries(values):
    with pytest.raises(ValidationError):
        PlannedSet.model_validate(values)


def test_unconfirmed_draft_rejects_incompatible_values_even_if_malformed():
    from app.features.training.schemas import DraftSet

    value = DraftSet.model_validate(
        {
            "client_id": "3e17c183-38a9-4b5c-b953-7ae49433af17",
            "completed": False,
            "reps": "invalid",
        }
    )
    with pytest.raises(ValueError):
        value.validate_activity("cardio", incomplete=True)
    value.validate_activity("gym", incomplete=True)
