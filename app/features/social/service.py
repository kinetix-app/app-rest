"""Mutual friendships. A pair has one row; acceptance happens in place."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.models import Profile, User
from app.features.social.errors import PersonNotFound, RequestNotFound, SelfFriendship
from app.features.social.models import FriendshipStatus, friendship
from app.features.social.schemas import (
    Friend,
    FriendPage,
    FriendRequest,
    FriendRequests,
    Person,
    PersonPage,
    PersonProfile,
    PersonResult,
    Relationship,
    RelationshipResponse,
)

users = User.__table__
profiles = Profile.__table__


def pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _pair_filter(a: int, b: int):
    low, high = pair(a, b)
    return sa.and_(friendship.c.user_low_id == low, friendship.c.user_high_id == high)


def _other(user_id: int):
    """The other account of a pair row, from the caller's point of view."""
    return sa.case(
        (friendship.c.user_low_id == user_id, friendship.c.user_high_id),
        else_=friendship.c.user_low_id,
    )


def _involves(user_id: int):
    return sa.or_(friendship.c.user_low_id == user_id, friendship.c.user_high_id == user_id)


def friend_ids_query(user_id: int) -> sa.Select:
    """IDs of accepted friends; reused by the posts feed for FRIENDS visibility."""
    return sa.select(_other(user_id)).where(
        _involves(user_id), friendship.c.status == FriendshipStatus.ACCEPTED
    )


def _relationship(user_id: int, row) -> Relationship:
    if row is None:
        return "none"
    if row["status"] == FriendshipStatus.ACCEPTED:
        return "friends"
    return "outgoing" if row["requester_id"] == user_id else "incoming"


def _active_person():
    """Active accounts that finished setting their name; others are not discoverable."""
    return sa.and_(users.c.status == "active", profiles.c.display_name.is_not(None))


def _person(row) -> Person:
    return Person(
        id=row["id"],
        display_name=row["display_name"],
        has_picture=row["picture_blob_name"] is not None,
    )


async def _require_person(session: AsyncSession, person_id: int, *, lock: bool = False) -> Person:
    query = (
        sa.select(users.c.id, profiles.c.display_name, profiles.c.picture_blob_name)
        .join(profiles, profiles.c.user_id == users.c.id)
        .where(users.c.id == person_id, _active_person())
    )
    if lock:
        query = query.with_for_update(of=users)
    row = (await session.execute(query)).mappings().first()
    if row is None:
        raise PersonNotFound
    return _person(row)


async def _pair_row(session: AsyncSession, a: int, b: int, *, lock: bool = False):
    query = sa.select(friendship).where(_pair_filter(a, b))
    if lock:
        query = query.with_for_update()
    return (await session.execute(query)).mappings().first()


async def relationships(
    session: AsyncSession, user_id: int, others: list[int]
) -> dict[int, Relationship]:
    result: dict[int, Relationship] = dict.fromkeys(others, "none")
    if user_id in result:
        result[user_id] = "self"
    rows = (
        await session.execute(
            sa.select(friendship, _other(user_id).label("other")).where(
                _involves(user_id), _other(user_id).in_(others)
            )
        )
    ).mappings()
    for row in rows:
        result[row["other"]] = _relationship(user_id, row)
    return result


async def search_people(session: AsyncSession, user_id: int, query: str, limit: int) -> PersonPage:
    rows = (
        (
            await session.execute(
                sa.select(users.c.id, profiles.c.display_name, profiles.c.picture_blob_name)
                .join(profiles, profiles.c.user_id == users.c.id)
                .where(
                    _active_person(),
                    users.c.id != user_id,
                    profiles.c.display_name.icontains(query, autoescape=True),
                )
                .order_by(sa.func.lower(profiles.c.display_name), users.c.id)
                .limit(limit)
            )
        )
        .mappings()
        .all()
    )
    states = await relationships(session, user_id, [row["id"] for row in rows])
    return PersonPage(
        items=[
            PersonResult(**_person(row).model_dump(), relationship=states[row["id"]])
            for row in rows
        ]
    )


