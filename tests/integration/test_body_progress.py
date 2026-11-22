import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update

from app.features.accounts.models import User
from app.features.goals import measurement_records, progress
from app.features.goals.models import physical_goal
from tests.integration.test_league_membership import league_api  # noqa: F401, F811

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

MEASUREMENTS = "/api/v1/me/body-measurements"
TARGET = "/api/v1/me/physical-target"
PROFILE = "/api/v1/me/profile"
ACCOUNT = "/api/v1/auth/me"
OBJECTIVE = "/api/v1/me/objective"
ALICE = httpx.BasicAuth("alice", "password")
BOB = httpx.BasicAuth("bob", "password")


def check_in(date="2020-06-12", **metrics):
    return {"request_id": str(uuid4()), "date": date, **metrics}


async def test_history_order_partial_records_profile_sync_and_isolation(league_api):  # noqa: F811
    client, sessions = league_api
    assert (await client.get(MEASUREMENTS)).status_code == 401
    assert (await client.post(MEASUREMENTS, json=check_in(weight_kg="80"))).status_code == 401
    alice = (await client.get(ACCOUNT, auth=ALICE)).json()["id"]
    assert (await client.get(MEASUREMENTS, auth=ALICE)).json() == {"items": []}

    later = check_in(
        height_cm="180.25",
        weight_kg="1000",
        body_fat_percentage="0",
        muscle_mass_kg="30.123456",
        waist_cm="77.12",
        chest_cm="95.25",
        arm_cm="29.10",
        thigh_cm="46.22",
    )
    # Matching concurrent requests return one committed row and one profile update.
    responses = await asyncio.gather(
        client.post(MEASUREMENTS, json=later, auth=ALICE),
        client.post(MEASUREMENTS, json=later, auth=ALICE),
    )
    assert [response.status_code for response in responses] == [201, 201]
    first = responses[0].json()
    assert responses[1].json() == first
    assert first == {
        "id": first["id"],
        "date": "2020-06-12",
        "height_cm": "180.25",
        "weight_kg": "1000.000000",
        "body_fat_percentage": "0.00",
        "muscle_mass_kg": "30.123456",
        "waist_cm": "77.12",
        "chest_cm": "95.25",
        "arm_cm": "29.10",
        "thigh_cm": "46.22",
    }
    collision = await client.post(MEASUREMENTS, json=later | {"weight_kg": "81"}, auth=ALICE)
    assert collision.status_code == 409

    same_day = await client.post(MEASUREMENTS, json=check_in(weight_kg="82.123456"), auth=ALICE)
    backfill = await client.post(
        MEASUREMENTS,
        json=check_in("2020-05-01", weight_kg="80", height_cm="179", waist_cm="76"),
        auth=ALICE,
    )
    assert same_day.status_code == backfill.status_code == 201
    assert same_day.json()["height_cm"] is None
    assert (await client.get(MEASUREMENTS, auth=ALICE)).json()["items"] == [
        backfill.json(),
        first,
        same_day.json(),
    ]
    profile = (await client.get(ACCOUNT, auth=ALICE)).json()["profile"]
    assert profile["weight_kg"] == "82.123456"
    assert profile["height_cm"] == "180.25"
    assert (await client.get(MEASUREMENTS, auth=BOB)).json() == {"items": []}
    assert (await client.get(ACCOUNT, auth=BOB)).json()["profile"]["weight_kg"] is None
    # Request IDs are scoped to the owner.
    assert (await client.post(MEASUREMENTS, json=later, auth=BOB)).status_code == 201
    async with sessions.begin() as session:
        await session.execute(update(User).where(User.id == alice).values(status="blocked"))
    assert (await client.get(MEASUREMENTS, auth=ALICE)).status_code == 403
    assert (await client.get(TARGET, auth=ALICE)).status_code == 403


async def test_local_dates_profile_edits_and_explicit_clear(league_api, monkeypatch):  # noqa: F811
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 4, 29, 11, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(measurement_records, "datetime", FixedClock)
    client, _ = league_api
    for update_fields in (
        {"timezone": "Pacific/Kiritimati", "height_cm": "171.25", "weight_kg": "70.135000"},
        {"weight_kg": "70.135", "measurement_system": "imperial"},
        {"timezone": "Europe/Madrid"},
    ):
        assert (await client.patch(PROFILE, json=update_fields, auth=ALICE)).status_code == 200
    history = (await client.get(MEASUREMENTS, auth=ALICE)).json()["items"]
    assert len(history) == 1
    assert history[0]["date"] == "2026-04-30"
    assert history[0]["height_cm"] == "171.25"
    assert history[0]["weight_kg"] == "70.135000"

    future = check_in("2026-04-30", weight_kg="99")
    assert (await client.post(MEASUREMENTS, json=future, auth=ALICE)).status_code == 422
    # Clearing the editable profile snapshot preserves its dated observations.
    cleared = await client.patch(PROFILE, json={"weight_kg": None}, auth=ALICE)
    assert cleared.json()["profile"]["weight_kg"] is None
    old = check_in("2026-04-29", weight_kg="60")
    assert (await client.post(MEASUREMENTS, json=old, auth=ALICE)).status_code == 201
    assert (await client.get(ACCOUNT, auth=ALICE)).json()["profile"]["weight_kg"] is None
    await client.patch(PROFILE, json={"timezone": "Pacific/Kiritimati"}, auth=ALICE)
    new = await client.patch(PROFILE, json={"weight_kg": "72.5"}, auth=ALICE)
    assert new.json()["profile"]["weight_kg"] == "72.500000"
    items = (await client.get(MEASUREMENTS, auth=ALICE)).json()["items"]
    assert [item["weight_kg"] for item in items] == ["60.000000", "70.135000", "72.500000"]
    assert items[-1]["height_cm"] is None


