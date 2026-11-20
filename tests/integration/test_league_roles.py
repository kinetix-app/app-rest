"""Admin role changes preserve league ownership and scoring provenance."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tests.integration.test_league_membership import league_api  # noqa: F401
from tests.integration.test_league_standings import seed_score

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_role_changes_preserve_creator_join_date_and_score_history(league_api):  # noqa: F811
    client, sessions = league_api
    alice, bob, eve = (httpx.BasicAuth(name, "password") for name in ("alice", "bob", "eve"))
    a, b, e = [
        (await client.get("/api/v1/me", auth=auth)).json()["id"] for auth in (alice, bob, eve)
    ]
    lid = (
        await client.post("/api/v1/leagues", auth=alice, json={"name": "Roles", "timezone": "UTC"})
    ).json()["id"]
    path = f"/api/v1/leagues/{lid}"
    token = (await client.post(path + "/invitations", auth=alice)).json()["token"]

    async def change(auth, member, role):
        return await client.patch(f"{path}/members/{member}/role", auth=auth, json={"role": role})

    def member(detail, member_id):
        return next(item for item in detail["members"] if item["user_id"] == member_id)

    assert (await change(eve, a, "member")).status_code == 404
    assert (await change(alice, e, "admin")).status_code == 404
    assert (await change(alice, a, "member")).status_code == 403
    joined = (await client.post(f"/api/v1/league-invitations/{token}/accept", auth=bob)).json()
    assert joined["creator_id"] == a
    original_joined = member(joined, b)["joined_at"]
    assert (await change(bob, a, "member")).status_code == 403
    async with sessions.begin() as session:
        await seed_score(session, lid, b, datetime.now(UTC) - timedelta(minutes=1), 10)
    history_url = f"{path}/members/{b}/score-history"
    history = (await client.get(history_url, auth=bob)).json()
    assert len(history["items"]) == 1

    promoted = await change(alice, b, "admin")
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["creator_id"] == a
    assert member(promoted.json(), b)["role"] == "admin"
    assert member(promoted.json(), b)["joined_at"] == original_joined
    assert (await change(bob, b, "member")).status_code == 403
    assert (await change(bob, a, "member")).status_code == 403
    assert (await change(bob, e, "admin")).status_code == 404
    assert (await change(alice, b, "owner")).status_code == 422

    assert (
        await client.post(f"/api/v1/league-invitations/{token}/accept", auth=eve)
    ).status_code == 200
    delegated = await change(bob, e, "admin")
    assert delegated.status_code == 200
    assert member(delegated.json(), e)["role"] == "admin"
    demoted = await change(eve, b, "member")
    assert demoted.status_code == 200
    assert member(demoted.json(), b)["role"] == "member"
    assert member(demoted.json(), b)["joined_at"] == original_joined
    assert member(demoted.json(), a)["role"] == "admin"
    assert (await change(bob, e, "member")).status_code == 403
    assert (await client.get(history_url, auth=bob)).json() == history
