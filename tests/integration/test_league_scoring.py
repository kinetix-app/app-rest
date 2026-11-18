"""Real PostgreSQL scoring snapshots and daily winner rules."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa

from app.features.accounts.models import Profile
from app.features.leagues.models import league, league_member, league_score
from app.features.leagues.scoring import credit_completed_session
from app.features.training.models import exercise, exercise_set, session_exercise, training_session
from tests.integration.test_league_membership import league_api  # noqa: F401, F811

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_completion_hook_and_retry_snapshot(league_api):  # noqa: F811
    client, sessions = league_api
    auth = httpx.BasicAuth("alice", "password")
    user = (await client.get("/api/v1/me", auth=auth)).json()["id"]
    created = (
        await client.post("/api/v1/leagues", json={"name": "L", "timezone": "UTC"}, auth=auth)
    ).json()
    async with sessions.begin() as session:
        await session.execute(
            sa.update(Profile).where(Profile.user_id == user).values(weight_kg=80)
        )
        exercise_id = await session.scalar(
            exercise.insert()
            .values(user_id=user, name="gym", activity_type="gym")
            .returning(exercise.c.id)
        )
        # Source begins after incorporation, within its current calendar round.
        await session.execute(
            league_member.update()
            .where(league_member.c.league_id == created["id"])
            .values(joined_at=datetime.now(UTC) - timedelta(hours=2))
        )
    now = datetime.now(UTC)
    payload = {
        "client_session_id": str(uuid4()),
        "started_at": (now - timedelta(hours=1)).isoformat(),
        "ended_at": now.isoformat(),
        "exercises": [{"exercise_id": exercise_id, "sets": [{"reps": 10, "weight_kg": "80"}]}],
    }
    response = await client.post("/api/v1/sessions", json=payload, auth=auth)
    assert response.status_code == 201, response.text
    source = response.json()["id"]
    async with sessions.begin() as session:
        snap = (
            (
                await session.execute(
                    sa.select(training_session).where(training_session.c.id == source)
                )
            )
            .mappings()
            .one()
        )
        assert (
            snap.league_score == 10
            and snap.league_volume_kg_reps == 800
            and snap.league_body_weight_kg == 80
        )
        await session.execute(
            sa.update(Profile).where(Profile.user_id == user).values(weight_kg=40)
        )
    assert (await client.post("/api/v1/sessions", json=payload, auth=auth)).status_code in (
        200,
        201,
    )
    async with sessions() as session:
        snap = (
            (
                await session.execute(
                    sa.select(training_session).where(training_session.c.id == source)
                )
            )
            .mappings()
            .one()
        )
        assert snap.league_score == 10 and snap.league_body_weight_kg == 80
        assert await session.scalar(sa.select(sa.func.count()).select_from(league_score)) == 1


async def test_replacement_cutoffs_and_concurrency(league_api):  # noqa: F811
    client, sessions = league_api
    auth = httpx.BasicAuth("alice", "password")
    user = (await client.get("/api/v1/me", auth=auth)).json()["id"]
    start = datetime(2026, 11, 17, 10, tzinfo=UTC)
    now = start + timedelta(hours=4)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(Profile).where(Profile.user_id == user).values(weight_kg=80)
        )
        lid = await session.scalar(
            league.insert()
            .values(name="test", timezone="UTC", created_by=user)
            .returning(league.c.id)
        )
        await session.execute(
            league_member.insert().values(
                league_id=lid, user_id=user, role="admin", joined_at=start - timedelta(seconds=1)
            )
        )
        gym = await session.scalar(
            exercise.insert()
            .values(user_id=user, name="gym", activity_type="gym")
            .returning(exercise.c.id)
        )

        async def source(at, reps, end=None):
            sid = await session.scalar(
                training_session.insert()
                .values(
                    user_id=user,
                    activity_type="gym",
                    started_at=at,
                    ended_at=end or at + timedelta(hours=1),
                )
                .returning(training_session.c.id)
            )
            eid = await session.scalar(
                session_exercise.insert()
                .values(session_id=sid, exercise_id=gym, exercise_order=1)
                .returning(session_exercise.c.id)
            )
            await session.execute(
                exercise_set.insert().values(
                    session_exercise_id=eid, set_number=1, reps=reps, weight_kg=80, completed=True
                )
            )
            await session.execute(
                exercise_set.insert().values(
                    session_exercise_id=eid, set_number=2, reps=999, weight_kg=80, completed=False
                )
            )
            return sid

        low = await source(start, 10)
        high = await source(start + timedelta(minutes=5), 20)
        tie = await source(start + timedelta(minutes=2), 20)
        tomorrow = await source(start + timedelta(days=1), 5)
        before = await source(start - timedelta(days=1), 100)

    async def credit(sid, instant=now):
        async with sessions.begin() as session:
            await credit_completed_session(session, user, sid, now=instant)

    await credit(low)
    await asyncio.gather(credit(high), credit(tie))
    await credit(tomorrow, start + timedelta(days=1, hours=4))
    await credit(before)
    async with sessions() as session:
        winners = (
            (
                await session.execute(
                    sa.select(league_score)
                    .where(league_score.c.league_id == lid)
                    .order_by(league_score.c.local_day)
                )
            )
            .mappings()
            .all()
        )
        assert len(winners) == 2
        assert winners[0].session_id == tie and winners[0].score == Decimal(20)
        assert winners[1].session_id == tomorrow and winners[1].score == Decimal(5)
        assert (
            await session.scalar(
                sa.select(training_session.c.league_score).where(training_session.c.id == before)
            )
            == 100
        )
    # Calling the hook again is a no-op, including after weight changes.
    async with sessions.begin() as session:
        await session.execute(
            sa.update(Profile).where(Profile.user_id == user).values(weight_kg=40)
        )
        await credit_completed_session(session, user, low, now=now)
    async with sessions() as session:
        assert (
            await session.scalar(
                sa.select(training_session.c.league_score).where(training_session.c.id == low)
            )
            == 10
        )


async def test_missing_inputs_and_closed_source_are_not_credited(league_api):  # noqa: F811
    client, sessions = league_api
    auth = httpx.BasicAuth("alice", "password")
    user = (await client.get("/api/v1/me", auth=auth)).json()["id"]
    start = datetime(2026, 11, 17, 10, tzinfo=UTC)
    async with sessions.begin() as session:
        lid = await session.scalar(
            league.insert()
            .values(name="test", timezone="UTC", created_by=user)
            .returning(league.c.id)
        )
        await session.execute(
            league_member.insert().values(
                league_id=lid, user_id=user, role="admin", joined_at=start - timedelta(days=1)
            )
        )
        gym = await session.scalar(
            exercise.insert()
            .values(user_id=user, name="gym", activity_type="gym")
            .returning(exercise.c.id)
        )
        ids = []
        for _ in range(2):
            sid = await session.scalar(
                training_session.insert()
                .values(
                    user_id=user,
                    activity_type="gym",
                    started_at=start,
                    ended_at=start + timedelta(hours=1),
                )
                .returning(training_session.c.id)
            )
            entry = await session.scalar(
                session_exercise.insert()
                .values(session_id=sid, exercise_id=gym, exercise_order=1)
                .returning(session_exercise.c.id)
            )
            await session.execute(
                exercise_set.insert().values(
                    session_exercise_id=entry, set_number=1, reps=10, weight_kg=80, completed=True
                )
            )
            ids.append(sid)
        await credit_completed_session(session, user, ids[0], now=start + timedelta(hours=2))
        await session.execute(
            sa.update(Profile).where(Profile.user_id == user).values(weight_kg=80)
        )
        await credit_completed_session(session, user, ids[1], now=start + timedelta(days=7))
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(league_score)) == 0
        assert (
            await session.scalar(
                sa.select(training_session.c.league_score).where(training_session.c.id == ids[0])
            )
            is None
        )
        assert (
            await session.scalar(
                sa.select(training_session.c.league_score).where(training_session.c.id == ids[1])
            )
            == 10
        )


async def test_same_routine_sources_use_each_leagues_local_start_day(league_api):  # noqa: F811
    from app.features.training.models import routine

    client, sessions = league_api
    auth = httpx.BasicAuth("alice", "password")
    user = (await client.get("/api/v1/me", auth=auth)).json()["id"]
    first = datetime(2026, 11, 17, 0, 30, tzinfo=UTC)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(Profile).where(Profile.user_id == user).values(weight_kg=80)
        )
        ids = []
        for zone in ("UTC", "America/Los_Angeles"):
            lid = await session.scalar(
                league.insert()
                .values(name=zone, timezone=zone, created_by=user)
                .returning(league.c.id)
            )
            await session.execute(
                league_member.insert().values(
                    league_id=lid, user_id=user, role="admin", joined_at=first - timedelta(days=1)
                )
            )
            ids.append(lid)
        rid = await session.scalar(
            routine.insert().values(user_id=user, name="Same template").returning(routine.c.id)
        )
        eid = await session.scalar(
            exercise.insert()
            .values(user_id=user, name="Gym", activity_type="gym")
            .returning(exercise.c.id)
        )
        for started, reps in ((first, 10), (first + timedelta(hours=23), 20)):
            ended = started + timedelta(hours=1)
            sid = await session.scalar(
                training_session.insert()
                .values(
                    user_id=user,
                    routine_id=rid,
                    activity_type="gym",
                    started_at=started,
                    ended_at=ended,
                )
                .returning(training_session.c.id)
            )
            occurrence = await session.scalar(
                session_exercise.insert()
                .values(session_id=sid, exercise_id=eid, exercise_order=1)
                .returning(session_exercise.c.id)
            )
            await session.execute(
                exercise_set.insert().values(
                    session_exercise_id=occurrence,
                    set_number=1,
                    reps=reps,
                    weight_kg=80,
                    completed=True,
                )
            )
            await credit_completed_session(session, user, sid, now=ended + timedelta(seconds=1))
    async with sessions() as session:
        rows = (
            (
                await session.execute(
                    sa.select(league_score).order_by(
                        league_score.c.league_id, league_score.c.local_day
                    )
                )
            )
            .mappings()
            .all()
        )
        utc = [row for row in rows if row.league_id == ids[0]]
        la = [row for row in rows if row.league_id == ids[1]]
        assert [(str(row.local_day), int(row.score)) for row in utc] == [("2026-11-17", 20)]
        assert [(str(row.local_day), int(row.score)) for row in la] == [
            ("2026-11-16", 10),
            ("2026-11-17", 20),
        ]
