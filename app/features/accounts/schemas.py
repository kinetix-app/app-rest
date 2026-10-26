from datetime import datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)

    age: int | None = Field(default=None, ge=1, le=120, strict=True)
    height_cm: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    weight_kg: Decimal | None = Field(default=None, gt=0, le=1000, decimal_places=6)
    measurement_system: Literal["metric", "imperial"] | None = None
    picture_url: str | None = Field(default=None, max_length=2048)

    @field_validator("picture_url")
    @classmethod
    def validate_picture_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        url = TypeAdapter(HttpUrl).validate_python(value)
        if url.scheme != "https" or url.username or url.password:
            raise ValueError("Use an HTTPS image URL without credentials")
        return str(url)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError, ValueError:
                raise ValueError("Use a valid IANA timezone") from None
        return value


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    display_name: str | None
    timezone: str | None
    age: int | None
    height_cm: Decimal | None
    weight_kg: Decimal | None
    measurement_system: Literal["metric", "imperial"] | None
    picture_url: str | None
    updated_at: datetime


class OnboardingResponse(BaseModel):
    profile_complete: bool
    objective_selected: bool
    required: bool


class AccountResponse(BaseModel):
    id: int
    status: str
    created_at: datetime
    profile: ProfileResponse
    onboarding: OnboardingResponse