async def test_validation_and_atomic_failure_retry(league_api, monkeypatch):  # noqa: F811
    client, _ = league_api
    for invalid in (
        {},
        {"date": "2020-02-30", "weight_kg": 80},
        {"date": "2020-01-01T00:00:00Z", "weight_kg": 80},
        {"date": "9999-12-31", "weight_kg": 80},
        {"height_cm": "0"},
        {"height_cm": "300.01"},
        {"weight_kg": "1000.000001"},
        {"weight_kg": "NaN"},
        {"weight_kg": "80", "user_id": 999},
        {"muscle_mass_kg": "1.0000001"},
        {"body_fat_percentage": "100.01"},
        {"arm_cm": "1000"},
    ):
        response = await client.post(MEASUREMENTS, json=check_in() | invalid, auth=ALICE)
        assert response.status_code == 422
    await client.patch(PROFILE, json={"weight_kg": "70"}, auth=ALICE)
    original = progress.append_measurement

    async def fail_after_insert(*args):
        await original(*args)
        raise RuntimeError("test failure after insert")

    payload = check_in("2020-06-12", weight_kg="82")
    with monkeypatch.context() as patch:
        patch.setattr(progress, "append_measurement", fail_after_insert)
        with pytest.raises(RuntimeError, match="test failure after insert"):
            await client.post(MEASUREMENTS, json=payload, auth=ALICE)
    assert len((await client.get(MEASUREMENTS, auth=ALICE)).json()["items"]) == 1
    assert (await client.get(ACCOUNT, auth=ALICE)).json()["profile"]["weight_kg"] == "70.000000"
    assert (await client.post(MEASUREMENTS, json=payload, auth=ALICE)).status_code == 201
    assert len((await client.get(MEASUREMENTS, auth=ALICE)).json()["items"]) == 2


async def test_weight_targets_are_owned_and_scoped_to_selected_objective(league_api):  # noqa: F811
    client, sessions = league_api
    assert (await client.get(TARGET)).status_code == 401
    assert (await client.get(TARGET, auth=ALICE)).json() == {"objective": None, "target": None}
    alice = (await client.get(ACCOUNT, auth=ALICE)).json()["id"]
    async with sessions.begin() as session:
        await session.execute(
            physical_goal.insert().values(user_id=alice, goal_type="gain_weight", target_value=5)
        )

    payload = {"objective": "gain_weight", "weight_kg": "83.413256", "target_date": "2027-01-02"}
    assert (await client.put(TARGET, json=payload, auth=ALICE)).status_code == 409
    assert (await client.put(OBJECTIVE, json={"objective": "gain_weight"}, auth=ALICE)).is_success
    assert (await client.get(TARGET, auth=ALICE)).json() == {
        "objective": "gain_weight",
        "target": None,
    }
    created = await client.put(TARGET, json=payload, auth=ALICE)
    assert created.json() == {
        "objective": "gain_weight",
        "target": {"weight_kg": "83.413256", "target_date": "2027-01-02"},
    }
    changed = await client.put(
        TARGET, json=payload | {"target_date": None, "weight_kg": "84"}, auth=ALICE
    )
    assert changed.json()["target"] == {"weight_kg": "84.000000", "target_date": None}
    assert (await client.put(OBJECTIVE, json={"objective": "gain_weight"}, auth=BOB)).is_success
    assert (await client.get(TARGET, auth=BOB)).json()["target"] is None

    assert (
        await client.put(OBJECTIVE, json={"objective": "maintain_weight"}, auth=ALICE)
    ).is_success
    assert (await client.get(TARGET, auth=ALICE)).json()["target"] is None
    assert (await client.put(TARGET, json=payload, auth=ALICE)).status_code == 409
    assert (
        await client.put(TARGET, json=payload | {"objective": "maintain_weight"}, auth=ALICE)
    ).is_success
    assert (await client.put(OBJECTIVE, json={"objective": "gain_weight"}, auth=ALICE)).is_success
    assert (await client.get(TARGET, auth=ALICE)).json() == changed.json()
    async with sessions() as session:
        rows = (await session.execute(select(physical_goal.c.target_metric))).scalars().all()
        assert rows.count("weight_kg") == 2
        assert rows.count(None) == 1
