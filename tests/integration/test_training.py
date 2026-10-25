"""Training API persistence, catalogue visibility and template/history isolation."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.features.training.models import (
    exercise,
    exercise_set,
    routine,
    routine_exercise,
    routine_exercise_set,
    session_draft,
    session_exercise,
    training_session,
)
from app.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def training_api(integration_url):
    schema = "training_" + uuid4().hex
    admin = create_async_engine(integration_url)
    engine = create_async_engine(
        integration_url, connect_args={"server_settings": {"search_path": schema}}
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with admin.begin() as connection:
            await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))

            def migrate(conn):
                config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
                config.attributes["connection"] = conn
                command.upgrade(config, "head")

            await connection.run_sync(migrate)
        settings = Settings(
            _env_file=None,
            app_env="test",
            auth_mode="basic",
            basic_auth_users={"alice": SecretStr("password"), "bob": SecretStr("password")},
            database_url=SecretStr(integration_url.render_as_string(hide_password=False)),
        )
        app = create_app(settings)
        async with LifespanManager(app):
            app.state.session_factory = sessions
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                alice = httpx.BasicAuth("alice", "password")
                bob = httpx.BasicAuth("bob", "password")
                alice_id = (await client.get("/api/v1/me", auth=alice)).json()["id"]
                bob_id = (await client.get("/api/v1/me", auth=bob)).json()["id"]
                async with sessions.begin() as session:
                    catalogue = []
                    for i in range(8):
                        catalogue.append(
                            await session.scalar(
                                exercise.insert()
                                .values(
                                    name=f"Catalogue {i}",
                                    activity_type="gym",
                                    source="ascend_edb_v2",
                                    external_id=f"exr_{i}",
                                    imported_at=datetime.now(UTC),
                                    target_muscles=["PECTORALIS"] if i % 2 == 0 else ["QUADRICEPS"],
                                    body_parts=["CHEST"] if i % 2 == 0 else ["UPPER ARMS"],
                                    secondary_muscles=["TRICEPS"],
                                    instructions=["Control the movement"],
                                    image_url="https://media.example/image.jpg",
                                    image_urls={"480p": "https://media.example/image.jpg"},
                                    video_url="https://media.example/video.mp4",
                                )
                                .returning(exercise.c.id)
                            )
                        )
                    private = await session.scalar(
                        exercise.insert()
                        .values(
                            name="Bob private",
                            activity_type="gym",
                            user_id=bob_id,
                        )
                        .returning(exercise.c.id)
                    )
                    own = await session.scalar(
                        exercise.insert()
                        .values(
                            name="Alice private",
                            activity_type="gym",
                            user_id=alice_id,
                        )
                        .returning(exercise.c.id)
                    )
                    unowned = await session.scalar(
                        exercise.insert()
                        .values(
                            name="Unpublished manual",
                            activity_type="gym",
                        )
                        .returning(exercise.c.id)
                    )
                    running = await session.scalar(
                        exercise.insert()
                        .values(
                            name="Run",
                            activity_type="running",
                            user_id=alice_id,
                        )
                        .returning(exercise.c.id)
                    )
                yield SimpleNamespace(
                    client=client,
                    sessions=sessions,
                    alice=alice,
                    bob=bob,
                    alice_id=alice_id,
                    bob_id=bob_id,
                    catalogue=catalogue,
                    private=private,
                    own=own,
                    unowned=unowned,
                    running=running,
                )
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def create(api, ids=None):
    response = await api.client.post(
        "/api/v1/routines",
        auth=api.alice,
        json={
            "name": " Upper body ",
            "exercises": [{"exercise_id": value} for value in (ids or api.catalogue[:3])],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_catalogue_filter_pagination_details_and_permissions(training_api):
    api = training_api
    all_rows = await api.client.get("/api/v1/exercises", auth=api.alice)
    assert all_rows.status_code == 200
    assert [row["id"] for row in all_rows.json()["items"]] == [*api.catalogue, api.own]
    for group in ("pectORALis", " PECTORALIS "):
        filtered = await api.client.get(
            "/api/v1/exercises", auth=api.alice, params={"muscle_group": group}
        )
        assert [row["id"] for row in filtered.json()["items"]] == api.catalogue[::2]
    for group in ("TRICEPS", "unknown"):
        filtered = await api.client.get(
            "/api/v1/exercises", auth=api.alice, params={"muscle_group": group}
        )
        assert filtered.json()["items"] == []
    blank = await api.client.get("/api/v1/exercises?muscle_group=", auth=api.alice)
    assert blank.json() == all_rows.json()
    page = await api.client.get("/api/v1/exercises?limit=2&offset=2", auth=api.alice)
    assert [row["id"] for row in page.json()["items"]] == api.catalogue[2:4]
    details = await api.client.get(f"/api/v1/exercises/{api.catalogue[0]}", auth=api.alice)
    assert details.json()["instructions"] == ["Control the movement"]
    assert details.json()["image_urls"]["480p"] == "https://media.example/image.jpg"
    assert "user_id" not in details.json() and "external_id" not in details.json()
    for resource_id in (api.private, api.unowned, api.running, 999999):
        assert (
            await api.client.get(f"/api/v1/exercises/{resource_id}", auth=api.alice)
        ).status_code == 404
    assert (await api.client.get(f"/api/v1/exercises/{api.own}", auth=api.alice)).status_code == 200
    assert (await api.client.get(f"/api/v1/exercises/{api.own}", auth=api.bob)).status_code == 404


async def test_routine_save_reopen_edit_and_account_isolation(training_api):
    api = training_api
    saved = await create(api)
    path = f"/api/v1/routines/{saved['id']}"
    assert saved["name"] == "Upper body"
    assert [slot["exercise"]["id"] for slot in saved["exercises"]] == api.catalogue[:3]
    assert (await api.client.get(path, auth=api.alice)).json() == saved
    assert (await api.client.get("/api/v1/routines", auth=api.alice)).json()["items"] == [
        {"id": saved["id"], "name": "Upper body"}
    ]
    assert (await api.client.get("/api/v1/routines", auth=api.bob)).json()["items"] == []
    assert (await api.client.get(path, auth=api.bob)).status_code == 404
    assert (await api.client.patch(path, auth=api.bob, json={"name": "Stolen"})).status_code == 404
    renamed = await api.client.patch(path, auth=api.alice, json={"name": "Renamed"})
    assert renamed.json()["exercises"] == saved["exercises"]
    first, second, _ = saved["exercises"]
    selection = [
        {"id": second["id"], "exercise_id": second["exercise"]["id"]},
        {"id": first["id"], "exercise_id": first["exercise"]["id"]},
        {"exercise_id": api.catalogue[0]},
    ]
    edited = await api.client.patch(path, auth=api.alice, json={"exercises": selection})
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "Renamed"
    slots = edited.json()["exercises"]
    assert [slot["id"] for slot in slots[:2]] == [second["id"], first["id"]]
    assert [slot["exercise_order"] for slot in slots] == [1, 2, 3]
    assert slots[2]["id"] not in [slot["id"] for slot in saved["exercises"]]
    assert slots[2]["exercise"]["id"] == first["exercise"]["id"]
    assert (await api.client.get(path, auth=api.alice)).json() == edited.json()
    one = await create(api, [api.own])
    assert len(one["exercises"]) == 1
    page = await api.client.get("/api/v1/routines?limit=1&offset=1", auth=api.alice)
    assert page.json()["items"][0]["id"] == one["id"]


async def test_invalid_references_leave_no_partial_writes(training_api, monkeypatch):
    api = training_api
    saved = await create(api)
    path = f"/api/v1/routines/{saved['id']}"
    for resource_id in (api.private, api.unowned, api.running, 999999):
        body = {"name": "Invalid", "exercises": [{"exercise_id": resource_id}]}
        assert (
            await api.client.post("/api/v1/routines", auth=api.alice, json=body)
        ).status_code == 422
        assert (await api.client.patch(path, auth=api.alice, json=body)).status_code == 422
    other = await create(api)
    invalid_slot = {
        "name": "Invalid",
        "exercises": [
            {
                "id": other["exercises"][0]["id"],
                "exercise_id": api.catalogue[0],
            }
        ],
    }
    assert (await api.client.patch(path, auth=api.alice, json=invalid_slot)).status_code == 422
    assert (await api.client.get(path, auth=api.alice)).json() == saved
    # Force a failure after writes; verify rollback using a fresh connection.
    from app.features.training import service
    from app.features.training.schemas import RoutineCreate, RoutinePatch

    async def fail(*args, **kwargs):
        raise RuntimeError("Simulated response failure")

    with monkeypatch.context() as patch:
        patch.setattr(service, "get_routine", fail)
        async with api.sessions() as session:
            with pytest.raises(RuntimeError):
                await service.update_routine(
                    session,
                    api.alice_id,
                    saved["id"],
                    RoutinePatch(
                        name="Rollback",
                        exercises=[{"exercise_id": api.catalogue[7]}],
                    ),
                )
            with pytest.raises(RuntimeError):
                await service.create_routine(
                    session,
                    api.alice_id,
                    RoutineCreate(
                        name="Rollback",
                        exercises=[{"exercise_id": api.catalogue[7]}],
                    ),
                )
    assert (await api.client.get(path, auth=api.alice)).json() == saved
    async with api.sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(routine)) == 2


async def add_workout(api, routine_id, slots, *, user_id=None, ended_at=None, reps=10):
    async with api.sessions.begin() as session:
        session_id = await session.scalar(
            training_session.insert()
            .values(
                user_id=user_id or api.alice_id,
                routine_id=routine_id,
                activity_type="gym",
                started_at=datetime(2026, 10, 20, tzinfo=UTC),
                ended_at=ended_at,
            )
            .returning(training_session.c.id)
        )
        for slot in slots:
            entry_id = await session.scalar(
                session_exercise.insert()
                .values(
                    session_id=session_id,
                    exercise_id=slot["exercise"]["id"],
                    exercise_order=slot["exercise_order"],
                )
                .returning(session_exercise.c.id)
            )
            await session.execute(
                exercise_set.insert().values(
                    session_exercise_id=entry_id,
                    set_number=1,
                    reps=reps,
                    weight_kg="42.50",
                    completed=True,
                )
            )
    return session_id


async def test_latest_results_defaults_reordering_and_history_preservation(training_api):
    api = training_api
    saved = await create(api)
    path = f"/api/v1/routines/{saved['id']}"
    slots = saved["exercises"]
    async with api.sessions.begin() as session:
        await session.execute(
            routine_exercise_set.insert(),
            [
                {
                    "routine_exercise_id": slot["id"],
                    "set_number": 1,
                    "reps": 5,
                    "weight_kg": "20.00",
                }
                for slot in slots
            ],
        )
    now = datetime(2026, 10, 21, 12, tzinfo=UTC)
    await add_workout(api, saved["id"], slots, ended_at=now - timedelta(days=1), reps=8)
    latest_id = await add_workout(api, saved["id"], slots[:2], ended_at=now, reps=12)
    # Active and another account's later session cannot override this account's completed workout.
    await add_workout(api, saved["id"], slots, reps=90)
    await add_workout(
        api, saved["id"], slots, user_id=api.bob_id, ended_at=now + timedelta(hours=1), reps=99
    )
    loaded = (await api.client.get(path, auth=api.alice)).json()["exercises"]
    assert [slot["sets"][0]["reps"] for slot in loaded] == [12, 12, 8]
    assert loaded[0]["default_sets"][0]["weight_kg"] == "20.000000"
    assert loaded[0]["sets"][0]["weight_kg"] == "42.500000"
    assert [slot["sets_source"] for slot in loaded] == [
        "latest_session",
        "latest_session",
        "latest_session",
    ]
    async with api.sessions() as session:
        before_sets = (
            (await session.execute(sa.select(exercise_set).order_by(exercise_set.c.id)))
            .mappings()
            .all()
        )
    changed = await api.client.patch(
        path,
        auth=api.alice,
        json={
            "exercises": [
                {"id": slots[1]["id"], "exercise_id": slots[1]["exercise"]["id"]},
                {"id": slots[2]["id"], "exercise_id": api.catalogue[7]},
            ]
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["exercises"][0]["sets"][0]["reps"] == 12
    assert changed.json()["exercises"][1]["sets"] == []
    async with api.sessions() as session:
        after_sets = (
            (await session.execute(sa.select(exercise_set).order_by(exercise_set.c.id)))
            .mappings()
            .all()
        )
        assert before_sets == after_sets
        historical = (
            (
                await session.execute(
                    sa.select(session_exercise)
                    .where(session_exercise.c.session_id == latest_id)
                    .order_by(session_exercise.c.exercise_order)
                )
            )
            .mappings()
            .all()
        )
        assert "routine_exercise_id" not in historical[0]
        assert historical[0]["exercise_id"] == api.catalogue[0]
        assert "routine_exercise_id" not in historical[1]
        assert (
            await session.scalar(sa.select(sa.func.count()).select_from(routine_exercise_set)) == 1
        )


async def test_concurrent_updates_are_serialized(training_api):
    api = training_api
    saved = await create(api)
    path = f"/api/v1/routines/{saved['id']}"
    results = await asyncio.gather(
        *[
            api.client.patch(path, auth=api.alice, json={"exercises": [{"exercise_id": value}]})
            for value in api.catalogue[3:5]
        ]
    )
    assert [result.status_code for result in results] == [200, 200]
    loaded = (await api.client.get(path, auth=api.alice)).json()
    assert len(loaded["exercises"]) == 1
    assert loaded["exercises"][0]["exercise"]["id"] in api.catalogue[3:5]
    async with api.sessions() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(routine_exercise)
                .where(routine_exercise.c.routine_id == saved["id"])
            )
            == 1
        )


async def test_authentication_and_validation(training_api):
    api = training_api
    saved = await create(api)
    path = f"/api/v1/routines/{saved['id']}"
    requests = [
        ("GET", "/api/v1/routines", None),
        ("GET", path, None),
        (
            "POST",
            "/api/v1/routines",
            {"name": "Test", "exercises": [{"exercise_id": api.catalogue[0]}]},
        ),
        ("PATCH", path, {"name": "Test"}),
        ("GET", "/api/v1/exercises", None),
        ("GET", f"/api/v1/exercises/{api.catalogue[0]}", None),
    ]
    for method, endpoint, payload in requests:
        assert (await api.client.request(method, endpoint, json=payload)).status_code == 401
    for changes in (
        {},
        {"name": None},
        {"name": " "},
        {"name": "x" * 151},
        {"exercises": None},
        {"exercises": []},
        {"user_id": api.bob_id},
        {"exercises": [{"exercise_id": True}]},
        {"exercises": [{"exercise_id": 2**63}]},
        {"exercises": [{"id": 1, "exercise_id": api.catalogue[0]}] * 2},
    ):
        assert (await api.client.patch(path, auth=api.alice, json=changes)).status_code == 422
    for query in ("limit=0", "limit=101", "offset=-1", "offset=9223372036854775808"):
        for endpoint in ("/api/v1/exercises", "/api/v1/routines"):
            assert (await api.client.get(f"{endpoint}?{query}", auth=api.alice)).status_code == 422
    for invalid in ("0", "-1", "abc", "9223372036854775808"):
        assert (
            await api.client.get(f"/api/v1/exercises/{invalid}", auth=api.alice)
        ).status_code == 422
    assert (await api.client.get("/api/v1/routines/999999", auth=api.alice)).status_code == 404
    assert (
        await api.client.patch("/api/v1/routines/999999", auth=api.alice, json={"name": "No"})
    ).status_code == 404


async def test_planned_sets_roundtrip_patch_omission_and_history(training_api):
    api = training_api
    payload = {
        "name": "Planned",
        "exercises": [
            {
                "exercise_id": api.catalogue[0],
                "sets": [
                    {"reps": 8, "weight_kg": "80.00"},
                    {"reps": 10, "weight_kg": "0"},
                ],
            }
        ],
    }
    response = await api.client.post("/api/v1/routines", auth=api.alice, json=payload)
    assert response.status_code == 201, response.text
    saved = response.json()
    slot = saved["exercises"][0]
    assert [row["set_number"] for row in slot["default_sets"]] == [1, 2]
    assert [row["weight_kg"] for row in slot["default_sets"]] == ["80.000000", "0.000000"]
    path = f"/api/v1/routines/{saved['id']}"
    assert (await api.client.get(path, auth=api.alice)).json() == saved
    session_id = await add_workout(
        api, saved["id"], [slot], ended_at=datetime(2026, 10, 21, tzinfo=UTC), reps=12
    )
    selection = {"id": slot["id"], "exercise_id": api.catalogue[0]}
    preserved = await api.client.patch(path, auth=api.alice, json={"exercises": [selection]})
    assert preserved.json()["exercises"][0]["default_sets"] == slot["default_sets"]
    updated = await api.client.patch(
        path,
        auth=api.alice,
        json={
            "exercises": [
                {
                    **selection,
                    "sets": [{"reps": 6, "weight_kg": "85.25"}],
                }
            ]
        },
    )
    assert updated.status_code == 200
    result = updated.json()["exercises"][0]
    assert result["default_sets"][0]["reps"] == 6
    assert result["sets"][0]["reps"] == 12
    async with api.sessions() as session:
        entry = await session.scalar(
            sa.select(session_exercise.c.id).where(session_exercise.c.session_id == session_id)
        )
        assert (
            await session.scalar(
                sa.select(exercise_set.c.reps).where(exercise_set.c.session_exercise_id == entry)
            )
            == 12
        )
    for bad in (
        None,
        [{"reps": 0, "weight_kg": "1"}],
        [{"reps": True, "weight_kg": "1"}],
        [{"reps": 8, "weight_kg": "1.001"}],
        [{"reps": 8, "weight_kg": "NaN"}],
        [{"reps": 8, "weight_kg": "-1"}],
    ):
        rejected = await api.client.patch(
            path,
            auth=api.alice,
            json={"name": "Not saved", "exercises": [{**selection, "sets": bad}]},
        )
        assert rejected.status_code == 422
    assert (await api.client.get(path, auth=api.alice)).json()["name"] == "Planned"
    cleared = await api.client.patch(
        path, auth=api.alice, json={"exercises": [{**selection, "sets": []}]}
    )
    assert cleared.json()["exercises"][0]["default_sets"] == []


async def test_catalogue_groups_name_search_and_summary_projection(training_api):
    api = training_api
    async with api.sessions.begin() as session:
        await session.execute(
            sa.update(exercise)
            .where(exercise.c.id == api.private)
            .values(target_muscles=["PRIVATE_ONLY"])
        )
        await session.execute(
            sa.update(exercise)
            .where(exercise.c.id == api.running)
            .values(target_muscles=["RUNNING_ONLY"])
        )
        await session.execute(
            sa.update(exercise)
            .where(exercise.c.id == api.own)
            .values(name="100%_Press", target_muscles=["DELTOID", "", "PECTORALIS"])
        )
    groups = await api.client.get("/api/v1/exercises/muscle-groups", auth=api.alice)
    assert groups.status_code == 200
    assert groups.json() == {"items": ["DELTOID", "PECTORALIS", "QUADRICEPS"]}
    assert (await api.client.get("/api/v1/exercises/muscle-groups")).status_code == 401
    bob_groups = await api.client.get("/api/v1/exercises/muscle-groups", auth=api.bob)
    assert "PRIVATE_ONLY" in bob_groups.json()["items"]
    assert "DELTOID" not in bob_groups.json()["items"]
    filtered = await api.client.get(
        "/api/v1/exercises",
        auth=api.alice,
        params={"name": " CATALOGUE ", "muscle_group": "pectORALis", "limit": 2, "offset": 1},
    )
    assert [item["id"] for item in filtered.json()["items"]] == api.catalogue[2:6:2]
    assert set(filtered.json()["items"][0]) == {
        "id",
        "name",
        "activity_type",
        "body_parts",
        "target_muscles",
        "equipments",
        "image_url",
    }
    literal = await api.client.get("/api/v1/exercises", auth=api.alice, params={"name": "%_"})
    assert [item["id"] for item in literal.json()["items"]] == [api.own]
    for name in ("missing", "Bob private"):
        assert (
            await api.client.get("/api/v1/exercises", auth=api.alice, params={"name": name})
        ).json()["items"] == []
    before = (await api.client.get("/api/v1/exercises", auth=api.alice)).json()
    assert (
        await api.client.get("/api/v1/exercises", auth=api.alice, params={"name": "  "})
    ).json() == before
    assert (
        await api.client.get("/api/v1/exercises", auth=api.alice, params={"name": "a" * 201})
    ).status_code == 422
    # Full details stay on demand even though the list is projected in SQL.
    detail = await api.client.get(f"/api/v1/exercises/{api.catalogue[0]}", auth=api.alice)
    assert detail.json()["instructions"] == ["Control the movement"]


async def test_routine_name_search_is_literal_and_owned(training_api):
    api = training_api
    saved = await create(api)
    await api.client.patch(
        f"/api/v1/routines/{saved['id']}", auth=api.alice, json={"name": "Push 100%_"}
    )
    for name in (" PUSH ", "%_"):
        result = await api.client.get("/api/v1/routines", auth=api.alice, params={"name": name})
        assert [item["id"] for item in result.json()["items"]] == [saved["id"]]
    assert (await api.client.get("/api/v1/routines", auth=api.bob, params={"name": "Push"})).json()[
        "items"
    ] == []
    assert (
        await api.client.get("/api/v1/routines", auth=api.alice, params={"name": "x" * 151})
    ).status_code == 422


async def test_body_part_options_filtering_and_visibility(training_api):
    api = training_api
    async with api.sessions.begin() as session:
        for record, parts in (
            (api.private, ["PRIVATE_ONLY"]),
            (api.running, ["RUNNING_ONLY"]),
            (api.unowned, ["UNPUBLISHED_ONLY"]),
            (api.own, [" BACK ", "", "CHEST", "CHEST"]),
        ):
            await session.execute(
                sa.update(exercise).where(exercise.c.id == record).values(body_parts=parts)
            )
    path = "/api/v1/exercises/body-parts"
    assert (await api.client.get(path)).status_code == 401
    options = await api.client.get(path, auth=api.alice)
    assert options.json() == {"items": ["BACK", "CHEST", "UPPER ARMS"]}
    assert (await api.client.get(path, auth=api.bob)).json() == {
        "items": ["CHEST", "PRIVATE_ONLY", "UPPER ARMS"]
    }
    result = await api.client.get(
        "/api/v1/exercises",
        auth=api.alice,
        params={"body_part": " cHeSt ", "name": "catalogue", "limit": 2, "offset": 1},
    )
    assert result.status_code == 200
    assert [item["id"] for item in result.json()["items"]] == api.catalogue[2:6:2]
    back = await api.client.get("/api/v1/exercises", auth=api.alice, params={"body_part": "back"})
    assert [item["id"] for item in back.json()["items"]] == [api.own]
    for part in ("missing", "PRIVATE_ONLY", "RUNNING_ONLY", "UNPUBLISHED_ONLY"):
        assert (
            await api.client.get("/api/v1/exercises", auth=api.alice, params={"body_part": part})
        ).json()["items"] == []
    all_items = (await api.client.get("/api/v1/exercises", auth=api.alice)).json()
    assert (
        await api.client.get("/api/v1/exercises", auth=api.alice, params={"body_part": "  "})
    ).json() == all_items
    assert (
        await api.client.get("/api/v1/exercises", auth=api.alice, params={"body_part": "a" * 101})
    ).status_code == 422


async def test_multiple_body_parts_match_any_without_duplicates_and_keep_visibility(training_api):
    api = training_api
    async with api.sessions.begin() as session:
        await session.execute(
            sa.update(exercise)
            .where(exercise.c.id == api.catalogue[0])
            .values(body_parts=["CHEST", "UPPER ARMS"])
        )
        await session.execute(
            sa.update(exercise).where(exercise.c.id == api.private).values(body_parts=["CHEST"])
        )
    path = "/api/v1/exercises"
    params = [
        ("body_part", " chest "),
        ("body_part", "UPPER ARMS"),
        ("body_part", "CHEST"),
        ("name", "catalogue"),
        ("limit", "3"),
        ("offset", "2"),
    ]
    result = await api.client.get(path, auth=api.alice, params=params)
    assert result.status_code == 200
    assert [row["id"] for row in result.json()["items"]] == api.catalogue[2:5]
    all_matches = await api.client.get(
        path, auth=api.alice, params=[("body_part", "CHEST"), ("body_part", "UPPER ARMS")]
    )
    assert [row["id"] for row in all_matches.json()["items"]] == api.catalogue
    unknown = await api.client.get(
        path, auth=api.alice, params=[("body_part", "missing"), ("body_part", "chest")]
    )
    assert [row["id"] for row in unknown.json()["items"]] == api.catalogue[::2]
    invalid = await api.client.get(path, auth=api.alice, params=[("body_part", "CHEST")] * 31)
    assert invalid.status_code == 422


def completed_payload(api, **changes):
    return {
        "client_session_id": str(uuid4()),
        "started_at": "2026-10-24T16:00:00Z",
        "ended_at": "2026-10-24T16:45:00Z",
        "exercises": [
            {
                "exercise_id": api.catalogue[0],
                "sets": [{"reps": 8, "weight": {"value": "100.00", "unit": "lb"}}],
            }
        ],
        **changes,
    }


async def test_complete_blank_workout_units_history_isolation_and_retry(training_api):
    api = training_api
    payload = completed_payload(api)
    response = await api.client.post(
        "/api/v1/sessions?weight_unit=lb", auth=api.alice, json=payload
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["state"] == "completed" and saved["routine_id"] is None
    actual = saved["exercises"][0]["sets"][0]
    assert actual["weight_kg"] == "45.359237"
    assert actual["weight"] == {"value": "100.00", "unit": "lb"}
    path = f"/api/v1/sessions/{saved['id']}"
    assert (await api.client.get(path + "?weight_unit=lb", auth=api.alice)).json() == saved
    kg = (await api.client.get(path, auth=api.alice)).json()
    assert kg["exercises"][0]["sets"][0]["weight"] == {"value": "45.36", "unit": "kg"}
    for _ in range(3):
        repeated = await api.client.post(
            "/api/v1/sessions?weight_unit=lb", auth=api.alice, json=payload
        )
        assert repeated.status_code == 200 and repeated.json() == saved
    changed = {**payload, "ended_at": "2026-10-24T17:00:00Z"}
    assert (
        await api.client.post("/api/v1/sessions", auth=api.alice, json=changed)
    ).status_code == 409
    # Equal instants and normalized mass also represent the same aggregate.
    normalized = {
        **payload,
        "started_at": "2026-10-24T18:00:00+02:00",
        "exercises": [
            {
                "exercise_id": api.catalogue[0],
                "sets": [{"reps": 8, "weight": {"value": "45.359237", "unit": "kg"}}],
            }
        ],
    }
    assert (
        await api.client.post("/api/v1/sessions", auth=api.alice, json=normalized)
    ).status_code == 200
    assert (await api.client.get(path, auth=api.bob)).status_code == 404
    assert (await api.client.get("/api/v1/sessions", auth=api.bob)).json()["items"] == []
    second = await api.client.post(
        "/api/v1/sessions", auth=api.alice, json={**payload, "client_session_id": str(uuid4())}
    )
    assert second.status_code == 201 and second.json()["id"] != saved["id"]
    history = (await api.client.get("/api/v1/sessions?limit=1&offset=1", auth=api.alice)).json()
    assert history["items"][0]["id"] == saved["id"]
    async with api.sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(training_session)) == 2
        assert await session.scalar(sa.select(exercise_set.c.weight_kg).limit(1)) == Decimal(
            "45.359237"
        )


async def test_concurrent_completed_retry_and_changed_key_race(training_api):
    api = training_api
    payload = completed_payload(api)
    replies = await asyncio.gather(
        *[api.client.post("/api/v1/sessions", auth=api.alice, json=payload) for _ in range(4)]
    )
    assert sorted(reply.status_code for reply in replies) == [200, 200, 200, 201]
    assert len({reply.json()["id"] for reply in replies}) == 1
    changed = completed_payload(api)
    replies = await asyncio.gather(
        api.client.post("/api/v1/sessions", auth=api.alice, json=changed),
        api.client.post(
            "/api/v1/sessions", auth=api.alice, json={**changed, "ended_at": "2026-10-24T17:00:00Z"}
        ),
    )
    assert sorted(reply.status_code for reply in replies) == [201, 409]


async def test_completed_exercises_independent_of_template_slots(training_api):
    api = training_api
    template = await create(api, [api.catalogue[0], api.catalogue[0]])
    slots = template["exercises"]
    payload = completed_payload(
        api,
        routine_id=template["id"],
        exercises=[
            {
                "exercise_id": api.catalogue[0],
                "routine_exercise_id": slot["id"],
                "sets": [{"reps": index + 1, "weight": {"value": "0", "unit": "kg"}}],
            }
            for index, slot in enumerate(slots)
        ],
    )
    path = f"/api/v1/routines/{template['id']}"
    # Remove first slot; replace the other exercise while recording locally.
    update = await api.client.patch(
        path,
        auth=api.alice,
        json={"exercises": [{"id": slots[1]["id"], "exercise_id": api.catalogue[1]}]},
    )
    assert update.status_code == 200
    response = await api.client.post("/api/v1/sessions", auth=api.alice, json=payload)
    assert response.status_code == 201, response.text
    actual = response.json()["exercises"]
    assert all("routine_exercise_id" not in entry for entry in actual)
    assert [entry["exercise"]["id"] for entry in actual] == [api.catalogue[0]] * 2
    assert [entry["sets"][0]["reps"] for entry in actual] == [1, 2]
    forged = {
        **payload,
        "client_session_id": str(uuid4()),
        "exercises": [{**payload["exercises"][0], "routine_exercise_id": 999999}],
    }
    assert (
        await api.client.post("/api/v1/sessions", auth=api.alice, json=forged)
    ).status_code == 201
    # Another account cannot claim the session-level routine origin.
    assert (
        await api.client.post("/api/v1/sessions", auth=api.bob, json=payload)
    ).status_code == 422
    # A previously successful submission still retries after its exercise ceases to be selectable.
    async with api.sessions.begin() as session:
        await session.execute(
            sa.update(exercise).where(exercise.c.id == api.catalogue[0]).values(imported_at=None)
        )
    assert (
        await api.client.post("/api/v1/sessions", auth=api.alice, json=payload)
    ).status_code == 200


async def test_completed_invalid_nested_data_rollback_and_auth(training_api):
    api = training_api
    payload = completed_payload(api)
    assert (await api.client.post("/api/v1/sessions", json=payload)).status_code == 401
    for changes in (
        {"user_id": api.bob_id},
        {"started_at": "2026-10-24T16:00:00"},
        {"ended_at": "2026-10-24T15:00:00Z"},
        {"exercises": [{"exercise_id": api.private, "sets": payload["exercises"][0]["sets"]}]},
        {
            "exercises": [
                {
                    "exercise_id": api.catalogue[0],
                    "sets": [{"reps": True, "weight": {"value": "1", "unit": "kg"}}],
                }
            ]
        },
        {
            "exercises": [
                {
                    "exercise_id": api.catalogue[0],
                    "sets": [{"reps": 1, "weight": {"value": "NaN", "unit": "kg"}}],
                }
            ]
        },
        {
            "exercises": [
                {
                    "exercise_id": api.catalogue[0],
                    "sets": [{"reps": 1, "weight": {"value": 1, "unit": "kg"}}],
                }
            ]
        },
    ):
        result = await api.client.post(
            "/api/v1/sessions", auth=api.alice, json={**payload, **changes}
        )
        assert result.status_code == 422, result.text
    async with api.sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(training_session)) == 0


async def test_completed_database_failure_rolls_back_full_aggregate(training_api, monkeypatch):
    from app.features.training import sessions as service
    from app.features.training.schemas import SessionCreate

    api = training_api

    async def failed(*args, **kwargs):
        raise RuntimeError("injected response/database failure")

    monkeypatch.setattr(service, "get_session", failed)
    async with api.sessions() as session:
        with pytest.raises(RuntimeError):
            await service.create_session(
                session, api.alice_id, SessionCreate.model_validate(completed_payload(api))
            )
    async with api.sessions() as session:
        for table in (training_session, session_exercise, exercise_set):
            assert await session.scalar(sa.select(sa.func.count()).select_from(table)) == 0


async def test_explicit_routine_units_roundtrip_and_ambiguous_input(training_api):
    api = training_api
    payload = {
        "name": "Pounds",
        "exercises": [
            {
                "exercise_id": api.catalogue[0],
                "sets": [{"reps": 8, "weight": {"value": "100", "unit": "lb"}}],
            }
        ],
    }
    response = await api.client.post(
        "/api/v1/routines?weight_unit=lb", auth=api.alice, json=payload
    )
    assert response.status_code == 201, response.text
    actual = response.json()["exercises"][0]["sets"][0]
    assert actual["weight_kg"] == "45.359237"
    assert actual["weight"] == {"value": "100.00", "unit": "lb"}
    payload["exercises"][0]["sets"][0]["weight_kg"] = "45.36"
    assert (
        await api.client.post("/api/v1/routines", auth=api.alice, json=payload)
    ).status_code == 422


def draft_snapshot(api, *, confirmed=False):
    return {
        "name": "Upper body",
        "routine_id": None,
        "started_at": "2026-10-25T10:00:00Z",
        "exercises": [
            {
                "client_id": str(uuid4()),
                "exercise_id": api.catalogue[0],
                "routine_exercise_id": None,
                "sets": [
                    {
                        "client_id": str(uuid4()),
                        "reps": 6 if confirmed else None,
                        "weight": {"value": "100", "unit": "lb"} if confirmed else None,
                        "completed": confirmed,
                    }
                ],
            }
        ],
    }


async def test_draft_save_resume_confirm_finish_and_immutable_retries(training_api):
    api = training_api
    key = str(uuid4())
    path = f"/api/v1/session-drafts/{key}"
    data = draft_snapshot(api)
    assert (await api.client.get("/api/v1/session-drafts", auth=api.alice)).json() is None
    saved = await api.client.put(path, auth=api.alice, json=data)
    assert saved.status_code == 200, saved.text
    assert saved.json()["state"] == "draft"
    assert (await api.client.put(path, auth=api.alice, json=data)).json() == saved.json()
    # Dispose pooled connections to establish persistence independent of the request/connection.
    await api.sessions.kw["bind"].dispose()
    assert (await api.client.get("/api/v1/session-drafts", auth=api.alice)).json() == saved.json()
    assert (await api.client.get("/api/v1/sessions", auth=api.alice)).json()["items"] == []
    finish = {"ended_at": "2026-10-25T10:10:00Z"}
    value = data["exercises"][0]["sets"][0]
    value.update(reps=6, weight={"value": "100", "unit": "lb"}, completed=True)
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 200
    # Editing and unchecking a set must replace its stored confirmation.
    value.update(reps=7, completed=False)
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 200
    value["completed"] = True
    await api.client.put(path, auth=api.alice, json=data)
    result = await api.client.post(path + "/finish", auth=api.alice, json=finish)
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "completed"
    assert result.json()["exercises"][0]["sets"][0]["weight_kg"] == "45.359237"
    assert result.json()["exercises"][0]["sets"][0]["reps"] == 7
    assert (
        await api.client.post(path + "/finish", auth=api.alice, json=finish)
    ).json() == result.json()
    assert (await api.client.get("/api/v1/session-drafts", auth=api.alice)).json() is None
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 409
    assert (await api.client.delete(path, auth=api.alice)).status_code == 409
    assert (
        await api.client.post(
            path + "/finish", auth=api.alice, json={"ended_at": "2026-10-25T10:11:00Z"}
        )
    ).status_code == 409
    assert len((await api.client.get("/api/v1/sessions", auth=api.alice)).json()["items"]) == 1
    assert (
        await api.client.put(
            f"/api/v1/session-drafts/{uuid4()}", auth=api.alice, json=draft_snapshot(api)
        )
    ).status_code == 200


async def test_draft_ownership_discard_validation_and_single_active(training_api):
    api = training_api
    key = str(uuid4())
    path = f"/api/v1/session-drafts/{key}"
    data = draft_snapshot(api, confirmed=True)
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 200
    assert (await api.client.get("/api/v1/session-drafts", auth=api.bob)).json() is None
    assert (await api.client.delete(path, auth=api.bob)).status_code == 204
    assert (
        await api.client.post(
            path + "/finish", auth=api.bob, json={"ended_at": "2026-10-25T10:10:00Z"}
        )
    ).status_code == 404
    assert (
        await api.client.put(f"/api/v1/session-drafts/{uuid4()}", auth=api.alice, json=data)
    ).status_code == 409
    data["started_at"] = "2026-10-25T10:01:00Z"
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 409
    data["started_at"] = "2026-10-25T10:00:00Z"
    data["exercises"][0]["exercise_id"] = api.private
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 422
    assert (await api.client.get("/api/v1/session-drafts", auth=api.alice)).json()["exercises"][0][
        "exercise_id"
    ] == api.catalogue[0]
    assert (await api.client.delete(path, auth=api.alice)).status_code == 204
    assert (await api.client.delete(path, auth=api.alice)).status_code == 204
    assert (await api.client.get("/api/v1/session-drafts", auth=api.alice)).json() is None
    # Concurrent different keys cannot create two active drafts.
    data["exercises"][0]["exercise_id"] = api.catalogue[0]
    responses = await asyncio.gather(
        *[
            api.client.put(f"/api/v1/session-drafts/{uuid4()}", auth=api.alice, json=data)
            for _ in range(2)
        ]
    )
    assert sorted(result.status_code for result in responses) == [200, 409]


async def test_draft_rejects_invalid_confirmed_values_and_concurrent_finish_is_atomic(training_api):
    api = training_api
    key = str(uuid4())
    path = f"/api/v1/session-drafts/{key}"
    data = draft_snapshot(api)
    value = data["exercises"][0]["sets"][0]
    value["completed"] = True
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 422
    value.update(reps=6, weight={"value": "0", "unit": "kg"})
    data["exercises"][0]["sets"].append(dict(value))
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 422
    data["exercises"][0]["sets"].pop()
    data["started_at"] = "2026-10-25T10:00:00"
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 422
    data["started_at"] = "2026-10-25T10:00:00Z"
    data["exercises"][0]["sets"] = []
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 200
    finish = {"ended_at": "2026-10-25T10:10:00Z"}
    data["exercises"] = []
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 200
    data = draft_snapshot(api, confirmed=True)
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 200
    assert (
        await api.client.post(
            path + "/finish", auth=api.alice, json={"ended_at": "2026-10-25T09:59:00Z"}
        )
    ).status_code == 422
    # Legacy submission cannot bypass the active draft state machine.
    legacy = {
        "client_session_id": key,
        "routine_id": None,
        "started_at": data["started_at"],
        "ended_at": finish["ended_at"],
        "exercises": [
            {
                "exercise_id": api.catalogue[0],
                "sets": [{"reps": 6, "weight": {"value": "100", "unit": "lb"}}],
            }
        ],
    }
    assert (
        await api.client.post("/api/v1/sessions", auth=api.alice, json=legacy)
    ).status_code == 409
    results = await asyncio.gather(
        *[api.client.post(path + "/finish", auth=api.alice, json=finish) for _ in range(2)]
    )
    assert [result.status_code for result in results] == [200, 200]
    assert results[0].json() == results[1].json()
    async with api.sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(training_session)) == 1
        assert await session.scalar(sa.select(sa.func.count()).select_from(exercise_set)) == 1


async def test_partial_finish_prunes_unsaved_values_but_keeps_exercise_order(training_api):
    api = training_api
    key = str(uuid4())
    path = f"/api/v1/session-drafts/{key}"
    data = draft_snapshot(api, confirmed=True)
    data["exercises"][0]["sets"].append(
        {
            "client_id": str(uuid4()),
            "reps": "not a number",
            "weight": {"value": "invalid", "unit": "kg"},
            "completed": False,
        }
    )
    data["exercises"].append(
        {
            "client_id": str(uuid4()),
            "exercise_id": api.catalogue[1],
            "sets": [{"client_id": str(uuid4()), "reps": -1, "weight": "bad", "completed": False}],
        }
    )
    saved = await api.client.put(path, auth=api.alice, json=data)
    assert saved.status_code == 200, saved.text
    assert "routine_exercise_id" not in saved.json()["exercises"][0]
    result = await api.client.post(
        path + "/finish", auth=api.alice, json={"ended_at": "2026-10-25T10:10:00Z"}
    )
    assert result.status_code == 200, result.text
    entries = result.json()["exercises"]
    assert [entry["exercise"]["id"] for entry in entries] == api.catalogue[:2]
    assert [len(entry["sets"]) for entry in entries] == [1, 0]
    assert entries[0]["sets"][0]["set_number"] == 1
    async with api.sessions() as session:
        snapshot = await session.scalar(sa.select(session_draft.c.snapshot))
        assert [len(item["sets"]) for item in snapshot["exercises"]] == [1, 0]
        assert all(value["completed"] for item in snapshot["exercises"] for value in item["sets"])
        assert await session.scalar(sa.select(sa.func.count()).select_from(exercise_set)) == 1


async def test_blank_finish_and_empty_routine_update_validation(training_api):
    api = training_api
    template = await create(api)
    path = f"/api/v1/session-drafts/{uuid4()}"
    data = {**draft_snapshot(api), "routine_id": template["id"], "exercises": []}
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 200
    finish = {"ended_at": "2026-10-25T10:10:00Z"}
    assert (
        await api.client.post(
            path + "/finish", auth=api.alice, json={**finish, "update_routine": True}
        )
    ).status_code == 422
    assert (await api.client.get("/api/v1/session-drafts", auth=api.alice)).json() is not None
    result = await api.client.post(path + "/finish", auth=api.alice, json=finish)
    assert result.status_code == 200 and result.json()["exercises"] == []
    assert result.json()["routine_id"] == template["id"]
    assert (
        await api.client.get(f"/api/v1/routines/{template['id']}", auth=api.alice)
    ).json() == template


async def test_finish_optional_routine_update_is_atomic_and_retry_decision_is_frozen(training_api):
    api = training_api
    template = await create(api)
    routine_path = f"/api/v1/routines/{template['id']}"
    path = f"/api/v1/session-drafts/{uuid4()}"
    data = draft_snapshot(api, confirmed=True)
    data["routine_id"] = template["id"]
    data["exercises"][0]["exercise_id"] = api.catalogue[3]
    data["exercises"].append(
        {
            "client_id": str(uuid4()),
            "exercise_id": api.catalogue[3],
            "sets": [],
        }
    )
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 200
    changed_origin = {**data, "routine_id": None}
    assert (await api.client.put(path, auth=api.alice, json=changed_origin)).status_code == 409
    finish = {"ended_at": "2026-10-25T10:10:00Z", "update_routine": True}
    result = await api.client.post(path + "/finish", auth=api.alice, json=finish)
    assert result.status_code == 200, result.text
    assert result.json()["routine_id"] == template["id"]
    updated = (await api.client.get(routine_path, auth=api.alice)).json()
    assert updated["name"] == template["name"]
    assert [item["exercise"]["id"] for item in updated["exercises"]] == [api.catalogue[3]] * 2
    assert [len(item["default_sets"]) for item in updated["exercises"]] == [1, 0]
    assert updated["exercises"][0]["default_sets"][0]["weight_kg"] == "45.359237"
    # A retry must not overwrite changes made to the routine after completion.
    await api.client.patch(
        routine_path, auth=api.alice, json={"exercises": [{"exercise_id": api.catalogue[4]}]}
    )
    assert (
        await api.client.post(path + "/finish", auth=api.alice, json=finish)
    ).json() == result.json()
    assert (await api.client.get(routine_path, auth=api.alice)).json()["exercises"][0]["exercise"][
        "id"
    ] == api.catalogue[4]
    assert (
        await api.client.post(
            path + "/finish", auth=api.alice, json={**finish, "update_routine": False}
        )
    ).status_code == 409
    assert (await api.client.post(path + "/finish", auth=api.bob, json=finish)).status_code == 404
    path = f"/api/v1/session-drafts/{uuid4()}"
    assert (await api.client.put(path, auth=api.bob, json=data)).status_code == 422
    # Keep-routine completion leaves template defaults and selection unchanged.
    data["exercises"][0]["exercise_id"] = api.catalogue[5]
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 200
    assert (
        await api.client.post(
            path + "/finish", auth=api.alice, json={**finish, "update_routine": False}
        )
    ).status_code == 200
    assert (await api.client.get(routine_path, auth=api.alice)).json()["exercises"][0]["exercise"][
        "id"
    ] == api.catalogue[4]


async def test_finish_routine_update_failure_rolls_back_workout_and_template(
    training_api, monkeypatch
):
    from app.features.training import drafts
    from app.features.training.schemas import DraftFinish

    api = training_api
    template = await create(api)
    key = uuid4()
    path = f"/api/v1/session-drafts/{key}"
    data = {**draft_snapshot(api, confirmed=True), "routine_id": template["id"]}
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 200
    replace = drafts.replace_routine_from_session

    async def fail_after_update(*args):
        await replace(*args)
        raise RuntimeError("injected post-update failure")

    monkeypatch.setattr(drafts, "replace_routine_from_session", fail_after_update)
    async with api.sessions() as session:
        with pytest.raises(RuntimeError, match="injected post-update"):
            await drafts.finish_draft(
                session,
                api.alice_id,
                key,
                DraftFinish.model_validate(
                    {
                        "ended_at": "2026-10-25T10:10:00Z",
                        "update_routine": True,
                    }
                ),
            )
    async with api.sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(training_session)) == 0
        assert await session.scalar(sa.select(session_draft.c.completed_session_id)) is None
    assert (
        await api.client.get(f"/api/v1/routines/{template['id']}", auth=api.alice)
    ).json() == template


async def test_last_configuration_uses_owned_latest_nonempty_occurrence_and_units(training_api):
    api = training_api
    exercise_id = api.catalogue[0]
    path = f"/api/v1/exercises/{exercise_id}/last-configuration"
    assert (await api.client.get(path)).status_code == 401
    assert (await api.client.get(path, auth=api.alice)).json() == {
        "exercise_id": exercise_id,
        "sets": [],
    }
    assert (
        await api.client.get(f"/api/v1/exercises/{api.private}/last-configuration", auth=api.alice)
    ).status_code == 404
    for reps, ended in ((5, "2026-10-24T17:00:00Z"), (7, "2026-10-24T18:00:00Z")):
        payload = completed_payload(
            api,
            ended_at=ended,
            exercises=[
                {
                    "exercise_id": exercise_id,
                    "sets": [{"reps": reps, "weight": {"value": "100", "unit": "lb"}}],
                },
                {
                    "exercise_id": exercise_id,
                    "sets": [{"reps": reps + 1, "weight": {"value": "100", "unit": "lb"}}],
                },
                {"exercise_id": exercise_id, "sets": []},
            ],
        )
        assert (
            await api.client.post("/api/v1/sessions", auth=api.alice, json=payload)
        ).status_code == 201
    # A later session with no recorded set and another account's history are excluded.
    for auth, sets in (
        (api.alice, []),
        (api.bob, [{"reps": 99, "weight": {"value": "1", "unit": "kg"}}]),
    ):
        payload = completed_payload(
            api,
            ended_at="2026-10-24T19:00:00Z",
            exercises=[
                {
                    "exercise_id": exercise_id,
                    "sets": sets,
                }
            ],
        )
        assert (
            await api.client.post("/api/v1/sessions", auth=auth, json=payload)
        ).status_code == 201
    result = (await api.client.get(path + "?weight_unit=lb", auth=api.alice)).json()
    assert result["sets"][0]["reps"] == 8
    assert result["sets"][0]["weight"] == {"value": "100.00", "unit": "lb"}
    assert (await api.client.get(path, auth=api.alice)).json()["sets"][0]["weight"][
        "value"
    ] == "45.36"
    template = await create(api, [exercise_id, exercise_id])
    assert [item["sets"][0]["reps"] for item in template["exercises"]] == [8, 8]
    assert all(item["default_sets"] == [] for item in template["exercises"])


async def test_legacy_slot_fingerprint_retries_remain_compatible(training_api):
    import hashlib
    import json

    from app.features.training.schemas import SessionCreate
    from app.features.training.sessions import normalized_payload

    api = training_api
    payload = completed_payload(api)
    payload["exercises"][0]["routine_exercise_id"] = 12345
    saved = await api.client.post("/api/v1/sessions", auth=api.alice, json=payload)
    assert saved.status_code == 201
    old_fingerprint = hashlib.sha256(
        json.dumps(
            normalized_payload(SessionCreate.model_validate(payload), legacy=True),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    async with api.sessions.begin() as session:
        await session.execute(
            training_session.update()
            .where(training_session.c.id == saved.json()["id"])
            .values(payload_fingerprint=old_fingerprint)
        )
    assert (
        await api.client.post("/api/v1/sessions", auth=api.alice, json=payload)
    ).status_code == 200
    payload["exercises"][0]["sets"][0]["reps"] += 1
    assert (
        await api.client.post("/api/v1/sessions", auth=api.alice, json=payload)
    ).status_code == 409


async def test_unavailable_routine_update_preserves_draft_and_actual_values(training_api):
    api = training_api
    template = await create(api)
    path = f"/api/v1/session-drafts/{uuid4()}"
    data = {**draft_snapshot(api, confirmed=True), "routine_id": template["id"]}
    assert (await api.client.put(path, auth=api.alice, json=data)).status_code == 200
    async with api.sessions.begin() as session:
        await session.execute(
            routine_exercise.delete().where(routine_exercise.c.routine_id == template["id"])
        )
        await session.execute(routine.delete().where(routine.c.id == template["id"]))
    result = await api.client.post(
        path + "/finish",
        auth=api.alice,
        json={
            "ended_at": "2026-10-25T10:10:00Z",
            "update_routine": True,
        },
    )
    assert result.status_code == 422
    restored = (await api.client.get("/api/v1/session-drafts", auth=api.alice)).json()
    assert restored["exercises"][0]["sets"][0]["reps"] == 6
    assert restored["routine_id"] == template["id"]
    assert (await api.client.get("/api/v1/sessions", auth=api.alice)).json()["items"] == []
