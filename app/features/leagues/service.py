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
)
from app.features.leagues.models import league, league_invitation, league_member
from app.features.leagues.schemas import (
    InvitationCreated,
    InvitationPreview,
    LeagueCreate,
    LeagueCreated,
    LeagueDetail,
    LeagueMember,
    LeaguePatch,
    LeagueSummary,
)


async def list_leagues(session: AsyncSession, user_id: int) -> list[LeagueSummary]:
    rows = (
        await session.execute(
            sa.select(league.c.id, league.c.name, league.c.timezone, league_member.c.role)
            .join(league_member, league_member.c.league_id == league.c.id)
            .where(league_member.c.user_id == user_id)
            .order_by(league.c.id)
        )
    ).mappings()
    return [LeagueSummary.model_validate(row) for row in rows]


async def create_league(session: AsyncSession, user_id: int, data: LeagueCreate) -> LeagueCreated:
    try:
        row = (
            (
                await session.execute(
                    league.insert()
                    .values(name=data.name, timezone=data.timezone, created_by=user_id)
                    .returning(league.c.id, league.c.name, league.c.timezone, league.c.created_at)
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
        result = LeagueCreated(**row, role="admin")
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
                    league.c.timezone,
                    league.c.created_at,
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
                league_member.c.role,
                league_member.c.joined_at,
            )
            .outerjoin(Profile, Profile.user_id == league_member.c.user_id)
            .where(league_member.c.league_id == league_id)
            .order_by(league_member.c.user_id)
        )
    ).mappings()
    return LeagueDetail(**row, members=[LeagueMember.model_validate(member) for member in members])


async def rename_league(
    session: AsyncSession, user_id: int, league_id: int, data: LeaguePatch
) -> LeagueDetail:
    try:
        role = (
            await session.execute(
                sa.select(league_member.c.role)
                .where(league_member.c.league_id == league_id, league_member.c.user_id == user_id)
                .with_for_update()
            )
        ).one_or_none()
        if role is None:
            raise LeagueNotFound
        if role.role != "admin":
            raise LeagueForbidden
        await session.execute(
            league.update().where(league.c.id == league_id).values(name=data.name)
        )
        result = await get_league(session, user_id, league_id)
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise


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


async def preview_invitation(session: AsyncSession, token: str) -> InvitationPreview:
    row = (
        (
            await session.execute(
                sa.select(
                    league.c.id.label("league_id"), league.c.name, league_invitation.c.expires_at
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
    return InvitationPreview.model_validate(row)


async def accept_invitation(session: AsyncSession, user_id: int, token: str) -> LeagueDetail:
    try:
        invitation = await preview_invitation(session, token)
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
