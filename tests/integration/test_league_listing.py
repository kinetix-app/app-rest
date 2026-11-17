"""Weekly card ranks agree with standings without materializing rounds or N+1 reads."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa

from app.features.leagues import standings
from app.features.leagues.listing import list_leagues
from app.features.leagues.models import league, league_member
from app.features.leagues.scoring_models import league_scoring_round
from tests.integration.test_league_membership import league_api  # noqa: F401
from tests.integration.test_league_standings import seed_score

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def provision(client):
    auths = [httpx.BasicAuth(name, "password") for name in ("alice", "bob", "eve")]
    ids = [(await client.get("/api/v1/me", auth=auth)).json()["id"] for auth in auths]
    return auths, ids


async def create_league(client, sessions, auth, owner, peers, name, timezone, creation):
    response = await client.post(
        "/api/v1/leagues", auth=auth, json={"name": name, "timezone": timezone}
    )
    lid = response.json()["id"]
    async with sessions.begin() as session:
        await session.execute(league.update().where(league.c.id == lid).values(created_at=creation))
        await session.execute(
            league_member.update()
            .where(league_member.c.league_id == lid, league_member.c.user_id == owner)
            .values(joined_at=creation)
        )
        if peers:
            await session.execute(
                league_member.insert(),
                [
                    {"league_id": lid, "user_id": uid, "role": "member", "joined_at": creation}
                    for uid in peers
                ],
            )
    return lid


async def test_batched_card_rank_counts_match_current_standings(league_api, monkeypatch):  # noqa: F811
    client, sessions = league_api
    (alice, bob, eve), (a, b, e) = await provision(client)
    now = datetime(2026, 11, 17, 12, tzinfo=UTC)
    creation = now - timedelta(days=21)
    first = await create_league(client, sessions, alice, a, [b, e], "ranked", "UTC", creation)
    second = await create_league(client, sessions, alice, a, [b], "another", "UTC", creation)
    empty = await create_league(
        client, sessions, alice, a, [], "zero", "UTC", now - timedelta(hours=1)
    )
    private = await create_league(client, sessions, bob, b, [], "not Alice's", "UTC", creation)
    async with sessions.begin() as session:
        await seed_score(session, first, a, now - timedelta(hours=2), 20)
        await seed_score(session, first, b, now - timedelta(hours=2), 20)
        await seed_score(session, first, e, now - timedelta(hours=2), 50)
        await seed_score(session, first, a, now - timedelta(days=7), 999999)
        await seed_score(session, second, b, now - timedelta(hours=2), 5)
        rounds_before = await session.scalar(
            sa.select(sa.func.count()).select_from(league_scoring_round)
        )
    queries = []
    engine = sessions.kw["bind"].sync_engine

    def record_query(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    sa.event.listen(engine, "before_cursor_execute", record_query)
    try:
        async with sessions() as session:
            listed = await list_leagues(session, a, now=now)
    finally:
        sa.event.remove(engine, "before_cursor_execute", record_query)
    assert len(queries) == 2
    cards = {item.id: item for item in listed}
    assert set(cards) == {first, second, empty} and private not in cards
    assert (cards[first].member_count, cards[first].current_week_position) == (3, 2)
    assert (cards[second].member_count, cards[second].current_week_position) == (2, 2)
    assert (cards[empty].member_count, cards[empty].current_week_position) == (1, 1)
    async with sessions() as session:
        assert (
            await session.scalar(sa.select(sa.func.count()).select_from(league_scoring_round))
            == rounds_before
        )
        assert (
            await session.scalar(
                sa.select(league_scoring_round.c.id).where(
                    league_scoring_round.c.league_id == empty
                )
            )
            is None
        )
        bob_cards = {item.id: item for item in await list_leagues(session, b, now=now)}
        assert bob_cards[first].current_week_position == 2

    class Clock:
        @staticmethod
        def now(zone):
            return now

    monkeypatch.setattr(standings, "datetime", Clock)
    for lid, card in cards.items():
        async with sessions() as session:
            detail = await standings.get_standings(session, a, lid)
        current = next(
            item for item in detail["rounds"] if item["id"] == detail["current_round_id"]
        )
        assert (
            next(row["position"] for row in current["standings"] if row["user_id"] == a)
            == card.current_week_position
        )
    # Public contract uses the dedicated list schema; detail/create remain unchanged.
    response = await client.get("/api/v1/leagues", auth=alice)
    assert response.status_code == 200
    assert all(
        "member_count" in item and "current_week_position" in item for item in response.json()
    )
    assert "member_count" not in (await client.get(f"/api/v1/leagues/{first}", auth=alice)).json()
    assert (await client.get("/api/v1/leagues")).status_code == 401
    assert len((await client.get("/api/v1/leagues", auth=eve)).json()) == 1


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 11, 22, 23, 30, tzinfo=UTC),
        datetime(2026, 10, 25, 23, 30, tzinfo=UTC),  # Madrid's DST transition week.
    ],
)
async def test_current_week_follows_each_leagues_timezone_and_rollover(league_api, now):  # noqa: F811
    client, sessions = league_api
    (alice, _, _), (a, b, _) = await provision(client)
    # Madrid Monday, Los Angeles Sunday; neither depends on the viewer’s timezone.
    creation = now - timedelta(days=14)
    madrid = await create_league(
        client, sessions, alice, a, [b], "Madrid", "Europe/Madrid", creation
    )
    la = await create_league(client, sessions, alice, a, [b], "LA", "America/Los_Angeles", creation)
    async with sessions.begin() as session:
        for lid in (madrid, la):
            await seed_score(session, lid, b, now - timedelta(hours=2), 9007199254740993)
    async with sessions() as session:
        cards = {item.id: item for item in await list_leagues(session, a, now=now)}
        assert cards[madrid].current_week_position == 1
        assert cards[la].current_week_position == 2
        next_week = now + timedelta(hours=9)
        cards = {item.id: item for item in await list_leagues(session, a, now=next_week)}
        assert cards[madrid].current_week_position == cards[la].current_week_position == 1


async def test_legacy_calendar_or_unknown_incorporation_has_no_rank_but_counts_members(league_api):  # noqa: F811
    client, sessions = league_api
    (alice, _, _), (a, b, e) = await provision(client)
    now = datetime(2026, 11, 17, 12, tzinfo=UTC)
    creation = now - timedelta(days=14)
    legacy = await create_league(client, sessions, alice, a, [b], "legacy", "UTC", creation)
    unknown = await create_league(client, sessions, alice, a, [b], "unknown", "UTC", creation)
    valid = await create_league(client, sessions, alice, a, [b, e], "valid", "UTC", creation)
    async with sessions.begin() as session:
        await session.execute(league.update().where(league.c.id == legacy).values(timezone=None))
        await session.execute(
            league_member.update()
            .where(league_member.c.league_id == unknown, league_member.c.user_id == a)
            .values(joined_at=None)
        )
        await session.execute(
            league_member.update()
            .where(league_member.c.league_id == valid, league_member.c.user_id == b)
            .values(joined_at=None)
        )
        await seed_score(session, valid, b, now - timedelta(hours=2), 100)
    async with sessions() as session:
        cards = {item.id: item for item in await list_leagues(session, a, now=now)}
    assert cards[legacy].member_count == cards[unknown].member_count == 2
    assert cards[legacy].current_week_position is cards[unknown].current_week_position is None
    assert cards[valid].member_count == 3 and cards[valid].current_week_position == 1
