from decimal import Decimal

import pytest

from app.features.accounts.models import Profile
from app.features.nutrition.recommendations import calculate_recommendation


def profile(**changes):
    return Profile(
        **{
            "age": 30,
            "sex": "male",
            "height_cm": Decimal("180"),
            "weight_kg": Decimal("80"),
            "activity_level": "moderate",
            **changes,
        }
    )


@pytest.mark.parametrize("sex,bmr", [("male", "1780"), ("female", "1614")])
def test_mifflin_and_maintenance(sex, bmr):
    result = calculate_recommendation(profile(sex=sex), "maintain_weight")
    assert result.available
    assert result.bmr == Decimal(bmr)
    assert result.maintenance_calories == Decimal(bmr) * Decimal("1.55")


@pytest.mark.parametrize(
    "objective,calories,protein",
    [
        ("lose_fat", "2345", "160"),
        ("build_muscle", "3035", "128"),
        ("gain_weight", "3035", "128"),
        ("maintain_weight", "2759", "128"),
    ],
)
def test_objectives_and_macro_budget(objective, calories, protein):
    result = calculate_recommendation(profile(), objective)
    goal = result.goal
    assert goal.calories == Decimal(calories)
    assert goal.protein == Decimal(protein)
    energy = 4 * (goal.protein + goal.carbohydrates) + 9 * goal.fats
    assert Decimal("0") <= goal.calories - energy < Decimal("0.04")


def test_missing_and_ineligible_profiles_do_not_invent_targets():
    assert calculate_recommendation(None, None).goal is None
    assert "objective" in calculate_recommendation(profile(), None).missing_fields
    for changes in (
        {"age": 17},
        {"weight_kg": Decimal("40")},
        {"weight_kg": Decimal("180")},
        {"sex": None},
    ):
        assert calculate_recommendation(profile(**changes), "lose_fat").goal is None


@pytest.mark.parametrize(
    "activity,factor",
    [
        ("sedentary", "1.2"),
        ("light", "1.375"),
        ("moderate", "1.55"),
        ("high", "1.725"),
        ("very_high", "1.9"),
    ],
)
def test_all_activity_factors(activity, factor):
    result = calculate_recommendation(profile(activity_level=activity), "maintain_weight")
    assert result.activity_factor == Decimal(factor)
    assert result.maintenance_calories == Decimal("1780") * Decimal(factor)


@pytest.mark.parametrize(
    "changes,objective,reason_code",
    [
        ({}, None, "incomplete_profile"),
        ({"age": 17}, "lose_fat", "underage"),
        ({"weight_kg": Decimal("40")}, "lose_fat", "measurements_need_assessment"),
        ({"sex": "unknown"}, "lose_fat", "missing_sex_or_activity"),
        (
            {
                "age": 120,
                "sex": "female",
                "height_cm": Decimal("160"),
                "weight_kg": Decimal("50"),
                "activity_level": "sedentary",
            },
            "lose_fat",
            "estimate_needs_assessment",
        ),
    ],
)
def test_unavailable_recommendations_expose_stable_reason_codes(changes, objective, reason_code):
    result = calculate_recommendation(profile(**changes), objective)
    assert result.reason_code == reason_code
    assert result.reason
    assert not result.available


def test_available_recommendation_has_no_reason_code():
    result = calculate_recommendation(profile(), "maintain_weight")
    assert result.available
    assert result.reason is None
    assert result.reason_code is None
