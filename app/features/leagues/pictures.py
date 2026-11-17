"""Member-private league pictures with administrator-only replacement and removal."""

import asyncio
from uuid import uuid4

import sqlalchemy as sa
from azure.core.exceptions import AzureError, ResourceNotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage.azure import BlobStorage
from app.features.accounts.errors import PictureMissing, PictureStorageUnavailable
from app.features.accounts.pictures import MAX_PICTURE_BYTES as MAX_PICTURE_BYTES
from app.features.accounts.pictures import normalize_picture
from app.features.leagues.errors import LeagueForbidden, LeagueNotFound
from app.features.leagues.models import league, league_member
from app.features.leagues.schemas import LeagueDetail
from app.features.leagues.service import get_league

_STORAGE_ERRORS = (AzureError, TimeoutError, OSError, ValueError)


def _prefix(league_id: int) -> str:
    return f"leagues/{league_id}/"


async def _member_picture(
    session: AsyncSession, user_id: int, league_id: int, *, admin: bool, lock: bool = False
) -> str | None:
    query = (
        sa.select(league.c.picture_blob_name, league_member.c.role)
        .join(league_member, league_member.c.league_id == league.c.id)
        .where(league.c.id == league_id, league_member.c.user_id == user_id)
    )
    if lock:
        query = query.with_for_update(of=[league, league_member])
    row = (await session.execute(query)).first()
    if row is None:
        raise LeagueNotFound
    if admin and row.role != "admin":
        raise LeagueForbidden
    return row.picture_blob_name


async def _authorized_name(
    session: AsyncSession, user_id: int, league_id: int, *, admin: bool = False
) -> str | None:
    try:
        name = await _member_picture(session, user_id, league_id, admin=admin)
        await session.commit()
        return name
    except BaseException:
        await session.rollback()
        raise


async def _cleanup(storage: BlobStorage | None, name: str | None, league_id: int) -> None:
    if storage is None or name is None or not name.startswith(_prefix(league_id)):
        return
    try:
        await storage.delete_profile_picture(name)
    except _STORAGE_ERRORS:
        # Committed replacement/removal remains successful if cleanup is unavailable.
        pass


async def _set_picture(
    session: AsyncSession, user_id: int, league_id: int, name: str | None
) -> tuple[LeagueDetail, str | None]:
    try:
        previous = await _member_picture(session, user_id, league_id, admin=True, lock=True)
        await session.execute(
            league.update().where(league.c.id == league_id).values(picture_blob_name=name)
        )
        result = await get_league(session, user_id, league_id)
        await session.commit()
        return result, previous
    except BaseException:
        await session.rollback()
        raise


async def upload_picture(
    session: AsyncSession,
    user_id: int,
    league_id: int,
    storage: BlobStorage | None,
    data: bytes,
    content_type: str | None,
) -> LeagueDetail:
    await _authorized_name(session, user_id, league_id, admin=True)
    if storage is None:
        raise PictureStorageUnavailable
    normalized = await asyncio.to_thread(normalize_picture, data, content_type)
    name = f"{_prefix(league_id)}{uuid4().hex}.jpg"
    try:
        await storage.upload_profile_picture(name, normalized)
    except _STORAGE_ERRORS:
        await _cleanup(storage, name, league_id)
        raise PictureStorageUnavailable from None
    try:
        result, previous = await _set_picture(session, user_id, league_id, name)
    except BaseException:
        await _cleanup(storage, name, league_id)
        raise
    await _cleanup(storage, previous, league_id)
    return result


async def remove_picture(
    session: AsyncSession, user_id: int, league_id: int, storage: BlobStorage | None
) -> LeagueDetail:
    result, previous = await _set_picture(session, user_id, league_id, None)
    await _cleanup(storage, previous, league_id)
    return result


async def read_picture(
    session: AsyncSession, user_id: int, league_id: int, storage: BlobStorage | None
) -> bytes:
    name = await _authorized_name(session, user_id, league_id)
    if name is None or not name.startswith(_prefix(league_id)):
        raise PictureMissing
    if storage is None:
        raise PictureStorageUnavailable
    try:
        return await storage.read_profile_picture(name)
    except ResourceNotFoundError:
        raise PictureMissing from None
    except _STORAGE_ERRORS:
        raise PictureStorageUnavailable from None


async def read_member_picture(
    session: AsyncSession,
    user_id: int,
    league_id: int,
    member_id: int,
    storage: BlobStorage | None,
) -> bytes:
    from app.features.accounts.models import Profile

    try:
        await _member_picture(session, user_id, league_id, admin=False)
        row = (
            await session.execute(
                sa.select(Profile.picture_blob_name)
                .select_from(league_member)
                .outerjoin(Profile, Profile.user_id == league_member.c.user_id)
                .where(league_member.c.league_id == league_id, league_member.c.user_id == member_id)
            )
        ).first()
        if row is None:
            raise LeagueNotFound
        name = row.picture_blob_name
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    if name is None or not name.startswith(f"profiles/{member_id}/"):
        raise PictureMissing
    if storage is None:
        raise PictureStorageUnavailable
    try:
        return await storage.read_profile_picture(name)
    except ResourceNotFoundError:
        raise PictureMissing from None
    except _STORAGE_ERRORS:
        raise PictureStorageUnavailable from None
