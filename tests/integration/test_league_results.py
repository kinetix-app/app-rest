"""Stable closure and membership-scoped result acknowledgement."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa

from app.features.leagues.calculation import weekly_bounds
from app.features.leagues.models import league, league_member
from app.features.leagues.result_models import league_result
from app.features.leagues.results import pending_results
from app.features.leagues.scoring_models import league_daily_score
from app.features.posts.models import post
from tests.integration.test_league_membership import league_api  # noqa: F401
from tests.integration.test_league_standings import seed_score

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_results_snapshot_acknowledgements_and_access(league_api):  # noqa: F811
    client, sessions = league_api
    alice, bob, eve = (httpx.BasicAuth(name, "password") for name in ("alice", "bob", "eve"))
    a, b, e = [
        (await client.get("/api/v1/me", auth=auth)).json()["id"] for auth in (alice, bob, eve)
    ]
    lid = (
        await client.post("/api/v1/leagues", auth=alice, json={"name": "test", "timezone": "UTC"})
    ).json()["id"]
    current, _ = weekly_bounds(datetime.now(UTC), "UTC")
    creation = current - timedelta(days=14)
    async with sessions.begin() as session:
        await session.execute(league.update().where(league.c.id == lid).values(created_at=creation))
        await session.execute(
            league_member.update()
            .where(league_member.c.league_id == lid)
            .values(joined_at=creation)
        )
        await session.execute(
            league_member.insert(),
            [
                {"league_id": lid, "user_id": b, "role": "member", "joined_at": creation},
                {"league_id": lid, "user_id": e, "role": "member", "joined_at": creation},
            ],
        )
        await seed_score(session, lid, a, creation + timedelta(days=1), 10)
    async with sessions() as session:
        first = await pending_results(session, a, lid, now=current + timedelta(hours=1))
    assert len(first) == 2
    assert first[0]["loser_user_ids"] == [b, e]
    assert first[1]["loser_user_ids"] == [a, b, e]
    assert first[0]["start_at"] < first[1]["start_at"]
    # Reads are nonacknowledging and closure never rewrites an existing snapshot.
    async with sessions.begin() as session:
        await session.execute(
            league_daily_score.update()
            .where(league_daily_score.c.league_id == lid)
            .values(score=99)
        )
    async with sessions() as session:
        assert await pending_results(session, a, lid, now=current + timedelta(hours=1)) == first
        assert await pending_results(session, b, lid, now=current + timedelta(hours=1)) == first
    p = f"/api/v1/leagues/{lid}/results"
    assert (await client.get(f"{p}/pending", auth=alice)).json() == first
    assert (await client.post(f"{p}/{first[1]['id']}/acknowledge", auth=alice)).status_code == 204
    assert (await client.post(f"{p}/{first[0]['id']}/acknowledge", auth=alice)).status_code == 204
    assert (await client.post(f"{p}/{first[1]['id']}/acknowledge", auth=alice)).status_code == 204
    assert (await client.get(f"{p}/pending", auth=alice)).json() == []
    assert (await client.get(f"{p}/pending", auth=bob)).json() == first
    other = (
        await client.post("/api/v1/leagues", auth=bob, json={"name": "other", "timezone": "UTC"})
    ).json()["id"]
    assert (
        await client.get(f"/api/v1/leagues/{other}/results/pending", auth=alice)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/leagues/{other}/results/{first[0]['id']}/acknowledge", auth=bob)
    ).status_code == 404
    async with sessions() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(league_result)
                .where(league_result.c.league_id == lid)
            )
            == 2
        )
        assert await session.scalar(sa.select(sa.func.count()).select_from(post)) == 0
        assert (
            await session.scalar(
                sa.select(league_member.c.last_seen_result_id).where(
                    league_member.c.league_id == lid, league_member.c.user_id == b
                )
            )
            is None
        )


async def test_single_member_has_no_loser_and_late_joiner_sees_eligible_results(league_api):  # noqa: F811
    client, sessions = league_api
    alice, bob = (httpx.BasicAuth(name, "password") for name in ("alice", "bob"))
    a, b = [(await client.get("/api/v1/me", auth=auth)).json()["id"] for auth in (alice, bob)]
    lid = (
        await client.post("/api/v1/leagues", auth=alice, json={"name": "solo", "timezone": "UTC"})
    ).json()["id"]
    current, _ = weekly_bounds(datetime.now(UTC), "UTC")
    creation = current - timedelta(days=14)
    async with sessions.begin() as session:
        await session.execute(league.update().where(league.c.id == lid).values(created_at=creation))
        await session.execute(
            league_member.update()
            .where(league_member.c.league_id == lid)
            .values(joined_at=creation)
        )
        await session.execute(
            league_member.insert().values(
                league_id=lid, user_id=b, role="member", joined_at=current - timedelta(days=6)
            )
        )
    async with sessions() as session:
        alice_results = await pending_results(session, a, lid, now=current + timedelta(hours=1))
    assert alice_results[0]["loser_user_ids"] == []
    assert set(alice_results[1]["loser_user_ids"]) == {a, b}
    async with sessions() as session:
        bob_results = await pending_results(session, b, lid, now=current + timedelta(hours=1))
    assert [item["id"] for item in bob_results] == [alice_results[1]["id"]]
    assert (
        await client.post(
            f"/api/v1/leagues/{lid}/results/{alice_results[0]['id']}/acknowledge", auth=bob
        )
    ).status_code == 404
