from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class FoodCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    brand: str | None = Field(default=None, max_length=100)
    calories: Decimal = Field(ge=0, max_digits=8, decimal_places=2)
    protein: Decimal = Field(ge=0, max_digits=8, decimal_places=2)
    carbohydrates: Decimal = Field(ge=0, max_digits=8, decimal_places=2)
    fats: Decimal = Field(ge=0, max_digits=8, decimal_places=2)
    barcode: str | None = Field(default=None, max_length=50)


class FoodResponse(FoodCreate):
    id: int
    user_id: int


class FoodPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    brand: str | None = Field(default=None, max_length=100)
    calories: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    protein: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    carbohydrates: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    fats: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    barcode: str | None = Field(default=None, max_length=50)


class NutritionGoalResponse(BaseModel):
    id: int
    user_id: int
    calories: Decimal
    protein: Decimal
    carbohydrates: Decimal
    fats: Decimal


class NutritionGoalInput(BaseModel):
    calories: Decimal = Field(gt=0, max_digits=8, decimal_places=2)
    protein: Decimal = Field(ge=0, max_digits=8, decimal_places=2)
    carbohydrates: Decimal = Field(ge=0, max_digits=8, decimal_places=2)
    fats: Decimal = Field(ge=0, max_digits=8, decimal_places=2)


class MealItemCreate(BaseModel):
    date: date
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    food_id: int = Field(gt=0)
    quantity_grams: Decimal = Field(gt=0, max_digits=8, decimal_places=2)


class MealItemResponse(BaseModel):
    id: int
    meal_type: str
    food_id: int
    name: str
    quantity_grams: Decimal
    calories: Decimal
    protein: Decimal
    carbohydrates: Decimal
    fats: Decimal
