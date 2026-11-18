"""Private league membership queries and transactions."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.models import Profile
from app.features.leagues.errors import (
    InvitationExpired,
    InvitationNotFound,
    LeagueForbidden,
    LeagueNotFound,
    LeagueRoleChangeForbidden,
)
from app.features.leagues.listing import list_leagues as list_leagues
from app.features.leagues.models import league, league_invitation, league_member
from app.features.leagues.presentation import member_picture_url, picture_url
from app.features.leagues.schemas import (
    InvitationCreated,
    InvitationPreview,
    LeagueCreate,
    LeagueCreated,
    LeagueDetail,
    LeagueMember,
    LeaguePatch,
    Role,
)


async def create_league(
    session: AsyncSession,
    user_id: int,
    data: LeagueCreate,
    *,
    reserved_id: int | None = None,
    picture_blob_name: str | None = None,
) -> LeagueCreated:
    values = data.model_dump() | {"created_by": user_id, "picture_blob_name": picture_blob_name}
    if reserved_id is not None:
        values["id"] = reserved_id
    try:
        row = (
            (
                await session.execute(
                    league.insert()
                    .values(**values)
                    .returning(
                        league.c.id,
                        league.c.name,
                        league.c.description,
                        league.c.timezone,
                        league.c.created_at,
                    )
                )
            )
            .mappings()
            .one()
        )
        await session.execute(
            league_member.insert().values(
                league_id=row.id, user_id=user_id, role="admin", joined_at=datetime.now(UTC)
            )
        )
        result = LeagueCreated(
            **row, role="admin", picture_url=picture_url(row.id, picture_blob_name)
        )
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise


async def get_league(session: AsyncSession, user_id: int, league_id: int) -> LeagueDetail:
    row = (
        (
            await session.execute(
                sa.select(
                    league.c.id,
                    league.c.name,
                    league.c.description,
                    league.c.timezone,
                    league.c.created_at,
                    league.c.picture_blob_name,
                    league.c.created_by.label("creator_id"),
                    league_member.c.role,
                )
                .join(league_member, league_member.c.league_id == league.c.id)
                .where(league.c.id == league_id, league_member.c.user_id == user_id)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LeagueNotFound
    members = (
        await session.execute(
            sa.select(
                league_member.c.user_id,
                Profile.display_name,
                Profile.picture_blob_name,
                Profile.picture_url,
                league_member.c.role,
                league_member.c.joined_at,
            )
            .outerjoin(Profile, Profile.user_id == league_member.c.user_id)
            .where(league_member.c.league_id == league_id)
            .order_by(league_member.c.user_id)
        )
    ).mappings()
    return LeagueDetail(
        **row,
        picture_url=picture_url(row.id, row.picture_blob_name),
        members=[
            LeagueMember(
                **{
                    **member,
                    "picture_url": member_picture_url(
                        league_id, member.user_id, member.picture_blob_name, member.picture_url
                    ),
                }
            )
            for member in members
        ],
    )


async def require_league_admin(
    session: AsyncSession, user_id: int, league_id: int, *, lock: bool = False
) -> str | None:
    membership = sa.select(league_member.c.role).where(
        league_member.c.league_id == league_id, league_member.c.user_id == user_id
    )
    if lock:
        # Result acknowledgement and configuration both acquire league before membership.
        query = (
            sa.select(league.c.picture_blob_name)
            .where(league.c.id == league_id, membership.exists())
            .with_for_update()
        )
    else:
        query = sa.select(league.c.picture_blob_name).where(
            league.c.id == league_id, membership.exists()
        )
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise LeagueNotFound
    if lock:
        membership = membership.with_for_update()
    role = (await session.execute(membership)).one_or_none()
    if role is None:
        raise LeagueNotFound
    if role.role != "admin":
        raise LeagueForbidden
    return row.picture_blob_name


async def rename_league(
    session: AsyncSession, user_id: int, league_id: int, data: LeaguePatch
) -> LeagueDetail:
    try:
        await require_league_admin(session, user_id, league_id, lock=True)
        await session.execute(
            league.update()
            .where(league.c.id == league_id)
            .values(**data.model_dump(exclude_unset=True))
        )
        result = await get_league(session, user_id, league_id)
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise


async def update_member_role(
    session: AsyncSession, user_id: int, league_id: int, member_id: int, role: Role
) -> LeagueDetail:
    async with session.begin():
        await require_league_admin(session, user_id, league_id, lock=True)
        member = (
            await session.execute(
                sa.select(league.c.created_by)
                .select_from(league_member)
                .join(league, league.c.id == league_member.c.league_id)
                .where(league_member.c.league_id == league_id, league_member.c.user_id == member_id)
                .with_for_update(of=league_member)
            )
        ).one_or_none()
        if member is None:
            raise LeagueNotFound
        if member_id == member.created_by:
            raise LeagueRoleChangeForbidden("The league creator’s role cannot be changed")
        if member_id == user_id:
            raise LeagueRoleChangeForbidden("You cannot change your own league role")
        await session.execute(
            league_member.update()
            .where(league_member.c.league_id == league_id, league_member.c.user_id == member_id)
            .values(role=role)
        )
        return await get_league(session, user_id, league_id)


async def create_invitation(
    session: AsyncSession, user_id: int, league_id: int
) -> InvitationCreated:
    try:
        role = (
            await session.execute(
                sa.select(league_member.c.role).where(
                    league_member.c.league_id == league_id, league_member.c.user_id == user_id
                )
            )
        ).one_or_none()
        if role is None:
            raise LeagueNotFound
        if role.role != "admin":
            raise LeagueForbidden
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(hours=48)
        await session.execute(
            league_invitation.insert().values(
                token_hash=_token_hash(token), league_id=league_id, expires_at=expires_at
            )
        )
        await session.commit()
        return InvitationCreated(token=token, expires_at=expires_at)
    except Exception:
        await session.rollback()
        raise


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def invitation_record(session: AsyncSession, token: str):
    row = (
        (
            await session.execute(
                sa.select(
                    league.c.id.label("league_id"),
                    league.c.name,
                    league.c.description,
                    league.c.created_at,
                    league.c.timezone,
                    league.c.picture_blob_name,
                    league_invitation.c.expires_at,
                )
                .join(league_invitation, league_invitation.c.league_id == league.c.id)
                .where(league_invitation.c.token_hash == _token_hash(token))
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise InvitationNotFound
    if row.expires_at <= datetime.now(UTC):
        raise InvitationExpired
    return row


async def preview_invitation(session: AsyncSession, user_id: int, token: str) -> InvitationPreview:
    row = await invitation_record(session, token)
    counts = (
        await session.execute(
            sa.select(
                sa.func.count().label("member_count"),
                sa.func.count().filter(league_member.c.user_id == user_id).label("viewer_count"),
            )
            .select_from(league_member)
            .where(league_member.c.league_id == row.league_id)
        )
    ).one()
    return InvitationPreview(
        **row,
        member_count=counts.member_count,
        already_member=counts.viewer_count > 0,
        has_picture=row.picture_blob_name is not None,
    )


async def accept_invitation(session: AsyncSession, user_id: int, token: str) -> LeagueDetail:
    try:
        invitation = await invitation_record(session, token)
        await session.execute(
            insert(league_member)
            .values(
                league_id=invitation.league_id,
                user_id=user_id,
                role="member",
                joined_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["user_id", "league_id"])
        )
        result = await get_league(session, user_id, invitation.league_id)
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise
