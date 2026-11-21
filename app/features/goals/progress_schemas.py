from __future__ import annotations

from datetime import date as Date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.features.accounts.schemas import BodyMassKg, HeightCm
from app.features.goals.schemas import Objective


def parse_calendar_date(value: object) -> Date:
    if isinstance(value, Date) and type(value) is Date:
        return value
    if isinstance(value, str):
        date = Date.fromisoformat(value)
        if date.isoformat() == value:
            return date
    raise ValueError("Use a date in YYYY-MM-DD format")


CalendarDate = Annotated[Date, BeforeValidator(parse_calendar_date)]
Percentage = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]
Circumference = Annotated[Decimal, Field(gt=0, le=Decimal("999.99"), decimal_places=2)]


class MeasurementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    date: CalendarDate
    height_cm: HeightCm | None = None
    weight_kg: BodyMassKg | None = None
    body_fat_percentage: Percentage | None = None
    muscle_mass_kg: BodyMassKg | None = None
    waist_cm: Circumference | None = None
    chest_cm: Circumference | None = None
    arm_cm: Circumference | None = None
    thigh_cm: Circumference | None = None

    @model_validator(mode="after")
    def require_measurement(self) -> MeasurementCreate:
        if not self.measurements():
            raise ValueError("Enter at least one measurement")
        return self

    def measurements(self) -> dict[str, Decimal]:
        return self.model_dump(exclude={"request_id", "date"}, exclude_none=True)


class MeasurementResponse(BaseModel):
    id: int
    date: Date
    height_cm: Decimal | None
    weight_kg: Decimal | None
    body_fat_percentage: Decimal | None
    muscle_mass_kg: Decimal | None
    waist_cm: Decimal | None
    chest_cm: Decimal | None
    arm_cm: Decimal | None
    thigh_cm: Decimal | None


class MeasurementHistory(BaseModel):
    items: list[MeasurementResponse]


class PhysicalTargetPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: Objective
    weight_kg: BodyMassKg
    target_date: CalendarDate | None = None


class PhysicalTarget(BaseModel):
    weight_kg: Decimal
    target_date: Date | None


class PhysicalTargetResponse(BaseModel):
    objective: Objective | None
    target: PhysicalTarget | None
