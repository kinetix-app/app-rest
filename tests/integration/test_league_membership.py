"""Authenticated membership and legacy-data upgrade coverage."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from pydantic import SecretStr
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.features.leagues.models import league, league_invitation, league_member
from app.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def league_api(integration_url):
    schema = "league_" + uuid4().hex
    admin = create_async_engine(integration_url)
    engine = create_async_engine(
        integration_url, connect_args={"server_settings": {"search_path": schema}}
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with admin.begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await conn.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))

            def upgrade(connection, target):
                config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
                config.attributes["connection"] = connection
                command.upgrade(config, target)

            await conn.run_sync(upgrade, "20261116_04")
            user = await conn.scalar(sa.text("INSERT INTO users DEFAULT VALUES RETURNING id"))
            old_id = await conn.scalar(
                sa.text("INSERT INTO league (name, created_by) VALUES ('old', :id) RETURNING id"),
                {"id": user},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO league_member (league_id, user_id, joined_date) "
                    "VALUES (:league, :user, '2020-01-02')"
                ),
                {"league": old_id, "user": user},
            )
            await conn.run_sync(upgrade, "head")
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT joined_date, joined_at, role FROM league_member WHERE league_id=:id"
                    ),
                    {"id": old_id},
                )
            ).one()
            assert (
                str(row.joined_date) == "2020-01-02" and row.joined_at is None and row.role is None
            )
            assert (
                await conn.scalar(
                    sa.text("SELECT timezone FROM league WHERE id=:id"), {"id": old_id}
                )
                is None
            )
        settings = Settings(
            _env_file=None,
            app_env="test",
            auth_mode="basic",
            basic_auth_users={name: SecretStr("password") for name in ("alice", "bob", "eve")},
            database_url=SecretStr(integration_url.render_as_string(hide_password=False)),
        )
        app = create_app(settings)
        async with LifespanManager(app):
            app.state.session_factory = sessions
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client, sessions
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def test_membership_invitation_permissions_and_persistence(league_api):
    client, sessions = league_api
    alice, bob, eve = (httpx.BasicAuth(name, "password") for name in ("alice", "bob", "eve"))
    assert (await client.get("/api/v1/leagues")).status_code == 401
    for payload in (
        {"name": " ", "timezone": "UTC"},
        {"name": "a", "timezone": "invalid"},
        {"name": "a", "timezone": "UTC", "role": "admin"},
    ):
        assert (await client.post("/api/v1/leagues", json=payload, auth=alice)).status_code == 422
    created = await client.post(
        "/api/v1/leagues", json={"name": " First ", "timezone": "Europe/Madrid"}, auth=alice
    )
    assert created.status_code == 201
    first = created.json()
    assert first["name"] == "First" and first["role"] == "admin"
    league_id = first["id"]
    assert (
        await client.post("/api/v1/leagues", json={"name": "Second", "timezone": "UTC"}, auth=alice)
    ).status_code == 201
    assert len((await client.get("/api/v1/leagues", auth=alice)).json()) == 2
    assert (await client.get(f"/api/v1/leagues/{league_id}", auth=bob)).status_code == 404
    assert (
        await client.patch(f"/api/v1/leagues/{league_id}", json={"name": "x"}, auth=bob)
    ).status_code == 404
    assert (
        await client.patch(f"/api/v1/leagues/{league_id}", json={"name": None}, auth=alice)
    ).status_code == 422
    invitation = await client.post(f"/api/v1/leagues/{league_id}/invitations", auth=alice)
    assert invitation.status_code == 201
    token = invitation.json()["token"]
    async with sessions() as session:
        assert await session.scalar(sa.select(league_invitation.c.token_hash)) != token
    assert (await client.get(f"/api/v1/league-invitations/{token}", auth=bob)).json()[
        "name"
    ] == "First"
    joined = await client.post(f"/api/v1/league-invitations/{token}/accept", auth=bob)
    assert joined.status_code == 200 and joined.json()["role"] == "member"
    joined_at = joined.json()["members"][1]["joined_at"]
    assert joined_at is not None
    assert (await client.post(f"/api/v1/league-invitations/{token}/accept", auth=bob)).json()[
        "members"
    ][1]["joined_at"] == joined_at
    assert (await client.post(f"/api/v1/league-invitations/{token}/accept", auth=alice)).json()[
        "role"
    ] == "admin"
    assert (
        await client.patch(f"/api/v1/leagues/{league_id}", json={"name": "x"}, auth=bob)
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/leagues/{league_id}/invitations", auth=bob)
    ).status_code == 403
    assert (
        await client.patch(f"/api/v1/leagues/{league_id}", json={"name": "Renamed"}, auth=alice)
    ).json()["name"] == "Renamed"
    assert (await client.get(f"/api/v1/leagues/{league_id}", auth=bob)).json()["name"] == "Renamed"
    assert (await client.get(f"/api/v1/leagues/{league_id}", auth=eve)).status_code == 404
    assert (await client.get("/api/v1/league-invitations/invalid", auth=eve)).status_code == 404
    async with sessions.begin() as session:
        await session.execute(
            league_invitation.update().values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert (
        await client.post(f"/api/v1/league-invitations/{token}/accept", auth=eve)
    ).status_code == 410
    async with sessions() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(league).where(league.c.id == league_id)
            )
            == 1
        )
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(league_member)
                .where(league_member.c.league_id == league_id)
            )
            == 2
        )


async def test_creation_rolls_back_when_membership_fails(league_api):
    client, sessions = league_api
    alice = httpx.BasicAuth("alice", "password")
    await client.get("/api/v1/me", auth=alice)
    async with sessions.begin() as session:
        await session.execute(
            sa.text("""
            CREATE FUNCTION reject_membership() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'test rejection'; END $$
        """)
        )
        await session.execute(
            sa.text("""
            CREATE TRIGGER reject_membership BEFORE INSERT ON league_member
            FOR EACH ROW EXECUTE FUNCTION reject_membership()
        """)
        )
    with pytest.raises(DBAPIError):
        await client.post(
            "/api/v1/leagues", json={"name": "rollback", "timezone": "UTC"}, auth=alice
        )
    async with sessions() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(league).where(league.c.name == "rollback")
            )
            == 0
        )
