import asyncio
from base64 import b64encode
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from pydantic import SecretStr
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.features.accounts import service
from app.features.accounts.models import AuthAccount, Profile, User
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def migrated_accounts(integration_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", integration_url.render_as_string(hide_password=False))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    return integration_url


@pytest.fixture
async def account_client(migrated_accounts, clerk_jwks):
    issuer = f"https://auth-{uuid4().hex}.clerk.accounts.dev"
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_mode="clerk",
        clerk_issuer=issuer,
        clerk_secret_key=SecretStr("sk_test_backend_only"),
        database_url=SecretStr(migrated_accounts.render_as_string(hide_password=False)),
    )
    app = create_app(settings)
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            try:
                yield client, app, issuer
            finally:
                async with app.state.session_factory() as session:
                    ids = list(
                        (
                            await session.scalars(
                                select(AuthAccount.user_id).where(AuthAccount.issuer == issuer)
                            )
                        ).all()
                    )
                    await session.execute(delete(AuthAccount).where(AuthAccount.issuer == issuer))
                    await session.execute(delete(User).where(User.id.in_(ids)))
                    await session.commit()


@pytest.fixture
async def basic_account_client(migrated_accounts):
    username = f"dev-{uuid4().hex}@example.test"
    other_username = f"dev-{uuid4().hex}@example.test"
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_mode="basic",
        basic_auth_users={
            username: SecretStr("integration-password"),
            other_username: SecretStr("other-integration-password"),
        },
        database_url=SecretStr(migrated_accounts.render_as_string(hide_password=False)),
    )
    app = create_app(settings)
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            try:
                yield client, app, username, other_username
            finally:
                async with app.state.session_factory() as session:
                    ids = list(
                        (
                            await session.scalars(
                                select(AuthAccount.user_id).where(
                                    AuthAccount.issuer == "urn:kinetix:dev",
                                    AuthAccount.subject.in_([username, other_username]),
                                )
                            )
                        ).all()
                    )
                    await session.execute(
                        delete(AuthAccount).where(
                            AuthAccount.issuer == "urn:kinetix:dev",
                            AuthAccount.subject.in_([username, other_username]),
                        )
                    )
                    await session.execute(delete(User).where(User.id.in_(ids)))
                    await session.commit()


def headers(signed_token, issuer, **claims):
    return {"Authorization": "Bearer " + signed_token(issuer=issuer, **claims)}


@pytest.mark.anyio
async def test_development_basic_auth_provisions_account_over_me_endpoint(basic_account_client):
    client, app, username, _ = basic_account_client
    token = b64encode(f"{username}:integration-password".encode()).decode()
    response = await client.get("/api/v1/me", headers={"Authorization": f"Basic {token}"})

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    account_id = response.json()["id"]
    assert isinstance(account_id, int)
    assert account_id > 0
    auth = {"Authorization": f"Basic {token}"}
    updated = await client.patch(
        "/api/v1/me/profile", headers=auth, json={"display_name": "Basic test user"}
    )
    assert updated.status_code == 200
    repeated = await client.get("/api/v1/me", headers=auth)
    assert repeated.status_code == 200
    assert repeated.json()["id"] == account_id
    assert repeated.json()["profile"]["display_name"] == "Basic test user"
    wrong = b64encode(f"{username}:wrong-password".encode()).decode()
    rejected = await client.get("/api/v1/me", headers={"Authorization": f"Basic {wrong}"})
    assert rejected.status_code == 401
    assert rejected.headers["WWW-Authenticate"] == "Basic"
    async with app.state.session_factory() as session:
        mapping = await session.scalar(
            select(AuthAccount).where(
                AuthAccount.issuer == "urn:kinetix:dev", AuthAccount.subject == username
            )
        )
        assert mapping is not None


