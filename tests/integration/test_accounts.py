import asyncio
from base64 import b64encode
from pathlib import Path
from uuid import UUID, uuid4

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
        user = await session.get(User, UUID(alice.json()["id"]))
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
    from uuid import UUID

    user_id = UUID(response.json()["id"])
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
