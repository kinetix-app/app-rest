"""Private league API payloads."""

from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Role = Literal["admin", "member"]


class LeagueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    description: Description | None = None
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
    name: Name | None = None
    description: Description | None = None

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set or ("name" in self.model_fields_set and self.name is None):
            raise ValueError("Provide a name or description to update; name cannot be null")
        return self


class LeagueRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


class LeagueConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    description: Description | None
    remove_picture: bool = Field(default=False, strict=True)


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
    description: str | None = None
    created_at: datetime


class LeagueMember(BaseModel):
    user_id: int
    display_name: str | None
    role: Role | None
    joined_at: datetime | None
    picture_url: str | None = None


class LeagueDetail(LeagueCreated):
    creator_id: int
    members: list[LeagueMember]


class InvitationCreated(BaseModel):
    token: str
    expires_at: datetime


class InvitationPreview(BaseModel):
    already_member: bool
    description: str | None
    member_count: int
    created_at: datetime
    timezone: str | None
    has_picture: bool
    league_id: int
    name: str
    expires_at: datetime