@pytest.mark.anyio
async def test_basic_accounts_are_isolated_and_blocked_accounts_stay_denied(basic_account_client):
    client, app, username, other_username = basic_account_client
    first = {
        "Authorization": "Basic " + b64encode(f"{username}:integration-password".encode()).decode()
    }
    second = {
        "Authorization": "Basic "
        + b64encode(f"{other_username}:other-integration-password".encode()).decode()
    }
    alice = await client.patch("/api/v1/me/profile", headers=first, json={"display_name": "Alice"})
    bob = await client.get("/api/v1/me", headers=second)
    assert alice.status_code == bob.status_code == 200
    assert alice.json()["id"] != bob.json()["id"]
    assert bob.json()["profile"]["display_name"] is None
    assert (await client.get("/api/v1/me", headers=first)).json()["profile"][
        "display_name"
    ] == "Alice"
    async with app.state.session_factory() as session:
        user = await session.get(User, alice.json()["id"])
        assert user is not None
        user.status = "blocked"
        await session.commit()
    assert (await client.get("/api/v1/me", headers=first)).status_code == 403
    assert (await client.get("/api/v1/me", headers=second)).json()["id"] == bob.json()["id"]


@pytest.mark.anyio
async def test_provisioning_profile_patch_and_two_account_isolation(account_client, signed_token):
    client, app, issuer = account_client
    alice = headers(signed_token, issuer)
    bob = headers(signed_token, issuer, sub="user_bob", sid="sess_bob")
    first = await client.get("/api/v1/me", headers=alice)
    assert first.status_code == 200
    user_id = first.json()["id"]
    edited = await client.patch(
        "/api/v1/me/profile",
        headers=alice,
        json={"display_name": "Alice", "timezone": "Europe/Madrid"},
    )
    assert edited.status_code == 200
    other = await client.get("/api/v1/me", headers=bob)
    assert other.json()["id"] != user_id
    assert other.json()["profile"]["display_name"] is None
    await client.patch("/api/v1/me/profile", headers=alice, json={"display_name": None})
    reopened = await client.get(
        "/api/v1/me", headers=headers(signed_token, issuer, sid="sess_renewed")
    )
    assert reopened.json()["id"] == user_id
    assert reopened.json()["profile"]["display_name"] is None
    assert reopened.json()["profile"]["timezone"] == "Europe/Madrid"
    forbidden = await client.patch("/api/v1/me/profile", headers=bob, json={"user_id": user_id})
    assert forbidden.status_code == 422
    async with app.state.session_factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(AuthAccount).where(AuthAccount.issuer == issuer)
            )
            == 2
        )
    # Reopen through a completely new application/pool with the same DB and issuer.
    restarted = create_app(app.state.settings)
    async with LifespanManager(restarted):
        restarted.state.clerk_verifier = app.state.clerk_verifier
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://test"
        ) as fresh:
            response = await fresh.get("/api/v1/me", headers=alice)
            assert response.json()["id"] == user_id
            assert response.json()["profile"]["timezone"] == "Europe/Madrid"


@pytest.mark.anyio
async def test_invalid_tokens_create_no_accounts(account_client, signed_token):
    client, app, issuer = account_client
    async with app.state.session_factory() as session:
        before = await session.scalar(select(func.count()).select_from(User))
    for credential in [
        headers(signed_token, issuer, exp=1),
        headers(signed_token, "https://wrong.example"),
        {"Authorization": "Bearer malformed"},
    ]:
        response = await client.get("/api/v1/me", headers=credential)
        assert response.status_code == 401
    async with app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == before
        assert (
            await session.scalar(
                select(func.count()).select_from(AuthAccount).where(AuthAccount.issuer == issuer)
            )
            == 0
        )


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["blocked", "deleted"])
async def test_denied_identities_are_never_recreated(account_client, signed_token, status):
    client, app, issuer = account_client
    credential = headers(signed_token, issuer)
    response = await client.get("/api/v1/me", headers=credential)
    user_id = response.json()["id"]
    async with app.state.session_factory() as session:
        await session.execute(update(User).where(User.id == user_id).values(status=status))
        await session.commit()
    assert (await client.get("/api/v1/me", headers=credential)).status_code == 403
    assert (
        await client.patch(
            "/api/v1/me/profile", headers=credential, json={"display_name": "Revive"}
        )
    ).status_code == 403
    async with app.state.session_factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(AuthAccount).where(AuthAccount.issuer == issuer)
            )
            == 1
        )


