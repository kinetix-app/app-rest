"""Private league API payloads."""

from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Role = Literal["admin", "member"]


class LeagueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    timezone: Annotated[str, StringConstraints(min_length=1, max_length=100)]

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError, ValueError:
            raise ValueError("Invalid IANA timezone") from None
        return value


class LeaguePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name


class LeagueSummary(BaseModel):
    id: int
    name: str
    timezone: str | None
    role: Role | None
    picture_url: str | None = None


class LeagueListItem(LeagueSummary):
    member_count: int = Field(ge=0)
    current_week_position: int | None = Field(ge=1)


class LeagueCreated(LeagueSummary):
    created_at: datetime


class LeagueMember(BaseModel):
    user_id: int
    display_name: str | None
    role: Role | None
    joined_at: datetime | None
    picture_url: str | None = None


class LeagueDetail(LeagueCreated):
    members: list[LeagueMember]


class InvitationCreated(BaseModel):
    token: str
    expires_at: datetime


class InvitationPreview(BaseModel):
    league_id: int
    name: str
    expires_at: datetime
