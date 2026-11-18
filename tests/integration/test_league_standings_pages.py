"""Bounded standings and score history exercised through the private league API."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.features.leagues.calculation import weekly_bounds
from app.features.leagues.models import league, league_member
from app.features.leagues.scoring import ensure_round
from tests.integration.test_league_membership import league_api  # noqa: F401
from tests.integration.test_league_standings import seed_score

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_ranked_pages_and_member_history_keep_round_and_privacy(league_api):  # noqa: F811
    client, sessions = league_api
    alice, bob, eve = (httpx.BasicAuth(name, "password") for name in ("alice", "bob", "eve"))
    a, b, e = [
        (await client.get("/api/v1/me", auth=auth)).json()["id"] for auth in (alice, bob, eve)
    ]

    async def create(auth):
        response = await client.post(
            "/api/v1/leagues", auth=auth, json={"name": "Paged league", "timezone": "UTC"}
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    lid = await create(alice)
    other_lid = await create(eve)
    joined_at = datetime.now(UTC)
    round_start, _ = weekly_bounds(joined_at, "UTC")
    old_score = 9_007_199_254_740_993
    async with sessions.begin() as session:
        inception = round_start - timedelta(days=7)
        await session.execute(
            league.update().where(league.c.id == lid).values(created_at=inception)
        )
        await session.execute(
            league_member.update()
            .where(league_member.c.league_id == lid)
            .values(joined_at=inception)
        )
        await session.execute(
            league_member.insert().values(
                league_id=lid, user_id=b, role="member", joined_at=inception
            )
        )
        prior = await seed_score(session, lid, a, round_start - timedelta(days=1), old_score)
        await seed_score(session, lid, a, round_start, 7)
        await seed_score(session, lid, b, round_start, 7)

    path = f"/api/v1/leagues/{lid}"
    catalog_res = await client.get(path + "/standings/rounds", auth=alice)
    assert catalog_res.status_code == 200, catalog_res.text
    catalog = catalog_res.json()
    assert catalog["timezone"] == "UTC"
    assert [item["id"] for item in catalog["rounds"]] == [
        catalog["current_round_id"],
        prior.id,
    ]
    assert set(catalog["rounds"][0]) == {"id", "start_at", "end_at"}
    assert (await client.get(path + "/standings/rounds", auth=eve)).status_code == 404

    async def get_page(**params):
        response = await client.get(path + "/standings/page", params=params, auth=alice)
        assert response.status_code == 200, response.text
        return response.json()

    first = await get_page(round_id=catalog["current_round_id"], limit=1)
    assert first["next_offset"] == 1
    assert [(item["user_id"], item["position"], item["score"]) for item in first["items"]] == [
        (a, 1, "7")
    ]
    second = await get_page(
        round_id=catalog["current_round_id"], limit=1, offset=first["next_offset"]
    )
    assert second["next_offset"] is None
    assert [(item["user_id"], item["position"], item["score"]) for item in second["items"]] == [
        (b, 1, "7")
    ]
    historical = (await get_page(round_id=prior.id))["items"]
    assert [(item["score"], item["position"]) for item in historical] == [
        (str(old_score), 1),
        ("0", 2),
    ]
    general = (await get_page())["items"]
    assert [(item["score"], item["position"]) for item in general] == [
        (str(old_score + 7), 1),
        ("7", 2),
    ]
    other_catalog = (
        await client.get(f"/api/v1/leagues/{other_lid}/standings/rounds", auth=eve)
    ).json()
    assert (
        await client.get(
            path + "/standings/page",
            params={"round_id": other_catalog["current_round_id"]},
            auth=alice,
        )
    ).status_code == 404
    assert (
        await client.get(path + "/standings/page", params={"round_id": 0}, auth=alice)
    ).status_code == 422
    assert (
        await client.get(path + "/standings/page", params={"limit": 51}, auth=alice)
    ).status_code == 422

    history_path = path + f"/members/{a}/score-history"
    history_res = await client.get(history_path, params={"limit": 1}, auth=bob)
    assert history_res.status_code == 200, history_res.text
    latest = history_res.json()
    item = latest["items"][0]
    assert item["score"] == "7" and item["round_id"] == catalog["current_round_id"]
    assert item["session_id"] > 0 and item["ended_at"]
    assert "calculation" not in item
    assert latest["next_before"] == item["local_day"]
    older = (
        await client.get(
            history_path, params={"before": latest["next_before"], "limit": 1}, auth=bob
        )
    ).json()
    assert older["next_before"] is None
    assert len(older["items"]) == 1
    assert older["items"][0]["session_id"] != item["session_id"]
    assert older["items"][0]["round_id"] == prior.id
    assert older["items"][0]["score"] == str(old_score)
    own = (await client.get(history_path, auth=alice)).json()
    assert own["items"][0]["calculation"]["session_id"] == item["session_id"]
    assert "body_weight_kg" in own["items"][0]["calculation"]
    assert (await client.get(history_path, auth=eve)).status_code == 404
    assert (await client.get(path + f"/members/{e}/score-history", auth=alice)).status_code == 404
    assert (await client.get(history_path)).status_code == 401
    assert (
        await client.get(history_path, params={"before": "invalid"}, auth=bob)
    ).status_code == 422


async def test_contributions_reuse_round_and_hide_peer_calculation(league_api):  # noqa: F811
    client, sessions = league_api
    alice, bob, eve = (httpx.BasicAuth(name, "password") for name in ("alice", "bob", "eve"))
    a = (await client.get("/api/v1/me", auth=alice)).json()["id"]
    b = (await client.get("/api/v1/me", auth=bob)).json()["id"]
    lid = (
        await client.post("/api/v1/leagues", auth=alice, json={"name": "Scopes", "timezone": "UTC"})
    ).json()["id"]
    token = (await client.post(f"/api/v1/leagues/{lid}/invitations", auth=alice)).json()["token"]
    assert (
        await client.post(f"/api/v1/league-invitations/{token}/accept", auth=bob)
    ).status_code == 200
    current, _ = weekly_bounds(datetime.now(UTC), "UTC")
    async with sessions.begin() as session:
        inception = current - timedelta(days=7)
        await session.execute(
            league.update().where(league.c.id == lid).values(created_at=inception)
        )
        await session.execute(
            league_member.update()
            .where(league_member.c.league_id == lid)
            .values(joined_at=inception)
        )
        prior = await seed_score(session, lid, a, current - timedelta(days=1), 100)
        await seed_score(session, lid, a, current, 7)
        await seed_score(session, lid, b, current, 5)

    async with sessions.begin() as session:
        row = (await session.execute(league.select().where(league.c.id == lid))).mappings().one()
        empty_round = await ensure_round(session, row, current + timedelta(days=7))

    endpoint = f"/api/v1/leagues/{lid}/standings/contributions"
    catalog = (await client.get(f"/api/v1/leagues/{lid}/standings/rounds", auth=bob)).json()
    current_params = {"round_id": catalog["current_round_id"], "limit": 1}
    page = await client.get(endpoint, auth=bob, params=current_params)
    assert page.status_code == 200, page.text
    current_first = page.json()
    assert current_first["next_offset"] == 1
    alice_score = current_first["items"][0]
    assert (alice_score["user_id"], alice_score["score"]) == (a, "7")
    assert alice_score["session_id"] > 0 and alice_score["ended_at"]
    assert "calculation" not in alice_score
    current_second = (
        await client.get(
            endpoint, auth=bob, params=current_params | {"offset": current_first["next_offset"]}
        )
    ).json()
    assert current_second["next_offset"] is None
    bob_score = current_second["items"][0]
    assert (bob_score["user_id"], bob_score["score"]) == (b, "5")
    assert bob_score["calculation"]["session_id"] == bob_score["session_id"]
    assert "body_weight_kg" in bob_score["calculation"]

    past = (await client.get(endpoint, auth=bob, params={"round_id": prior.id})).json()
    assert [(item["round_id"], item["score"]) for item in past["items"]] == [(prior.id, "100")]
    general = (await client.get(endpoint, auth=bob)).json()
    assert general["items"] == [alice_score, bob_score, past["items"][0]]
    empty = await client.get(endpoint, auth=bob, params={"round_id": empty_round.id})
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "next_offset": None}
    other = (
        await client.post("/api/v1/leagues", auth=eve, json={"name": "Other", "timezone": "UTC"})
    ).json()
    other_round = (
        await client.get(f"/api/v1/leagues/{other['id']}/standings/rounds", auth=eve)
    ).json()["current_round_id"]
    assert (
        await client.get(endpoint, auth=bob, params={"round_id": other_round})
    ).status_code == 404
    assert (await client.get(endpoint, auth=bob, params={"scope": "general"})).status_code == 422
    assert (await client.get(endpoint, auth=eve)).status_code == 404
    assert (await client.get(endpoint)).status_code == 401
    assert (await client.get(endpoint, auth=bob, params={"round_id": 99999999})).status_code == 404
    assert (await client.get(endpoint, auth=bob, params={"limit": 51})).status_code == 422