@pytest.mark.anyio
async def test_concurrent_first_access_has_no_duplicate_or_orphan_users(
    account_client, signed_token, monkeypatch
):
    client, app, issuer = account_client
    original = service._find_identity
    gate = asyncio.Event()
    arrived = 0

    async def synchronized(session, identity):
        nonlocal arrived
        user = await original(session, identity)
        if user is None:
            arrived += 1
            if arrived == 4:
                gate.set()
            await asyncio.wait_for(gate.wait(), timeout=10)
        return user

    monkeypatch.setattr(service, "_find_identity", synchronized)
    async with app.state.session_factory() as session:
        before = await session.scalar(select(func.count()).select_from(User))
    responses = await asyncio.gather(
        *[client.get("/api/v1/me", headers=headers(signed_token, issuer)) for _ in range(4)]
    )
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    async with app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == before + 1
        assert (
            await session.scalar(
                select(func.count()).select_from(AuthAccount).where(AuthAccount.issuer == issuer)
            )
            == 1
        )


@pytest.mark.anyio
async def test_mapping_failure_rolls_back_user_and_profile(
    account_client, signed_token, monkeypatch
):
    client, app, issuer = account_client
    original = AsyncSession.flush

    async def fail_mapping(session, *args, **kwargs):
        if any(isinstance(obj, AuthAccount) for obj in session.new):
            raise IntegrityError("synthetic mapping failure", {}, Exception("failure"))
        return await original(session, *args, **kwargs)

    async with app.state.session_factory() as session:
        before = await session.scalar(select(func.count()).select_from(User))
        profiles_before = await session.scalar(select(func.count()).select_from(Profile))
    monkeypatch.setattr(AsyncSession, "flush", fail_mapping)
    auth_headers = headers(signed_token, issuer)
    with pytest.raises(IntegrityError):
        await client.get("/api/v1/me", headers=auth_headers)
    async with app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == before
        assert await session.scalar(select(func.count()).select_from(Profile)) == profiles_before


