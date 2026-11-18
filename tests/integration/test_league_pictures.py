"""Private league pictures, member avatars and data-preserving upgrades."""

import os
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from PIL import Image
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.core.storage.azure import BlobStorage
from app.features.leagues import pictures
from app.features.leagues.calculation import weekly_bounds
from app.features.leagues.models import league, league_member
from app.features.leagues.result_models import league_result
from tests.integration.test_league_membership import league_api  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


def image(color="red"):
    output = BytesIO()
    Image.new("RGB", (40, 40), color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
async def picture_api(league_api):  # noqa: F811
    client, sessions = league_api
    account, url, key = (
        os.environ.get("TEST_AZURE_STORAGE_ACCOUNT_" + suffix) for suffix in ("NAME", "URL", "KEY")
    )
    if not all((account, url, key)):
        pytest.skip("Set explicit TEST_AZURE_STORAGE_ACCOUNT_NAME/URL/KEY for Azurite")
    settings = Settings(
        _env_file=None,
        app_env="test",
        postgres_password=SecretStr("unused"),
        azure_storage_account_name=account,
        azure_storage_account_url=url,
        azure_storage_account_key=SecretStr(key),
        azure_storage_media_base_url=url,
        azure_storage_profile_container="test-leagues-" + uuid4().hex,
    )
    storage = BlobStorage(settings)
    app = client._transport.app
    app.state.blob_storage = storage
    container = storage.client.get_container_client(settings.azure_storage_profile_container)
    await container.create_container(public_access=None)
    alice, bob, eve = (httpx.BasicAuth(name, "password") for name in ("alice", "bob", "eve"))
    ids = [(await client.get("/api/v1/me", auth=auth)).json()["id"] for auth in (alice, bob, eve)]
    created = await client.post(
        "/api/v1/leagues", auth=alice, json={"name": "Private pictures", "timezone": "UTC"}
    )
    assert created.status_code == 201 and created.json()["picture_url"] is None
    lid = created.json()["id"]
    invitation = (await client.post(f"/api/v1/leagues/{lid}/invitations", auth=alice)).json()
    await client.post(f"/api/v1/league-invitations/{invitation['token']}/accept", auth=bob)
    try:
        yield client, sessions, app, storage, container, (alice, bob, eve), ids, lid
    finally:
        await container.delete_container()
        app.state.blob_storage = None
        await storage.close()


async def test_private_picture_permissions_replacement_failure_and_removal(
    picture_api, monkeypatch
):
    client, sessions, app, storage, container, auths, _, lid = picture_api
    alice, bob, eve = auths
    path = f"/api/v1/leagues/{lid}/picture"

    async def upload(color="red", auth=alice, data=None, mime="image/png"):
        return await client.post(
            path, auth=auth, files={"file": ("league.png", data or image(color), mime)}
        )

    assert (await client.get(path, auth=alice)).status_code == 404
    assert (await client.get(path)).status_code == 401
    assert (await upload(auth=bob)).status_code == 403
    assert (await upload(auth=eve)).status_code == 404
    assert (await client.delete(path, auth=bob)).status_code == 403
    assert (await client.delete(path, auth=eve)).status_code == 404
    first = await upload()
    assert first.status_code == 200
    url = first.json()["picture_url"]
    assert url.startswith(path + "?v=") and "picture_blob_name" not in first.json()
    assert (await client.get(f"/api/v1/leagues/{lid}", auth=bob)).json()["picture_url"] == url
    assert (await client.get("/api/v1/leagues", auth=bob)).json()[0]["picture_url"] == url
    original = await client.get(url, auth=bob)
    assert original.status_code == 200 and original.headers["content-type"] == "image/jpeg"
    assert original.headers["cache-control"] == "private, no-store"
    assert (await client.get(url, auth=eve)).status_code == 404
    invite = await client.post(f"/api/v1/leagues/{lid}/invitations", auth=alice)
    token = invite.json()["token"]
    preview_path = f"/api/v1/league-invitations/{token}"
    assert (await client.get(preview_path, auth=eve)).json()["has_picture"] is True
    invite_photo = await client.get(preview_path + "/picture", auth=eve)
    assert invite_photo.content == original.content
    assert invite_photo.headers["cache-control"] == "private, no-store"
    assert (await client.get(preview_path + "/picture")).status_code == 401
    assert (
        await client.get("/api/v1/league-invitations/invalid/picture", auth=eve)
    ).status_code == 404
    async with sessions.begin() as session:
        await session.execute(
            sa.text("UPDATE league_invitation SET expires_at = now() - interval '1 second'")
        )
    assert (await client.get(preview_path + "/picture", auth=eve)).status_code == 410

    original_name = [blob.name async for blob in container.list_blobs()][0]
    assert not (await container.get_container_properties()).public_access
    async with httpx.AsyncClient() as anonymous:
        assert (await anonymous.get(f"{container.url}/{original_name}")).status_code in (403, 404)
    assert (await upload(data=b"bad")).status_code == 422
    assert (await upload(mime="image/gif")).status_code == 415
    assert (await upload(data=b"x" * (5 * 1024 * 1024 + 1))).status_code == 413

    original_upload = storage.upload_profile_picture

    async def unavailable(*args):
        raise TimeoutError

    monkeypatch.setattr(storage, "upload_profile_picture", unavailable)
    assert (await upload()).status_code == 503
    monkeypatch.setattr(storage, "upload_profile_picture", original_upload)
    original_get = pictures.get_league

    async def failed_response(*args):
        raise RuntimeError("synthetic league rollback")

    monkeypatch.setattr(pictures, "get_league", failed_response)
    with pytest.raises(RuntimeError, match="synthetic league rollback"):
        await upload("blue")
    monkeypatch.setattr(pictures, "get_league", original_get)
    assert [blob.name async for blob in container.list_blobs()] == [original_name]
    assert (await client.get(path, auth=alice)).content == original.content
    second = await upload("blue")
    assert second.json()["picture_url"] != url
    assert (await client.get(path, auth=bob)).content != original.content
    assert len([blob async for blob in container.list_blobs()]) == 1
    async with sessions() as session:
        reopened = await pictures.get_league(session, (second.json()["members"])[0]["user_id"], lid)
        assert reopened.picture_url == second.json()["picture_url"]
    # Unlinking does not depend on storage availability; cleanup is best effort.
    app.state.blob_storage = None
    for _ in range(2):
        assert (await client.delete(path, auth=alice)).json()["picture_url"] is None
    app.state.blob_storage = storage
    assert (await client.get(path, auth=alice)).status_code == 404
    await container.set_container_access_policy(signed_identifiers={}, public_access="blob")
    assert (await upload()).status_code == 503


async def test_member_avatars_are_current_private_and_not_historical_score_data(picture_api):
    client, sessions, _, _, _, auths, ids, lid = picture_api
    alice, bob, eve = auths
    a, b, e = ids
    profile_path = "/api/v1/me/profile/picture"
    assert (
        await client.post(profile_path, auth=bob, files={"file": ("bob.png", image(), "image/png")})
    ).status_code == 200
    detail = (await client.get(f"/api/v1/leagues/{lid}", auth=alice)).json()
    member = next(item for item in detail["members"] if item["user_id"] == b)
    path = member["picture_url"]
    assert path.startswith(f"/api/v1/leagues/{lid}/members/{b}/picture?v=")
    assert "picture_blob_name" not in member and "weight_kg" not in member
    original = await client.get(path, auth=alice)
    assert original.status_code == 200 and original.headers["cache-control"] == "private, no-store"
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, auth=eve)).status_code == 404
    assert (
        await client.get(f"/api/v1/leagues/{lid}/members/{e}/picture", auth=alice)
    ).status_code == 404
    standings = (await client.get(f"/api/v1/leagues/{lid}/standings", auth=alice)).json()
    assert next(row for row in standings["general"] if row["user_id"] == b)["picture_url"] == path
    assert all(
        next(row for row in item["standings"] if row["user_id"] == b)["picture_url"] == path
        for item in standings["rounds"]
    )

    # Seed one expired round for the test-owned league to verify immutable result identity.
    current, _ = weekly_bounds(datetime.now(UTC), "UTC")
    creation = current - timedelta(days=7)
    async with sessions.begin() as session:
        await session.execute(league.update().where(league.c.id == lid).values(created_at=creation))
        await session.execute(
            league_member.update()
            .where(league_member.c.league_id == lid)
            .values(joined_at=creation)
        )
    pending_path = f"/api/v1/leagues/{lid}/results/pending"
    pending = (await client.get(pending_path, auth=alice)).json()
    assert (
        pending
        and next(row for row in pending[0]["standings"] if row["user_id"] == b)["picture_url"]
        == path
    )
    async with sessions() as session:
        saved = await session.scalar(
            sa.select(league_result.c.snapshot).where(league_result.c.league_id == lid)
        )
        assert all("picture_url" not in row for row in saved["standings"])
    assert (
        await client.post(
            profile_path, auth=bob, files={"file": ("bob.png", image("blue"), "image/png")}
        )
    ).status_code == 200
    refreshed = (await client.get(pending_path, auth=alice)).json()
    row = next(row for row in refreshed[0]["standings"] if row["user_id"] == b)
    assert row["picture_url"] != path and row["score"] == "0"
    assert (await client.get(row["picture_url"], auth=alice)).content != original.content
    assert (await client.delete(profile_path, auth=bob)).status_code == 200
    assert (await client.get(path, auth=alice)).status_code == 404
    assert (
        await client.patch(
            "/api/v1/me/profile", auth=bob, json={"picture_url": "https://example.test/avatar.png"}
        )
    ).status_code == 200
    detail = (await client.get(f"/api/v1/leagues/{lid}", auth=alice)).json()
    assert (
        next(item for item in detail["members"] if item["user_id"] == b)["picture_url"]
        == "https://example.test/avatar.png"
    )
    # Re-check target membership rather than treating an earlier URL as permanent access.
    async with sessions.begin() as session:
        await session.execute(
            league_member.delete().where(
                league_member.c.league_id == lid, league_member.c.user_id == b
            )
        )
    assert (await client.get(path, auth=alice)).status_code == 404
    assert (
        await client.get(f"/api/v1/leagues/{lid}/members/{a}/picture", auth=bob)
    ).status_code == 404


