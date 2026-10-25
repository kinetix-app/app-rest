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
    assert canonical_weight(Decimal("0"), "lb") == 0


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "1000000", True, 1, 1.5])
def test_invalid_mass_and_decimal_input(value):
    with pytest.raises(ValidationError):
        WeightInput.model_validate({"value": value, "unit": "kg"})


def test_legacy_mass_compatibility_rejects_ambiguous_inputs():
    assert PlannedSet(reps=8, weight_kg="80.25").canonical_kg() == Decimal("80.250000")
    with pytest.raises(ValidationError):
        PlannedSet(reps=8, weight_kg="80.25", weight={"value": "80.25", "unit": "kg"})