@pytest.mark.anyio
async def test_onboarding_profile_objective_persistence_and_clearing(account_client, signed_token):
    client, app, issuer = account_client
    alice = headers(signed_token, issuer)
    bob = headers(signed_token, issuer, sub="user_bob", sid="sess_bob")
    first = await client.get("/api/v1/auth/me", headers=alice)
    assert first.status_code == 200
    assert first.json()["onboarding"] == {
        "profile_complete": False,
        "objective_selected": False,
        "required": True,
    }
    assert (await client.get("/api/v1/me/objective", headers=alice)).json() == {"objective": None}
    profile = {
        "display_name": " Alice ",
        "age": 30,
        "height_cm": "170.25",
        "weight_kg": "68.038855",
        "picture_url": "",
    }
    partial = await client.patch("/api/v1/me/profile", headers=alice, json=profile)
    assert partial.status_code == 200
    assert partial.json()["profile"]["measurement_system"] is None
    assert partial.json()["onboarding"]["profile_complete"] is False
    complete = await client.patch(
        "/api/v1/me/profile", headers=alice, json={"measurement_system": "imperial"}
    )
    assert complete.json()["profile"]["weight_kg"] == "68.038855"
    assert complete.json()["profile"]["height_cm"] == "170.25"
    assert complete.json()["profile"]["measurement_system"] == "imperial"
    assert complete.json()["profile"]["display_name"] == "Alice"
    assert complete.json()["profile"]["picture_url"] is None
    assert complete.json()["onboarding"]["profile_complete"] is True
    assert complete.json()["onboarding"]["required"] is True
    for objective in ("build_muscle", "lose_fat", "gain_weight", "maintain_weight"):
        response = await client.put(
            "/api/v1/me/objective", headers=alice, json={"objective": objective}
        )
        assert response.status_code == 200
        assert response.json() == {"objective": objective}
        assert (await client.get("/api/v1/auth/me", headers=alice)).json()["onboarding"] == {
            "profile_complete": True,
            "objective_selected": True,
            "required": False,
        }
    other = await client.get("/api/v1/auth/me", headers=bob)
    assert other.json()["profile"]["age"] is None
    assert other.json()["onboarding"]["required"] is True
    assert (await client.get("/api/v1/me/objective", headers=bob)).json() == {"objective": None}
    restarted = create_app(app.state.settings)
    async with LifespanManager(restarted):
        restarted.state.clerk_verifier = app.state.clerk_verifier
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://test"
        ) as fresh:
            saved = await fresh.get("/api/v1/auth/me", headers=alice)
            assert saved.json()["onboarding"]["required"] is False
            assert saved.json()["profile"]["height_cm"] == "170.25"
            assert saved.json()["profile"]["measurement_system"] == "imperial"
            assert (await fresh.get("/api/v1/me/objective", headers=alice)).json() == {
                "objective": "maintain_weight"
            }
    switched = await client.patch(
        "/api/v1/me/profile", headers=alice, json={"measurement_system": "metric"}
    )
    assert switched.json()["profile"]["measurement_system"] == "metric"
    assert switched.json()["profile"]["height_cm"] == "170.25"
    assert switched.json()["profile"]["weight_kg"] == "68.038855"
    cleared = await client.patch(
        "/api/v1/me/profile", headers=alice, json={"measurement_system": None}
    )
    assert cleared.json()["onboarding"] == {
        "profile_complete": False,
        "objective_selected": True,
        "required": True,
    }
    assert cleared.json()["profile"]["age"] == 30
    assert (
        await client.patch("/api/v1/me/profile", headers=alice, json={})
    ).json() == cleared.json()


@pytest.mark.anyio
async def test_setup_rejects_invalid_fields_and_client_ownership(account_client, signed_token):
    client, app, issuer = account_client
    alice = headers(signed_token, issuer)
    for changes in (
        {"age": 0},
        {"age": 121},
        {"age": 30.5},
        {"age": True},
        {"height_cm": 0},
        {"height_cm": 301},
        {"height_cm": "170.251"},
        {"weight_kg": 0},
        {"weight_kg": 1001},
        {"weight_kg": "1.0000001"},
        {"weight_kg": "NaN"},
        {"measurement_system": "stone"},
        {"measurement_system": "kg"},
        {"weight_unit": "lb"},
        {"picture_url": "http://example.test/a.png"},
        {"picture_url": "data:image/png;base64,a"},
        {"picture_url": "https://user:secret@example.test/a.png"},
        {"display_name": " "},
        {"user_id": 123},
    ):
        assert (
            await client.patch("/api/v1/me/profile", headers=alice, json=changes)
        ).status_code == 422
    for value in (
        {},
        {"objective": None},
        {"objective": "bulk"},
        {"objective": "lose_fat", "user_id": 1},
    ):
        assert (
            await client.put("/api/v1/me/objective", headers=alice, json=value)
        ).status_code == 422
    good = await client.patch(
        "/api/v1/me/profile", headers=alice, json={"picture_url": "https://example.test/avatar.png"}
    )
    assert good.status_code == 200
    assert good.json()["profile"]["picture_url"] == "https://example.test/avatar.png"
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/me/objective")).status_code == 401
    user_id = good.json()["id"]
    async with app.state.session_factory() as session:
        await session.execute(update(User).where(User.id == user_id).values(status="blocked"))
        await session.commit()
    assert (
        await client.put("/api/v1/me/objective", headers=alice, json={"objective": "lose_fat"})
    ).status_code == 403


