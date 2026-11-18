"""League standings and member score history page payloads."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class StandingsPageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    round_id: int | None = Field(default=None, gt=0, le=2**63 - 1)
    offset: int = Field(default=0, ge=0, le=2**53 - 1)
    limit: int = Field(default=20, ge=1, le=50)


class RoundSummary(BaseModel):
    id: int
    start_at: datetime
    end_at: datetime


class RoundCatalog(BaseModel):
    timezone: str
    current_round_id: int
    rounds: list[RoundSummary]


class StandingItem(BaseModel):
    user_id: int
    display_name: str | None
    picture_url: str | None
    score: str
    position: int


class StandingsPage(BaseModel):
    items: list[StandingItem]
    next_offset: int | None


class CalculationInputs(BaseModel):
    session_id: int
    volume_kg_reps: str
    duration_us: str
    body_weight_kg: str
    formula_version: str


class MemberScoreItem(BaseModel):
    local_day: date
    round_id: int
    start_at: datetime
    end_at: datetime
    score: str
    session_id: int
    ended_at: datetime
    calculation: CalculationInputs | None = None


class MemberScoreHistory(BaseModel):
    items: list[MemberScoreItem]
    next_before: date | None


class ContributionItem(MemberScoreItem):
    user_id: int
    display_name: str | None
    picture_url: str | None


class ContributionsPage(BaseModel):
    items: list[ContributionItem]
    next_offset: int | None
