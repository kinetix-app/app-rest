"""Private standings and upgrade coverage using isolated PostgreSQL data."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa

from app.features.leagues.calculation import weekly_bounds
from app.features.leagues.models import league, league_member, league_score
from app.features.leagues.scoring import ensure_round
from app.features.training.models import training_session
from tests.integration.test_league_membership import league_api  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def seed_score(session, lid, user_id, moment, score):
    row = (await session.execute(sa.select(league).where(league.c.id == lid))).mappings().one()
    round_row = await ensure_round(session, row, moment)
    source = await session.scalar(
        training_session.insert()
        .values(
            user_id=user_id,
            activity_type="gym",
            started_at=moment,
            ended_at=moment + timedelta(hours=1),
            league_score=score,
            league_volume_kg_reps=800,
            league_duration_us=3600000000,
            league_body_weight_kg=80,
            league_formula_version="test-v1",
        )
        .returning(training_session.c.id)
    )
    await session.execute(
        league_score.insert().values(
            league_id=lid,
            user_id=user_id,
            local_day=moment.date(),
            round_id=round_row.id,
            session_id=source,
            score=score,
            volume_kg_reps=800,
            duration_us=3600000000,
            body_weight_kg=80,
            ended_at=moment + timedelta(hours=1),
            formula_version="test-v1",
        )
    )
    return round_row


async def test_standings_private_totals_ranking_and_source_details(league_api):  # noqa: F811
    client, sessions = league_api
    alice, bob, eve = (httpx.BasicAuth(name, "password") for name in ("alice", "bob", "eve"))
    a, b, e = [
        (await client.get("/api/v1/me", auth=auth)).json()["id"] for auth in (alice, bob, eve)
    ]
    lid = (
        await client.post("/api/v1/leagues", auth=alice, json={"name": "test", "timezone": "UTC"})
    ).json()["id"]
    current, _ = weekly_bounds(datetime.now(UTC), "UTC")
    async with sessions.begin() as session:
        await session.execute(
            league.update().where(league.c.id == lid).values(created_at=current - timedelta(days=7))
        )
        await session.execute(
            league_member.update()
            .where(league_member.c.league_id == lid)
            .values(joined_at=current - timedelta(days=7))
        )
        await session.execute(
            league_member.insert(),
            [
                {
                    "league_id": lid,
                    "user_id": b,
                    "role": "member",
                    "joined_at": current - timedelta(days=7),
                },
                {
                    "league_id": lid,
                    "user_id": e,
                    "role": "member",
                    "joined_at": current - timedelta(days=7),
                },
            ],
        )
        await seed_score(session, lid, a, current - timedelta(days=6), 10)
        await seed_score(session, lid, b, current - timedelta(days=6), 10)
        await seed_score(session, lid, a, current + timedelta(hours=1), 7)
    outsider = httpx.BasicAuth("outsider", "password")
    assert (await client.get(f"/api/v1/leagues/{lid}/standings")).status_code == 401
    assert (
        await client.get(f"/api/v1/leagues/{lid + 9999}/standings", auth=alice)
    ).status_code == 404
    response = await client.get(f"/api/v1/leagues/{lid}/standings", auth=alice)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["rounds"]) == 2
    assert data["rounds"][0]["id"] == data["current_round_id"]
    assert [(x["user_id"], x["score"], x["position"]) for x in data["general"]] == [
        (a, "17", 1),
        (b, "10", 2),
        (e, "0", 3),
    ]
    assert [(x["score"], x["position"]) for x in data["rounds"][1]["standings"]] == [
        ("10", 1),
        ("10", 1),
        ("0", 3),
    ]
    for round_row in data["rounds"]:
        for contribution in round_row["contributions"]:
            assert ("calculation" in contribution) == (contribution["user_id"] == a)
            if contribution["user_id"] == b:
                assert set(contribution) == {"user_id", "local_day", "score"}
    assert (await client.get(f"/api/v1/leagues/{lid}/standings", auth=outsider)).status_code == 401
    other = (
        await client.post("/api/v1/leagues", auth=bob, json={"name": "other", "timezone": "UTC"})
    ).json()["id"]
    assert (await client.get(f"/api/v1/leagues/{other}/standings", auth=alice)).status_code == 404


async def test_initial_scoring_upgrade_preserves_legacy_round_and_score(integration_url):
    from pathlib import Path
    from uuid import uuid4

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(integration_url)
    schema = "legacy_league_" + uuid4().hex
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await conn.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))

            def migrate(connection, target):
                config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
                config.attributes["connection"] = connection
                command.upgrade(config, target)

            await conn.run_sync(migrate, "20261117_01")
            user = await conn.scalar(sa.text("INSERT INTO users DEFAULT VALUES RETURNING id"))
            lid = await conn.scalar(
                sa.text("INSERT INTO league (name,created_by) VALUES ('legacy',:uid) RETURNING id"),
                {"uid": user},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO league_member (user_id,league_id,joined_date) "
                    "VALUES (:uid,:lid,'2020-01-01')"
                ),
                {"uid": user, "lid": lid},
            )
            rid = await conn.scalar(
                sa.text(
                    "INSERT INTO league_round (league_id,start_date,end_date) "
                    "VALUES (:lid,'2020-01-06','2020-01-12') RETURNING id"
                ),
                {"lid": lid},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO league_score (league_id,user_id,round_id,score) "
                    "VALUES (:lid,:uid,:rid,42)"
                ),
                {"lid": lid, "uid": user, "rid": rid},
            )
            await conn.run_sync(migrate, "20261117_05")
            preserved = (
                await conn.execute(
                    sa.text(
                        "SELECT r.start_date,r.end_date,s.score,m.joined_date,m.joined_at, "
                        "m.role,m.last_seen_result_id FROM league_round r "
                        "JOIN league_score s ON s.round_id=r.id "
                        "JOIN league_member m ON m.league_id=r.league_id WHERE r.id=:rid"
                    ),
                    {"rid": rid},
                )
            ).one()
            assert tuple(map(str, preserved[:4])) == (
                "2020-01-06",
                "2020-01-12",
                "42",
                "2020-01-01",
            )
            assert preserved[4:] == (None, None, None)
            await conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await engine.dispose()