@pytest.mark.anyio
async def test_profile_and_objective_failures_roll_back(account_client, signed_token, monkeypatch):
    from app.features.goals.models import AccountObjective

    client, app, issuer = account_client
    alice = headers(signed_token, issuer)
    first = await client.get("/api/v1/auth/me", headers=alice)
    user_id = first.json()["id"]
    original = AsyncSession.commit

    async def fail_setup_commit(session):
        if any(
            isinstance(row, (Profile, AccountObjective)) for row in [*session.new, *session.dirty]
        ):
            await session.flush()
            raise RuntimeError("synthetic setup persistence failure")
        # Profile service explicitly flushes before commit, so identify its transaction too.
        profile = session.identity_map.get((Profile, (user_id,), None))
        if profile is not None and profile.display_name == "Uncommitted":
            raise RuntimeError("synthetic setup persistence failure")
        await original(session)

    monkeypatch.setattr(AsyncSession, "commit", fail_setup_commit)
    with pytest.raises(RuntimeError, match="synthetic setup persistence failure"):
        await client.put("/api/v1/me/objective", headers=alice, json={"objective": "build_muscle"})
    with pytest.raises(RuntimeError, match="synthetic setup persistence failure"):
        await client.patch(
            "/api/v1/me/profile", headers=alice, json={"display_name": "Uncommitted"}
        )
    monkeypatch.setattr(AsyncSession, "commit", original)
    assert (await client.get("/api/v1/me/objective", headers=alice)).json() == {"objective": None}
    saved = await client.get("/api/v1/auth/me", headers=alice)
    assert saved.json()["profile"]["display_name"] is None
    assert saved.json()["onboarding"]["required"] is True


