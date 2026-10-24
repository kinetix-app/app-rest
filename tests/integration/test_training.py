"""Training API persistence, catalogue visibility and template/history isolation."""

import asyncio
from datetime import UTC, datetime, timedelta
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
                started_at=datetime(2026, 10, 20),
                ended_at=ended_at,
            )
            .returning(training_session.c.id)
        )
        for slot in slots:
            entry_id = await session.scalar(
                session_exercise.insert()
                .values(
                    session_id=session_id,
                    routine_exercise_id=slot["id"],
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
    now = datetime(2026, 10, 21, 12)
    await add_workout(api, saved["id"], slots, ended_at=now - timedelta(days=1), reps=8)
    latest_id = await add_workout(api, saved["id"], slots[:2], ended_at=now, reps=12)
    # Active and another account's later session cannot override this account's completed workout.
    await add_workout(api, saved["id"], slots, reps=90)
    await add_workout(
        api, saved["id"], slots, user_id=api.bob_id, ended_at=now + timedelta(hours=1), reps=99
    )
    loaded = (await api.client.get(path, auth=api.alice)).json()["exercises"]
    assert [slot["sets"][0]["reps"] for slot in loaded] == [12, 12, 5]
    assert loaded[0]["default_sets"][0]["weight_kg"] == "20.00"
    assert loaded[0]["sets"][0]["weight_kg"] == "42.50"
    assert [slot["sets_source"] for slot in loaded] == [
        "latest_session",
        "latest_session",
        "routine",
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
        assert historical[0]["routine_exercise_id"] is None
        assert historical[0]["exercise_id"] == api.catalogue[0]
        assert historical[1]["routine_exercise_id"] == slots[1]["id"]
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
    assert [row["weight_kg"] for row in slot["default_sets"]] == ["80.00", "0.00"]
    path = f"/api/v1/routines/{saved['id']}"
    assert (await api.client.get(path, auth=api.alice)).json() == saved
    session_id = await add_workout(
        api, saved["id"], [slot], ended_at=datetime(2026, 10, 21), reps=12
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
