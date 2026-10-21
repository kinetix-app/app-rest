
from decimal import Decimal

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
