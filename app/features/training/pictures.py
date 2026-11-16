"""Owned routine covers in private storage; provider I/O never holds a transaction."""

import asyncio
from uuid import uuid4

import sqlalchemy as sa
from azure.core.exceptions import AzureError, ResourceNotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage.azure import BlobStorage
from app.features.accounts.errors import PictureMissing, PictureStorageUnavailable
from app.features.accounts.pictures import MAX_PICTURE_BYTES as MAX_PICTURE_BYTES
from app.features.accounts.pictures import normalize_picture
from app.features.training.errors import TrainingNotFound
from app.features.training.models import routine
from app.features.training.schemas import RoutineCreate, RoutineResponse
from app.features.training.service import create_routine, get_routine, validate_exercises
from app.features.training.units import WeightUnit

_STORAGE_ERRORS = (AzureError, TimeoutError, OSError, ValueError)


def _prefix(user_id: int, routine_id: int) -> str:
    return f"routines/{user_id}/{routine_id}/"


async def _owned_name(session: AsyncSession, user_id: int, routine_id: int) -> str | None:
    try:
        row = (
            await session.execute(
                sa.select(routine.c.picture_blob_name).where(
                    routine.c.id == routine_id,
                    routine.c.user_id == user_id,
                    routine.c.deleted_at.is_(None),
                )
            )
        ).first()
        if row is None:
            raise TrainingNotFound
        await session.commit()
        return row[0]
    except BaseException:
        await session.rollback()
        raise


async def _cleanup(storage: BlobStorage | None, name: str | None, prefix: str) -> None:
    if storage is None or name is None or not name.startswith(prefix):
        return
    try:
        await storage.delete_profile_picture(name)
    except _STORAGE_ERRORS:
        pass


async def _set_picture(
    session: AsyncSession, user_id: int, routine_id: int, name: str | None
) -> tuple[RoutineResponse, str | None]:
    try:
        row = (
            await session.execute(
                sa.select(routine.c.picture_blob_name)
                .where(
                    routine.c.id == routine_id,
                    routine.c.user_id == user_id,
                    routine.c.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).first()
        if row is None:
            raise TrainingNotFound
        await session.execute(
            sa.update(routine).where(routine.c.id == routine_id).values(picture_blob_name=name)
        )
        result = await get_routine(session, user_id, routine_id)
        await session.commit()
        return result, row[0]
    except BaseException:
        await session.rollback()
        raise


async def upload_picture(
    session: AsyncSession,
    user_id: int,
    routine_id: int,
    storage: BlobStorage | None,
    data: bytes,
    content_type: str | None,
) -> RoutineResponse:
    await _owned_name(session, user_id, routine_id)
    if storage is None:
        raise PictureStorageUnavailable
    normalized = await asyncio.to_thread(normalize_picture, data, content_type)
    prefix = _prefix(user_id, routine_id)
    name = f"{prefix}{uuid4().hex}.jpg"
    try:
        await storage.upload_profile_picture(name, normalized)
    except _STORAGE_ERRORS:
        await _cleanup(storage, name, prefix)
        raise PictureStorageUnavailable from None
    try:
        result, previous = await _set_picture(session, user_id, routine_id, name)
    except BaseException:
        await _cleanup(storage, name, prefix)
        raise
    await _cleanup(storage, previous, prefix)
    return result


async def create_with_picture(
    session: AsyncSession,
    user_id: int,
    data: RoutineCreate,
    storage: BlobStorage | None,
    image: bytes,
    content_type: str | None,
    weight_unit: WeightUnit = "kg",
) -> RoutineResponse:
    # Normalize before DB/provider operations. Reserving a sequence value creates no row.
    normalized = await asyncio.to_thread(normalize_picture, image, content_type)
    if storage is None:
        raise PictureStorageUnavailable
    try:
        await validate_exercises(session, user_id, data.exercises)
        routine_id = await session.scalar(
            sa.select(sa.func.nextval(sa.func.pg_get_serial_sequence("routine", "id")))
        )
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    prefix = _prefix(user_id, routine_id)
    name = f"{prefix}{uuid4().hex}.jpg"
    try:
        await storage.upload_profile_picture(name, normalized)
    except _STORAGE_ERRORS:
        await _cleanup(storage, name, prefix)
        raise PictureStorageUnavailable from None
    try:
        return await create_routine(
            session, user_id, data, weight_unit, reserved_id=routine_id, picture_blob_name=name
        )
    except BaseException:
        await session.rollback()
        await _cleanup(storage, name, prefix)
        raise


async def remove_picture(
    session: AsyncSession, user_id: int, routine_id: int, storage: BlobStorage | None
) -> RoutineResponse:
    result, previous = await _set_picture(session, user_id, routine_id, None)
    await _cleanup(storage, previous, _prefix(user_id, routine_id))
    return result


async def read_picture(
    session: AsyncSession, user_id: int, routine_id: int, storage: BlobStorage | None
) -> bytes:
    name = await _owned_name(session, user_id, routine_id)
    if name is None or not name.startswith(_prefix(user_id, routine_id)):
        raise PictureMissing
    if storage is None:
        raise PictureStorageUnavailable
    try:
        return await storage.read_profile_picture(name)
    except ResourceNotFoundError:
        raise PictureMissing from None
    except _STORAGE_ERRORS:
        raise PictureStorageUnavailable from None