async def test_picture_migration_preserves_league_membership_and_downgrade(integration_url):
    engine = create_async_engine(integration_url)
    schema = "league_picture_migration_" + uuid4().hex

    def migrate(connection, target, *, down=False):
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.attributes["connection"] = connection
        (command.downgrade if down else command.upgrade)(config, target)

    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await conn.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            await conn.run_sync(migrate, "20261117_03")
            uid = await conn.scalar(sa.text("INSERT INTO users DEFAULT VALUES RETURNING id"))
            lid = await conn.scalar(
                sa.text(
                    "INSERT INTO league (name, created_by, timezone) "
                    "VALUES ('kept', :uid, 'UTC') RETURNING id"
                ),
                {"uid": uid},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO league_member (user_id, league_id, role, joined_at) "
                    "VALUES (:uid, :lid, 'admin', now())"
                ),
                {"uid": uid, "lid": lid},
            )
            await conn.run_sync(migrate, "head")
            row = (
                await conn.execute(
                    sa.text("SELECT name, timezone, picture_blob_name FROM league WHERE id=:lid"),
                    {"lid": lid},
                )
            ).one()
            assert row.name == "kept" and row.timezone == "UTC" and row.picture_blob_name is None
            await conn.run_sync(lambda connection: migrate(connection, "20261117_03", down=True))
            assert (
                await conn.execute(
                    sa.text("SELECT role FROM league_member WHERE league_id=:lid"), {"lid": lid}
                )
            ).scalar_one() == "admin"
            assert (
                await conn.execute(sa.text("SELECT name FROM league WHERE id=:lid"), {"lid": lid})
            ).scalar_one() == "kept"
            await conn.run_sync(migrate, "head")
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
