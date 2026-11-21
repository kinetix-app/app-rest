"""Workout posts API: feed visibility, media, likes, comments and failure cleanup."""

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from azure.core.exceptions import ResourceNotFoundError
from PIL import Image
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.features.accounts.models import User
from app.features.posts import service
from app.features.posts.models import file, post, post_comment, post_like
from app.features.training.models import exercise, training_session
from app.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
POSTS = "/api/v1/posts"


class FakeStorage:
    """In-memory private post container; uploads can be made to fail."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.fail_upload_after: int | None = None

    async def upload_post_media(self, name, data):
        if self.fail_upload_after is not None and len(self.blobs) >= self.fail_upload_after:
            raise OSError("storage down")
        self.blobs[name] = data

    async def read_post_media(self, name):
        if name not in self.blobs:
            raise ResourceNotFoundError("missing")
        return self.blobs[name]

    async def delete_post_media(self, name):
        self.blobs.pop(name, None)

    async def read_profile_picture(self, name):
        if name not in self.blobs:
            raise ResourceNotFoundError("missing")
        return self.blobs[name]

    def post_media_blob_url(self, name):
        return f"http://blob.test/post-media/{name}"

    async def close(self):
        pass


def png(size=(32, 24)):
    output = BytesIO()
    image = Image.new("RGB", size, "blue")
    exif = Image.Exif()
    exif[270] = "Private metadata"
    image.save(output, format="PNG", exif=exif)
    return output.getvalue()


@pytest.fixture
async def posts_api(integration_url):
    schema = "posts_" + uuid4().hex
    admin = create_async_engine(integration_url)
    engine = create_async_engine(
        integration_url, connect_args={"options": f"-csearch_path={schema}"}
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
            basic_auth_users={name: SecretStr("password") for name in ("alice", "bob", "carol")},
            database_url=SecretStr(integration_url.render_as_string(hide_password=False)),
        )
        app = create_app(settings)
        async with LifespanManager(app):
            app.state.session_factory = sessions
            storage = FakeStorage()
            app.state.blob_storage = storage
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                auth = {
                    name: httpx.BasicAuth(name, "password") for name in ("alice", "bob", "carol")
                }
                ids = {
                    name: (await client.get("/api/v1/me", auth=value)).json()["id"]
                    for name, value in auth.items()
                }
                async with sessions.begin() as session:
                    catalogue = [
                        await session.scalar(
                            exercise.insert()
                            .values(
                                name=f"Catalogue {i}",
                                activity_type="gym",
                                source="ascend_edb_v2",
                                external_id=f"exr_{i}",
                                imported_at=datetime.now(UTC),
                            )
                            .returning(exercise.c.id)
                        )
                        for i in range(2)
                    ]
                yield SimpleNamespace(
                    app=app,
                    client=client,
                    sessions=sessions,
                    storage=storage,
                    catalogue=catalogue,
                    **auth,
                    alice_id=ids["alice"],
                    bob_id=ids["bob"],
                    carol_id=ids["carol"],
                )
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def workout(api, auth):
    """Complete a workout through the real sessions API: 3 sets, 23 reps, 1312.50 kg."""
    response = await api.client.post(
        "/api/v1/sessions",
        auth=auth,
        json={
            "client_session_id": str(uuid4()),
            "started_at": "2026-11-09T16:00:00Z",
            "ended_at": "2026-11-09T16:45:00Z",
            "exercises": [
                {
                    "exercise_id": api.catalogue[0],
                    "sets": [
                        {"reps": 8, "weight": {"value": "100.00", "unit": "kg"}},
                        {"reps": 5, "weight": {"value": "62.50", "unit": "kg"}},
                    ],
                },
                {
                    "exercise_id": api.catalogue[1],
                    "sets": [{"reps": 10, "weight": {"value": "20.00", "unit": "kg"}}],
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def share(api, auth, session_id, *, text="Leg day", images=0, **fields):
    files = [("files", (f"photo{i}.png", png(), "image/png")) for i in range(images)]
    return await api.client.post(
        POSTS,
        auth=auth,
        data={"training_session_id": str(session_id), "text": text, **fields},
        files=files or None,
    )


async def shared(api, auth, **options):
    response = await share(api, auth, await workout(api, auth), **options)
    assert response.status_code == 201, response.text
    return response.json()


async def count(api, table):
    async with api.sessions() as session:
        return await session.scalar(sa.select(sa.func.count()).select_from(table))


async def test_share_workout_with_images_feed_and_media(posts_api):
    api = posts_api
    session_id = await workout(api, api.alice)
    response = await share(api, api.alice, session_id, text="  Leg day  ", images=2)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["text"] == "Leg day"
    assert (created["visibility"], created["type"]) == ("PUBLIC", "SESSION")
    assert created["author"]["id"] == api.alice_id
    assert (created["like_count"], created["comment_count"]) == (0, 0)
    assert (created["liked_by_me"], created["is_mine"]) == (False, True)
    assert created["workout"] == {
        "session_id": session_id,
        "activity_type": "gym",
        "started_at": "2026-11-09T16:00:00Z",
        "ended_at": "2026-11-09T16:45:00Z",
        "duration_seconds": 2700,
        "exercise_count": 2,
        "set_count": 3,
        "total_reps": 23,
        "total_volume_kg": "1312.50",
        "exercises": ["Catalogue 0", "Catalogue 1"],
    }
    media = created["media"]
    assert [item["order"] for item in media] == [1, 2]
    assert all(item["type"] == "IMAGE" for item in media)
    assert media[0]["url"] == f"{POSTS}/{created['id']}/media/{media[0]['id']}"

    image = await api.client.get(media[0]["url"], auth=api.bob)
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.headers["cache-control"] == "private, max-age=3600"
    with Image.open(BytesIO(image.content)) as decoded:
        assert decoded.format == "JPEG"
        assert decoded.size == (32, 24)
        assert not decoded.getexif()

    async with api.sessions() as session:
        rows = (await session.execute(sa.select(file))).mappings().all()
    assert {row["file_name"] for row in rows} == set(api.storage.blobs)
    assert all(row["file_name"].startswith(f"posts/{api.alice_id}/") for row in rows)
    assert all(row["url"].startswith("http://blob.test/post-media/posts/") for row in rows)
    assert all(row["file_size"] == len(api.storage.blobs[row["file_name"]]) for row in rows)

    seen = (await api.client.get(POSTS, auth=api.bob)).json()
    assert [item["id"] for item in seen["items"]] == [created["id"]]
    assert seen["items"][0]["is_mine"] is False
    assert seen["next_before_id"] is None
    assert (await api.client.get(f"{POSTS}/{created['id']}", auth=api.alice)).json() == created

    again = await share(api, api.alice, session_id, images=1)
    assert again.status_code == 409
    assert len(api.storage.blobs) == 2


async def test_post_workout_details_follow_post_visibility(posts_api):
    api = posts_api
    public = await shared(api, api.alice)
    response = await api.client.get(f"{POSTS}/{public['id']}/workout", auth=api.bob)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["set_count"] == 3
    assert detail["total_volume_kg"] == "1312.50"
    assert [len(item["sets"]) for item in detail["detailed_exercises"]] == [2, 1]
    first = detail["detailed_exercises"][0]
    assert first["exercise_id"] == api.catalogue[0]
    assert [(s["set_number"], s["reps"], s["weight_kg"]) for s in first["sets"]] == [
        (1, 8, "100.00"),
        (2, 5, "62.50"),
    ]

    private = await shared(api, api.alice, visibility="PRIVATE")
    path = f"{POSTS}/{private['id']}/workout"
    assert (await api.client.get(path, auth=api.bob)).status_code == 404
    assert (await api.client.get(path, auth=api.alice)).status_code == 200

    free = await api.client.post(POSTS, auth=api.alice, data={"text": "Rest day"})
    assert free.status_code == 201, free.text
    free_path = f"{POSTS}/{free.json()['id']}/workout"
    assert (await api.client.get(free_path, auth=api.alice)).status_code == 404


async def test_share_validation_leaves_no_posts_or_blobs(posts_api):
    api = posts_api
    session_id = await workout(api, api.alice)
    async with api.sessions.begin() as session:
        unfinished = await session.scalar(
            training_session.insert()
            .values(
                user_id=api.alice_id,
                activity_type="gym",
                started_at=datetime(2026, 11, 9, tzinfo=UTC),
            )
            .returning(training_session.c.id)
        )
    for auth, target in ((api.bob, session_id), (api.alice, 999_999), (api.alice, unfinished)):
        response = await share(api, auth, target, images=1)
        assert response.status_code == 422, response.text
    cases = [
        ({"visibility": "LEAGUE"}, 422),
        ({"text": "x" * 2201}, 422),
        ({"images": 6}, 422),
    ]
    for fields, status in cases:
        assert (await share(api, api.alice, session_id, **fields)).status_code == status
    for payload, mime, status in ((b"bad", "image/png", 422), (b"GIF89a", "image/gif", 415)):
        response = await api.client.post(
            POSTS,
            auth=api.alice,
            data={"training_session_id": str(session_id)},
            files=[("files", ("x", payload, mime))],
        )
        assert response.status_code == status
    for data in ({}, {"text": "   "}):
        empty = await api.client.post(POSTS, auth=api.alice, data=data)
        assert empty.status_code == 422, data
        assert empty.json()["detail"] == "Add a caption, a photo or a workout"
    assert (await api.client.get(POSTS)).status_code == 401
    assert await count(api, post) == 0
    assert api.storage.blobs == {}


async def test_posts_without_a_workout_need_a_caption_or_photo(posts_api):
    api = posts_api
    text_only = await api.client.post(POSTS, auth=api.alice, data={"text": "  Rest day  "})
    assert text_only.status_code == 201, text_only.text
    created = text_only.json()
    assert (created["type"], created["text"], created["workout"]) == ("GENERAL", "Rest day", None)
    photo_only = await api.client.post(
        POSTS,
        auth=api.alice,
        data={"visibility": "PRIVATE"},
        files=[("files", ("view.png", png(), "image/png"))],
    )
    assert photo_only.status_code == 201, photo_only.text
    body = photo_only.json()
    assert (body["type"], body["text"], body["visibility"]) == ("GENERAL", "", "PRIVATE")
    assert len(body["media"]) == 1
    feed = (await api.client.get(POSTS, auth=api.bob)).json()["items"]
    assert [item["id"] for item in feed] == [created["id"]]
    # Free posts never consume a workout: it can still be shared afterwards.
    assert (await share(api, api.alice, await workout(api, api.alice))).status_code == 201


async def test_private_posts_and_blocked_authors_are_hidden(posts_api):
    api = posts_api
    private = await shared(api, api.alice, visibility="PRIVATE", images=1)
    path = f"{POSTS}/{private['id']}"
    assert private["visibility"] == "PRIVATE"
    assert [
        item["id"] for item in (await api.client.get(POSTS, auth=api.bob)).json()["items"]
    ] == []
    for method, url, body in (
        ("GET", path, None),
        ("PUT", path + "/like", None),
        ("GET", path + "/comments", None),
        ("POST", path + "/comments", {"comment": "Hi"}),
        ("GET", private["media"][0]["url"], None),
        ("DELETE", path, None),
    ):
        response = await api.client.request(method, url, auth=api.bob, json=body)
        assert response.status_code == 404, (method, url)
    assert (await api.client.get(path, auth=api.alice)).status_code == 200

    public = await shared(api, api.bob)
    assert public["id"] in [
        item["id"] for item in (await api.client.get(POSTS, auth=api.alice)).json()["items"]
    ]
    async with api.sessions.begin() as session:
        await session.execute(sa.update(User).where(User.id == api.bob_id).values(status="blocked"))
    feed = (await api.client.get(POSTS, auth=api.alice)).json()["items"]
    assert [item["id"] for item in feed] == [private["id"]]
    assert (await api.client.get(f"{POSTS}/{public['id']}", auth=api.alice)).status_code == 404


async def test_likes_are_idempotent_and_per_account(posts_api):
    api = posts_api
    created = await shared(api, api.alice)
    like = f"{POSTS}/{created['id']}/like"
    for _ in range(2):
        response = await api.client.put(like, auth=api.bob)
        assert response.json() == {"liked": True, "like_count": 1}
    assert (await api.client.put(like, auth=api.alice)).json() == {"liked": True, "like_count": 2}
    detail = (await api.client.get(f"{POSTS}/{created['id']}", auth=api.carol)).json()
    assert (detail["like_count"], detail["liked_by_me"]) == (2, False)
    detail = (await api.client.get(f"{POSTS}/{created['id']}", auth=api.bob)).json()
    assert detail["liked_by_me"] is True
    for _ in range(2):
        response = await api.client.delete(like, auth=api.bob)
        assert response.json() == {"liked": False, "like_count": 1}
    assert (await api.client.put(f"{POSTS}/999999/like", auth=api.bob)).status_code == 404


async def test_comments_pagination_validation_and_permissions(posts_api):
    api = posts_api
    created = await shared(api, api.alice)
    comments = f"{POSTS}/{created['id']}/comments"
    response = await api.client.post(comments, auth=api.bob, json={"comment": "  Nice  "})
    assert response.status_code == 201, response.text
    first = response.json()
    assert first["comment"] == "Nice"
    assert (first["author"]["id"], first["is_mine"], first["post_id"]) == (
        api.bob_id,
        True,
        created["id"],
    )
    for body in ({"comment": "   "}, {"comment": "x" * 1001}, {"comment": "Hi", "extra": 1}, {}):
        assert (await api.client.post(comments, auth=api.bob, json=body)).status_code == 422
    for text in ("Two", "Three", "Four"):
        assert (
            await api.client.post(comments, auth=api.alice, json={"comment": text})
        ).status_code == 201

    page = (await api.client.get(comments + "?limit=2", auth=api.carol)).json()
    assert [item["comment"] for item in page["items"]] == ["Nice", "Two"]
    assert page["items"][0]["is_mine"] is False
    rest = (
        await api.client.get(f"{comments}?limit=2&after_id={page['next_after_id']}", auth=api.carol)
    ).json()
    assert [item["comment"] for item in rest["items"]] == ["Three", "Four"]
    assert rest["next_after_id"] is None
    assert (await api.client.get(f"{POSTS}/{created['id']}", auth=api.bob)).json()[
        "comment_count"
    ] == 4

    by_bob = f"{comments}/{first['id']}"
    assert (await api.client.delete(by_bob, auth=api.carol)).status_code == 403
    assert (await api.client.delete(by_bob, auth=api.alice)).status_code == 204
    own = rest["items"][0]["id"]
    assert (await api.client.delete(f"{comments}/{own}", auth=api.alice)).status_code == 204
    assert (await api.client.delete(by_bob, auth=api.alice)).status_code == 404
    other = await shared(api, api.bob)
    misplaced = f"{POSTS}/{other['id']}/comments/{rest['items'][1]['id']}"
    assert (await api.client.delete(misplaced, auth=api.bob)).status_code == 404
    assert await count(api, post_comment) == 2


async def test_delete_post_removes_children_and_blobs_then_allows_reshare(posts_api):
    api = posts_api
    session_id = await workout(api, api.alice)
    created = (await share(api, api.alice, session_id, images=1)).json()
    path = f"{POSTS}/{created['id']}"
    await api.client.put(path + "/like", auth=api.bob)
    await api.client.post(path + "/comments", auth=api.bob, json={"comment": "Great"})
    assert (await api.client.delete(path, auth=api.bob)).status_code == 403
    assert (await api.client.delete(path, auth=api.alice)).status_code == 204
    assert api.storage.blobs == {}
    for table in (post, file, post_like, post_comment):
        assert await count(api, table) == 0
    assert (await api.client.get(path, auth=api.alice)).status_code == 404
    assert (await share(api, api.alice, session_id)).status_code == 201


async def test_feed_cursor_pagination_and_limits(posts_api):
    api = posts_api
    first, second, third = [(await shared(api, api.alice))["id"] for _ in range(3)]
    page = (await api.client.get(POSTS + "?limit=2", auth=api.bob)).json()
    assert [item["id"] for item in page["items"]] == [third, second]
    assert page["next_before_id"] == second
    rest = (await api.client.get(f"{POSTS}?limit=2&before_id={second}", auth=api.bob)).json()
    assert [item["id"] for item in rest["items"]] == [first]
    assert rest["next_before_id"] is None
    for query in ("limit=0", "limit=51", "before_id=0"):
        assert (await api.client.get(f"{POSTS}?{query}", auth=api.bob)).status_code == 422


async def test_storage_and_database_failures_leave_no_partial_posts(posts_api, monkeypatch):
    api = posts_api
    session_id = await workout(api, api.alice)
    api.storage.fail_upload_after = 1
    assert (await share(api, api.alice, session_id, images=2)).status_code == 503
    assert api.storage.blobs == {}
    assert await count(api, post) == 0
    api.storage.fail_upload_after = None

    def broken(*args, **kwargs):
        raise RuntimeError("database failure after upload")

    with monkeypatch.context() as patch:
        patch.setattr(service, "get_post", broken)
        with pytest.raises(RuntimeError):
            await share(api, api.alice, session_id, images=1)
    assert api.storage.blobs == {}
    assert await count(api, post) == 0
    assert await count(api, file) == 0

    with_image = (await share(api, api.alice, session_id, images=1)).json()
    api.app.state.blob_storage = None
    try:
        image = await api.client.get(with_image["media"][0]["url"], auth=api.bob)
        assert image.status_code == 503
        other = await workout(api, api.alice)
        assert (await share(api, api.alice, other, images=1)).status_code == 503
        assert (await share(api, api.alice, other)).status_code == 201
    finally:
        api.app.state.blob_storage = api.storage
    missing = f"{POSTS}/{with_image['id']}/media/999999"
    assert (await api.client.get(missing, auth=api.bob)).status_code == 404
    api.storage.blobs.clear()
    assert (await api.client.get(with_image["media"][0]["url"], auth=api.bob)).status_code == 404
