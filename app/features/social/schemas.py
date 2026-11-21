"""Public friendship API contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# From the caller's point of view.
Relationship = Literal["self", "none", "outgoing", "incoming", "friends"]


class Person(BaseModel):
    id: int
    display_name: str | None
    # Load the photo from GET /api/v1/people/{id}/picture when true.
    has_picture: bool = False


class PersonResult(Person):
    relationship: Relationship


class PersonProfile(PersonResult):
    friend_count: int


class PersonPage(BaseModel):
    items: list[PersonResult]


class Friend(BaseModel):
    user: Person
    since: datetime


class FriendPage(BaseModel):
    items: list[Friend]
    limit: int
    offset: int


class FriendRequest(BaseModel):
    user: Person
    created_at: datetime


class FriendRequests(BaseModel):
    incoming: list[FriendRequest]
    outgoing: list[FriendRequest]


class FriendRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(strict=True, gt=0, le=2**63 - 1)


class RelationshipResponse(BaseModel):
    user_id: int
    relationship: Relationship