async def get_person(session: AsyncSession, user_id: int, person_id: int) -> PersonProfile:
    if person_id == user_id:
        row = (
            await session.execute(
                sa.select(profiles.c.display_name, profiles.c.picture_blob_name).where(
                    profiles.c.user_id == user_id
                )
            )
        ).first()
        person = Person(
            id=user_id,
            display_name=row.display_name if row else None,
            has_picture=bool(row and row.picture_blob_name),
        )
        relationship: Relationship = "self"
    else:
        person = await _require_person(session, person_id)
        relationship = _relationship(user_id, await _pair_row(session, user_id, person_id))
    friend_count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(friendship)
        .join(users, users.c.id == _other(person.id))
        .where(
            _involves(person.id),
            friendship.c.status == FriendshipStatus.ACCEPTED,
            users.c.status == "active",
        )
    )
    return PersonProfile(
        **person.model_dump(), relationship=relationship, friend_count=friend_count or 0
    )


async def list_friends(session: AsyncSession, user_id: int, limit: int, offset: int) -> FriendPage:
    other = _other(user_id)
    rows = (
        (
            await session.execute(
                sa.select(
                    users.c.id,
                    profiles.c.display_name,
                    profiles.c.picture_blob_name,
                    friendship.c.accepted_at,
                )
                .select_from(friendship)
                .join(users, users.c.id == other)
                .join(profiles, profiles.c.user_id == users.c.id)
                .where(
                    _involves(user_id),
                    friendship.c.status == FriendshipStatus.ACCEPTED,
                    users.c.status == "active",
                )
                .order_by(sa.func.lower(profiles.c.display_name), users.c.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .mappings()
        .all()
    )
    return FriendPage(
        items=[
            Friend(
                user=_person(row),
                since=row["accepted_at"],
            )
            for row in rows
        ],
        limit=limit,
        offset=offset,
    )


async def list_requests(session: AsyncSession, user_id: int) -> FriendRequests:
    other = _other(user_id)
    rows = (
        (
            await session.execute(
                sa.select(
                    users.c.id,
                    profiles.c.display_name,
                    profiles.c.picture_blob_name,
                    friendship.c.requester_id,
                    friendship.c.created_at,
                )
                .select_from(friendship)
                .join(users, users.c.id == other)
                .join(profiles, profiles.c.user_id == users.c.id)
                .where(
                    _involves(user_id),
                    friendship.c.status == FriendshipStatus.PENDING,
                    users.c.status == "active",
                )
                .order_by(friendship.c.created_at.desc(), users.c.id)
            )
        )
        .mappings()
        .all()
    )
    incoming, outgoing = [], []
    for row in rows:
        item = FriendRequest(
            user=_person(row),
            created_at=row["created_at"],
        )
        (outgoing if row["requester_id"] == user_id else incoming).append(item)
    return FriendRequests(incoming=incoming, outgoing=outgoing)


async def _accept(session: AsyncSession, a: int, b: int) -> None:
    await session.execute(
        sa.update(friendship)
        .where(_pair_filter(a, b))
        .values(status=FriendshipStatus.ACCEPTED, accepted_at=sa.func.now())
    )


async def send_request(session: AsyncSession, user_id: int, person_id: int) -> RelationshipResponse:
    if person_id == user_id:
        raise SelfFriendship
    try:
        await _require_person(session, person_id)
        row = await _pair_row(session, user_id, person_id, lock=True)
        if row is None:
            low, high = pair(user_id, person_id)
            await session.execute(
                insert(friendship)
                .values(
                    user_low_id=low,
                    user_high_id=high,
                    requester_id=user_id,
                    status=FriendshipStatus.PENDING,
                )
                .on_conflict_do_nothing(
                    index_elements=[friendship.c.user_low_id, friendship.c.user_high_id]
                )
            )
            # A concurrent request from either side may have won the insert.
            row = await _pair_row(session, user_id, person_id, lock=True)
        state = _relationship(user_id, row)
        if state == "incoming":
            # Both want to be friends: requesting back accepts.
            await _accept(session, user_id, person_id)
            state = "friends"
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return RelationshipResponse(user_id=person_id, relationship=state)


async def accept_request(
    session: AsyncSession, user_id: int, person_id: int
) -> RelationshipResponse:
    try:
        await _require_person(session, person_id)
        row = await _pair_row(session, user_id, person_id, lock=True)
        state = _relationship(user_id, row)
        if state not in ("incoming", "friends"):
            raise RequestNotFound
        if state == "incoming":
            await _accept(session, user_id, person_id)
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return RelationshipResponse(user_id=person_id, relationship="friends")


async def remove(session: AsyncSession, user_id: int, person_id: int) -> None:
    """Unfriend, decline an incoming request or cancel an outgoing one; idempotent."""
    try:
        await session.execute(sa.delete(friendship).where(_pair_filter(user_id, person_id)))
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
