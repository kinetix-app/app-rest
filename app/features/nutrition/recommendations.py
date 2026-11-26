"""Versioned, deterministic starting estimates; see docs/nutrition-recommendations.md."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.models import Profile
from app.features.goals.models import AccountObjective
from app.features.goals.schemas import Objective
from app.features.nutrition.schemas import NutritionGoalInput

FACTORS = dict(
    zip(
        ("sedentary", "light", "moderate", "high", "very_high"),
        map(Decimal, ("1.2", "1.375", "1.55", "1.725", "1.9")),
        strict=True,
    )
)
ADJUSTMENTS = {"lose_fat": -15, "build_muscle": 10, "gain_weight": 10, "maintain_weight": 0}


class NutritionRecommendation(BaseModel):
    version: str = "mifflin_v1"
    available: bool = False
    reason: str | None = None
    reason_code: (
        Literal[
            "incomplete_profile",
            "underage",
            "measurements_need_assessment",
            "missing_sex_or_activity",
            "estimate_needs_assessment",
        ]
        | None
    ) = None
    missing_fields: list[str] = []
    objective: Objective | None = None
    bmr: Decimal | None = None
    maintenance_calories: Decimal | None = None
    activity_factor: Decimal | None = None
    adjustment_percent: int | None = None
    protein_per_kg: Decimal | None = None
    goal: NutritionGoalInput | None = None


def calculate_recommendation(profile: Profile | None, objective: Objective | None):
    fields = ("age", "sex", "height_cm", "weight_kg", "activity_level")
    missing = [field for field in fields if profile is None or getattr(profile, field) is None]
    if objective is None:
        missing.append("objective")
    result = NutritionRecommendation(objective=objective, missing_fields=missing)
    if missing:
        result.reason_code = "incomplete_profile"
        result.reason = "Complete your profile and select an objective to get a suggestion."
        return result
    if profile.age < 18:
        result.reason_code = "underage"
        result.reason = "Automatic suggestions are available for adults aged 18 or older."
        return result
    weight, height = profile.weight_kg, profile.height_cm
    bmi = weight / (height / 100) ** 2
    if not Decimal("18.5") <= bmi < 40:
        result.reason_code = "measurements_need_assessment"
        result.reason = "Your measurements need an individual assessment before setting a target."
        return result
    factor = FACTORS.get(profile.activity_level)
    if factor is None or profile.sex not in ("male", "female"):
        result.reason_code = "missing_sex_or_activity"
        result.reason = "Update your sex and activity level in Profile."
        return result
    bmr = 10 * weight + Decimal("6.25") * height - 5 * profile.age
    bmr += 5 if profile.sex == "male" else -161
    maintenance = bmr * factor
    adjustment = ADJUSTMENTS[objective]
    calories = (maintenance * (1 + Decimal(adjustment) / 100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    per_kg = Decimal("2") if objective == "lose_fat" else Decimal("1.6")
    protein = (weight * per_kg).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Round down fat/carbohydrates so the stored split never exceeds its calorie budget.
    fats = (calories * Decimal("0.30") / 9).quantize(Decimal("0.01"), rounding="ROUND_DOWN")
    carbs = ((calories - protein * 4 - fats * 9) / 4).quantize(
        Decimal("0.01"), rounding="ROUND_DOWN"
    )
    if not 1200 <= calories <= 5000 or carbs <= 0 or protein * 4 > calories * Decimal("0.35"):
        result.reason_code = "estimate_needs_assessment"
        result.reason = "This estimate needs an individual assessment before setting a target."
        return result
    return NutritionRecommendation(
        available=True,
        objective=objective,
        bmr=bmr.quantize(Decimal("0.01")),
        maintenance_calories=maintenance.quantize(Decimal("0.01")),
        activity_factor=factor,
        adjustment_percent=adjustment,
        protein_per_kg=per_kg,
        goal=NutritionGoalInput(calories=calories, protein=protein, fats=fats, carbohydrates=carbs),
    )


async def get_recommendation(session: AsyncSession, user_id: int):
    profile = await session.get(Profile, user_id)
    selected = await session.get(AccountObjective, user_id)
    return calculate_recommendation(profile, selected.objective if selected else None)
