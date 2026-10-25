"""Deterministic canonical mass conversion (kg), rounded once at persistence."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

WeightUnit = Literal["kg", "lb"]
KG_PER_LB = Decimal("0.45359237")
STORAGE_QUANTUM = Decimal("0.000001")
DISPLAY_QUANTUM = Decimal("0.01")
MAX_WEIGHT_KG = Decimal("999999.99")


def canonical_weight(value: Decimal, unit: WeightUnit) -> Decimal:
    weight = value * KG_PER_LB if unit == "lb" else value
    if not weight.is_finite() or weight < 0 or weight > MAX_WEIGHT_KG:
        raise ValueError("Weight must be between 0 and 999999.99 kg")
    return weight.quantize(STORAGE_QUANTUM, rounding=ROUND_HALF_UP)


def display_weight(value: Decimal, unit: WeightUnit) -> Decimal:
    return (value / KG_PER_LB if unit == "lb" else value).quantize(
        DISPLAY_QUANTUM, rounding=ROUND_HALF_UP
    )
