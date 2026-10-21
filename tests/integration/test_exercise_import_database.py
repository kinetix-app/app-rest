"""Import permissions, atomicity and persistence against test-owned schemas/containers."""

import asyncio
import json
import logging
import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.storage.azure import BlobStorage
from app.features.training.models import exercise
from app.features.training.seed import seed_exercises
from app.features.training.seed_dataset import load_dataset

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def exercise_database(integration_url):
    schema = "seed_" + uuid4().hex
    admin = create_async_engine(integration_url)
    engine = create_async_engine(
        integration_url, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with admin.begin() as connection:
            await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))

            def migrate(conn):
                config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
                config.attributes["connection"] = conn
                command.upgrade(config, "head")

            await connection.run_sync(migrate)
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


class MemoryStorage:
    def __init__(self, engine):
        self.engine = engine
        self.blobs = {}
        self.fail_on = None
        self.check_sessions = True

    async def ensure_container(self):
        if self.check_sessions:
            assert self.engine.pool.checkedout() == 0

    async def upload(self, path, name, digest, content_type):
        if self.check_sessions:
            assert self.engine.pool.checkedout() == 0
        if self.fail_on and self.fail_on in name:
            raise OSError("test storage unavailable")
        self.blobs[name] = path.read_bytes()
        return "http://media.test/test-exercises/" + name


async def rows(sessions):
    async with sessions() as session:
        return (await session.execute(sa.select(exercise).order_by(exercise.c.id))).mappings().all()


async def test_seed_retries_preserve_ids_metadata_and_unrelated_records(
    exercise_database, exercise_export
):
    engine, sessions = exercise_database
    storage = MemoryStorage(engine)
    dataset = load_dataset(exercise_export)
    # Same provider ID can exist in a user's private catalogue; manual rows are independent.
    async with sessions.begin() as session:
        user_id = await session.scalar(sa.text("INSERT INTO users DEFAULT VALUES RETURNING id"))
        await session.execute(
            exercise.insert(),
            [
                {
                    "name": "Owned",
                    "activity_type": "gym",
                    "source": "ascend_edb_v2",
                    "external_id": "exr_seed_test",
                    "user_id": user_id,
                },
                {
                    "name": "Manual",
                    "activity_type": "gym",
                    "source": "manual",
                    "external_id": "exr_seed_test",
                    "user_id": None,
                },
            ],
        )
    assert await seed_exercises(dataset, storage, sessions) == {"exercises": 1, "media": 3}
    before = await rows(sessions)
    catalogue = before[-1]
    assert catalogue["user_id"] is None
    assert catalogue["imported_at"].tzinfo is not None
    for key, value in dataset[0].data.database_values().items():
        assert catalogue[key] == value
    assert catalogue["image_url"] == catalogue["image_urls"]["480p"]
    assert len(catalogue["image_urls"]) == 2
    assert catalogue["video_url"].startswith("http://media.test/test-exercises/")
    # Concurrent invocations are also protected by the partial unique index/upsert.
    storage.check_sessions = False
    await asyncio.gather(*(seed_exercises(dataset, storage, sessions) for _ in range(2)))
    after = await rows(sessions)
    assert [row["id"] for row in after] == [row["id"] for row in before]
    assert after[:2] == before[:2]
    assert len(storage.blobs) == 3
    await engine.dispose()
    assert [row["id"] for row in await rows(sessions)] == [row["id"] for row in before]
    # A missing upload never commits the changed metadata.
    dataset[0].data.name = "Changed metadata"
    storage.fail_on = dataset[0].video.blob_name
    with pytest.raises(OSError):
        await seed_exercises(dataset, storage, sessions)
    assert (await rows(sessions))[-1]["name"] == "Bench press"
    storage.fail_on = None
    await seed_exercises(dataset, storage, sessions)
    assert (await rows(sessions))[-1]["id"] == catalogue["id"]
    assert (await rows(sessions))[-1]["name"] == "Changed metadata"


async def test_database_failure_rolls_back_all_exercise_rows(exercise_database, exercise_export):
    import shutil

    engine, sessions = exercise_database
    storage = MemoryStorage(engine)
    shutil.copytree(exercise_export / "bench-press", exercise_export / "second-press")
    path = exercise_export / "second-press" / "data.json"
    metadata = json.loads(path.read_text())
    metadata["exerciseId"] = "exr_second"
    path.write_text(json.dumps(metadata))
    (exercise_export / "index.json").write_text(
        json.dumps({"exr_seed_test": "bench-press", "exr_second": "second-press"})
    )
    dataset = load_dataset(exercise_export)
    await seed_exercises(dataset, storage, sessions)
    before = await rows(sessions)
    dataset[0].data.name = "Must roll back"
    # Simulate invalid persistence after validation to force a real PostgreSQL error
    # on the second row, after the first row's UPDATE has executed.
    dataset[1].data.name = None
    with pytest.raises(DBAPIError):
        await seed_exercises(dataset, storage, sessions)
    assert await rows(sessions) == before
    dataset[1].data.name = "Second press"
    await seed_exercises(dataset, storage, sessions)
    assert (await rows(sessions))[0]["name"] == "Must roll back"


async def test_real_blob_upload_readback_rerun_and_database_persistence(
    exercise_database, exercise_export, caplog
):
    url = os.environ.get("TEST_AZURE_STORAGE_ACCOUNT_URL")
    key = os.environ.get("TEST_AZURE_STORAGE_ACCOUNT_KEY")
    account = os.environ.get("TEST_AZURE_STORAGE_ACCOUNT_NAME")
    if not url or not key or not account:
        pytest.skip("Set TEST_AZURE_STORAGE_ACCOUNT_NAME/URL/KEY for Azurite integration")
    _, sessions = exercise_database
    container = "test-exercises-" + uuid4().hex
    settings = Settings(
        _env_file=None,
        app_env="test",
        postgres_password=SecretStr("unused"),
        azure_storage_account_name=account,
        azure_storage_account_url=url,
        azure_storage_account_key=SecretStr(key),
        azure_storage_container=container,
        azure_storage_media_base_url=url,
        azure_storage_local_public_read=True,
    )
    storage = BlobStorage(settings)
    try:
        with caplog.at_level(logging.DEBUG):
            await storage.check()
        assert not any("Request URL" in record.getMessage() for record in caplog.records)
        assert not any(key in record.getMessage() for record in caplog.records)
        dataset = load_dataset(exercise_export)
        for _ in range(2):
            assert await seed_exercises(dataset, storage, sessions) == {"exercises": 1, "media": 3}
        assert len([blob async for blob in storage.container.list_blobs()]) == 3
        (record,) = await rows(sessions)
        async with httpx.AsyncClient() as client:
            for asset in dataset[0].assets:
                response = await client.get(storage.media_url(asset.blob_name))
                assert response.status_code == 200
                assert response.headers["content-type"] == asset.content_type
                assert sha256(response.content).hexdigest() == asset.digest
            response = await client.get(record["video_url"], headers={"Range": "bytes=0-3"})
            assert response.status_code == 206
        # Existing mismatched blobs cannot silently claim success.
        asset = dataset[0].video
        await storage.container.upload_blob(asset.blob_name, b"corrupt", overwrite=True)
        with pytest.raises(ValueError, match="content identity"):
            await seed_exercises(dataset, storage, sessions)
    finally:
        try:
            await storage.container.delete_container()
        finally:
            await storage.close()