@pytest.mark.anyio
async def test_private_picture_upload_isolation_replacement_and_failure(
    account_client, signed_token, monkeypatch
):
    import os
    from io import BytesIO

    from azure.core.exceptions import ResourceNotFoundError
    from PIL import Image

    from app.core.storage.azure import BlobStorage
    from app.features.accounts import pictures

    client, app, issuer = account_client
    url = os.environ.get("TEST_AZURE_STORAGE_ACCOUNT_URL")
    key = os.environ.get("TEST_AZURE_STORAGE_ACCOUNT_KEY")
    account = os.environ.get("TEST_AZURE_STORAGE_ACCOUNT_NAME")
    if not all((url, key, account)):
        pytest.skip("Set explicit TEST_AZURE_STORAGE_ACCOUNT_NAME/URL/KEY for Azurite integration")
    settings = Settings(
        _env_file=None,
        app_env="test",
        postgres_password=SecretStr("unused"),
        azure_storage_account_name=account,
        azure_storage_account_url=url,
        azure_storage_account_key=SecretStr(key),
        azure_storage_media_base_url=url,
        azure_storage_container="test-exercises-" + uuid4().hex,
        azure_storage_profile_container="test-profiles-" + uuid4().hex,
        azure_storage_local_public_read=True,
    )
    storage = BlobStorage(settings)
    app.state.blob_storage = storage
    container = storage.client.get_container_client(settings.azure_storage_profile_container)
    alice = headers(signed_token, issuer)
    bob = headers(signed_token, issuer, sub="user_bob", sid="sess_bob")
    route = "/api/v1/me/profile/picture"

    def image(color="red"):
        output = BytesIO()
        exif = Image.Exif()
        exif[270] = "Private location metadata"
        Image.new("RGB", (80, 80), color).save(output, format="PNG", exif=exif)
        return output.getvalue()

    async def upload(data=None, mime="image/png"):
        return await client.post(
            route, headers=alice, files={"file": ("photo.png", data or image(), mime)}
        )

    try:
        assert (
            await client.post(route, files={"file": ("photo.png", image(), "image/png")})
        ).status_code == 401
        created = await upload()
        assert created.status_code == 200
        assert created.json()["profile"]["picture_url"] == route
        assert "picture_blob_name" not in created.json()["profile"]
        assert created.json()["onboarding"]["required"] is True
        first_blob = [blob async for blob in container.list_blobs()][0].name
        assert not (await container.get_container_properties()).public_access
        async with httpx.AsyncClient() as anonymous:
            assert (await anonymous.get(f"{container.url}/{first_blob}")).status_code in (403, 404)
        fetched = await client.get(route, headers=alice)
        assert fetched.status_code == 200
        assert fetched.headers["content-type"] == "image/jpeg"
        assert fetched.headers["cache-control"] == "private, no-store"
        with Image.open(BytesIO(fetched.content)) as decoded:
            assert not decoded.getexif()
        assert (await client.get(route)).status_code == 401
        assert (await client.get(route, headers=bob)).status_code == 404
        assert (await client.delete(route, headers=bob)).status_code == 200
        assert (await client.get(route, headers=alice)).content == fetched.content
        # Saving remaining profile fields must preserve the uploaded photo.
        patched = await client.patch(
            "/api/v1/me/profile", headers=alice, json={"display_name": "Photo owner"}
        )
        assert patched.json()["profile"]["picture_url"] == route
        assert (await upload(b"broken")).status_code == 422
        assert (await upload(image(), "text/plain")).status_code == 415
        assert (await upload(image(), "image/jpeg")).status_code == 415
        assert (await upload(b"a" * (5 * 1024 * 1024 + 1))).status_code == 413
        assert (await client.get(route, headers=alice)).content == fetched.content
        # Provider failure cannot overwrite the old reference.
        original_upload = storage.upload_profile_picture

        async def unavailable(*args):
            raise TimeoutError

        monkeypatch.setattr(storage, "upload_profile_picture", unavailable)
        assert (await upload()).status_code == 503
        monkeypatch.setattr(storage, "upload_profile_picture", original_upload)
        assert (await client.get(route, headers=alice)).content == fetched.content
        # Persistence rollback deletes only the newly uploaded object.
        original_read = pictures.read_account

        async def failed_response(*args):
            raise RuntimeError("Synthetic photo persistence failure")

        monkeypatch.setattr(pictures, "read_account", failed_response)
        replacement_picture = image("blue")
        with pytest.raises(RuntimeError, match="Synthetic photo persistence failure"):
            await upload(replacement_picture)
        monkeypatch.setattr(pictures, "read_account", original_read)
        assert [blob.name async for blob in container.list_blobs()] == [first_blob]
        assert (await client.get(route, headers=alice)).content == fetched.content
        replaced = await upload(image("blue"))
        assert replaced.status_code == 200
        assert (await client.get(route, headers=alice)).content != fetched.content
        first_blob_client = container.get_blob_client(first_blob)
        with pytest.raises(ResourceNotFoundError):
            await first_blob_client.get_blob_properties()
        # Reopen from a new app/pool to verify DB and Azure persistence.
        restarted = create_app(app.state.settings)
        async with LifespanManager(restarted):
            restarted.state.clerk_verifier = app.state.clerk_verifier
            restarted.state.blob_storage = storage
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=restarted), base_url="http://test"
            ) as fresh:
                assert (await fresh.get(route, headers=alice)).status_code == 200
            restarted.state.blob_storage = None
        for _ in range(2):
            removed = await client.delete(route, headers=alice)
            assert removed.status_code == 200
            assert removed.json()["profile"]["picture_url"] is None
            assert removed.json()["profile"]["display_name"] == "Photo owner"
        assert (await client.get(route, headers=alice)).status_code == 404
        assert [blob async for blob in container.list_blobs()] == []
        await upload()
        legacy = await client.patch(
            "/api/v1/me/profile",
            headers=alice,
            json={"picture_url": "https://example.test/legacy.jpg"},
        )
        assert legacy.status_code == 200
        assert (await client.get(route, headers=alice)).status_code == 404
        assert [blob async for blob in container.list_blobs()] == []
        assert (await client.delete(route, headers=alice)).json()["profile"]["picture_url"] is None
        # Existing public containers cannot be reused for private profile images.
        await container.set_container_access_policy(signed_identifiers={}, public_access="blob")
        assert (await upload()).status_code == 503
    finally:
        await container.delete_container()
        app.state.blob_storage = None
        await storage.close()
