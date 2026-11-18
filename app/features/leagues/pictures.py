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
from app.features.leagues.errors import LeagueNotFound
from app.features.leagues.models import league, league_member
from app.features.leagues.schemas import (
    LeagueConfiguration,
    LeagueCreate,
    LeagueCreated,
    LeagueDetail,
)
from app.features.leagues.service import (
    create_league,
    get_league,
    invitation_record,
    require_league_admin,
)

_STORAGE_ERRORS = (AzureError, TimeoutError, OSError, ValueError)


def _prefix(league_id: int) -> str:
    return f"leagues/{league_id}/"


async def _authorized_name(
    session: AsyncSession, user_id: int, league_id: int, *, admin: bool = False
) -> str | None:
    async with session.begin():
        if admin:
            return await require_league_admin(session, user_id, league_id)
        return await _member_picture(session, user_id, league_id)


async def _member_picture(session: AsyncSession, user_id: int, league_id: int) -> str | None:
    row = (
        await session.execute(
            sa.select(league.c.picture_blob_name)
            .join(league_member, league_member.c.league_id == league.c.id)
            .where(league.c.id == league_id, league_member.c.user_id == user_id)
        )
    ).one_or_none()
    if row is None:
        raise LeagueNotFound
    return row.picture_blob_name


async def _cleanup(storage: BlobStorage | None, name: str | None, league_id: int) -> None:
    if storage is None or name is None or not name.startswith(_prefix(league_id)):
        return
    try:
        await storage.delete_profile_picture(name)
    except _STORAGE_ERRORS:
        # Committed replacement/removal remains successful if cleanup is unavailable.
        pass


async def _save_settings(
    session: AsyncSession, user_id: int, league_id: int, values: dict
) -> tuple[LeagueDetail, str | None]:
    async with session.begin():
        previous = await require_league_admin(session, user_id, league_id, lock=True)
        await session.execute(league.update().where(league.c.id == league_id).values(**values))
        return await get_league(session, user_id, league_id), previous


async def _upload_new_picture(
    storage: BlobStorage | None, league_id: int, data: bytes, content_type: str | None
) -> str:
    if storage is None:
        raise PictureStorageUnavailable
    normalized = await asyncio.to_thread(normalize_picture, data, content_type)
    name = f"{_prefix(league_id)}{uuid4().hex}.jpg"
    try:
        await storage.upload_profile_picture(name, normalized)
    except BaseException as error:
        await _cleanup(storage, name, league_id)
        if isinstance(error, _STORAGE_ERRORS):
            raise PictureStorageUnavailable from None
        raise
    return name


async def create_with_picture(
    session: AsyncSession,
    user_id: int,
    data: LeagueCreate,
    storage: BlobStorage | None,
    image: bytes,
    content_type: str | None,
) -> LeagueCreated:
    # Reserve the sequence value without inserting any rows. Upload outside the transaction.
    async with session.begin():
        league_id = (
            await session.execute(
                sa.select(sa.func.nextval(sa.func.pg_get_serial_sequence("league", "id")))
            )
        ).scalar_one()
    name = await _upload_new_picture(storage, league_id, image, content_type)
    try:
        return await create_league(
            session, user_id, data, reserved_id=league_id, picture_blob_name=name
        )
    except BaseException:
        await session.rollback()
        await _cleanup(storage, name, league_id)
        raise


async def _save_with_picture(
    session: AsyncSession,
    user_id: int,
    league_id: int,
    storage: BlobStorage | None,
    data: bytes,
    content_type: str | None,
    values: dict,
) -> LeagueDetail:
    await _authorized_name(session, user_id, league_id, admin=True)
    name = await _upload_new_picture(storage, league_id, data, content_type)
    try:
        result, previous = await _save_settings(
            session, user_id, league_id, values | {"picture_blob_name": name}
        )
    except BaseException:
        await _cleanup(storage, name, league_id)
        raise
    await _cleanup(storage, previous, league_id)
    return result


async def upload_picture(
    session: AsyncSession,
    user_id: int,
    league_id: int,
    storage: BlobStorage | None,
    data: bytes,
    content_type: str | None,
) -> LeagueDetail:
    return await _save_with_picture(session, user_id, league_id, storage, data, content_type, {})


async def remove_picture(
    session: AsyncSession, user_id: int, league_id: int, storage: BlobStorage | None
) -> LeagueDetail:
    result, previous = await _save_settings(
        session, user_id, league_id, {"picture_blob_name": None}
    )
    await _cleanup(storage, previous, league_id)
    return result


async def update_configuration(
    session: AsyncSession,
    user_id: int,
    league_id: int,
    data: LeagueConfiguration,
    storage: BlobStorage | None,
    image: bytes | None,
    content_type: str | None,
) -> LeagueDetail:
    values = {"name": data.name, "description": data.description}
    if image is not None:
        return await _save_with_picture(
            session, user_id, league_id, storage, image, content_type, values
        )
    if data.remove_picture:
        values["picture_blob_name"] = None
    result, previous = await _save_settings(session, user_id, league_id, values)
    if data.remove_picture:
        await _cleanup(storage, previous, league_id)
    return result


async def read_picture(
    session: AsyncSession, user_id: int, league_id: int, storage: BlobStorage | None
) -> bytes:
    name = await _authorized_name(session, user_id, league_id)
    return await _read_league_blob(storage, league_id, name)


async def read_invitation_picture(
    session: AsyncSession, token: str, storage: BlobStorage | None
) -> bytes:
    row = await invitation_record(session, token)
    await session.commit()
    return await _read_league_blob(storage, row.league_id, row.picture_blob_name)


async def _read_league_blob(storage: BlobStorage | None, league_id: int, name: str | None) -> bytes:
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
        await _member_picture(session, user_id, league_id)
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
