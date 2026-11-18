"""Atomic league creation and administration through the multipart API."""

import json

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from tests.integration.test_league_membership import league_api  # noqa: F401
from tests.integration.test_league_pictures import image, picture_api  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
LEAGUES = "/api/v1/leagues"


def parts(data, color=None):
    result = {"data": (None, json.dumps(data))}
    if color is not None:
        result["file"] = ("league.png", image(color), "image/png")
    return result


async def test_timezones_and_configuration_without_picture(league_api):  # noqa: F811
    client, _ = league_api
    alice = httpx.BasicAuth("alice", "password")
    timezones = LEAGUES + "/timezones"
    assert (await client.get(timezones)).status_code == 401
    zones = (await client.get(timezones, auth=alice)).json()
    assert zones == sorted(set(zones))
    assert {"UTC", "Europe/Madrid"} <= set(zones)
    create_path = LEAGUES + "/configuration"
    data = {"name": "Team", "description": "Weekly club", "timezone": "Europe/Madrid"}
    assert (await client.post(create_path, auth=alice, json=data)).status_code == 415
    assert (
        await client.post(
            create_path,
            auth=alice,
            content=b"not multipart",
            headers={"Content-Type": "multipart/form-data; boundary=fixture-boundary"},
        )
    ).status_code == 422
    assert (
        await client.post(create_path, auth=alice, files=parts(data | {"timezone": "invalid"}))
    ).status_code == 422
    created = await client.post(create_path, auth=alice, files=parts(data))
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["picture_url"] is None
    lid = item["id"]
    path = f"{LEAGUES}/{lid}/configuration"
    changed = await client.post(
        path, auth=alice, files=parts({"name": "Renamed", "description": None})
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "Renamed"
    assert changed.json()["description"] is None
    assert changed.json()["timezone"] == data["timezone"]
    assert changed.json()["members"][0]["role"] == "admin"
    assert (
        await client.post(path, auth=alice, files=parts({"name": "Renamed", "timezone": "UTC"}))
    ).status_code == 422


async def test_configuration_fields_rollback_with_logo_and_removal(picture_api, monkeypatch):  # noqa: F811
    client, sessions, _, storage, container, (alice, bob, eve), ids, lid = picture_api
    create_path = LEAGUES + "/configuration"
    data = {"name": "With logo", "description": "Wednesdays", "timezone": "UTC"}
    created = await client.post(create_path, auth=alice, files=parts(data, "red"))
    assert created.status_code == 201, created.text
    assert created.json()["picture_url"]
    assert created.json()["description"] == data["description"]
    assert (await client.get(created.json()["picture_url"], auth=alice)).status_code == 200
    item_path = f"{LEAGUES}/{lid}"
    path = item_path + "/configuration"
    config = {"name": "New logo", "description": "Weekends"}
    assert (await client.post(path, auth=bob, files=parts(config, "blue"))).status_code == 403
    assert (await client.post(path, auth=eve, files=parts(config))).status_code == 404
    assert (
        await client.post(path, auth=alice, files=parts(config | {"remove_picture": True}, "blue"))
    ).status_code == 422
    updated = await client.post(path, auth=alice, files=parts(config, "blue"))
    assert updated.status_code == 200, updated.text
    previous = updated.json()
    assert previous["name"] == config["name"]
    assert previous["description"] == config["description"]
    assert previous["picture_url"]
    assert (await client.get(previous["picture_url"], auth=bob)).status_code == 200
    assert (await client.get(previous["picture_url"], auth=eve)).status_code == 404
    blobs_before = {blob.name async for blob in container.list_blobs()}

    async def unavailable(*args):
        raise TimeoutError

    with monkeypatch.context() as patch:
        patch.setattr(storage, "upload_profile_picture", unavailable)
        broken = {"name": "Not saved", "description": None}
        assert (
            await client.post(path, auth=alice, files=parts(broken, "green"))
        ).status_code == 503
        assert (
            await client.post(create_path, auth=alice, files=parts(data, "green"))
        ).status_code == 503
    assert (await client.get(item_path, auth=alice)).json() == previous

    # Force a real SQL failure after publishing the staged image.
    async with sessions.begin() as session:
        await session.execute(
            sa.text("""
                CREATE FUNCTION reject_configured_league() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.name = 'Reject in database' THEN
                        RAISE EXCEPTION 'test configuration rollback';
                    END IF;
                    RETURN NEW;
                END;
                $$
            """)
        )
        await session.execute(
            sa.text("""
                CREATE TRIGGER reject_configured_league BEFORE INSERT OR UPDATE ON league
                FOR EACH ROW EXECUTE FUNCTION reject_configured_league()
            """)
        )
    broken = {"name": "Reject in database", "description": None}
    broken_edit_parts = parts(broken, "green")
    broken_create_parts = parts(broken | {"timezone": "UTC"}, "green")
    with pytest.raises(DBAPIError, match="test configuration rollback"):
        await client.post(path, auth=alice, files=broken_edit_parts)
    with pytest.raises(DBAPIError, match="test configuration rollback"):
        await client.post(create_path, auth=alice, files=broken_create_parts)
    assert (await client.get(item_path, auth=alice)).json() == previous
    assert {blob.name async for blob in container.list_blobs()} == blobs_before
    listed = (await client.get(LEAGUES, auth=alice)).json()
    assert {item["id"] for item in listed} == {lid, created.json()["id"]}
    assert next(item for item in listed if item["id"] == lid)["role"] == "admin"

    replaced = await client.post(path, auth=alice, files=parts(config, "green"))
    assert replaced.status_code == 200
    assert replaced.json()["picture_url"] != previous["picture_url"]
    assert len({blob.name async for blob in container.list_blobs()} & blobs_before) == 1
    removed = await client.post(
        path, auth=alice, files=parts(config | {"description": None, "remove_picture": True})
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["picture_url"] is None
    assert removed.json()["description"] is None
    assert removed.json()["members"][0]["user_id"] == ids[0]
    assert (await client.get(previous["picture_url"], auth=alice)).status_code == 404
    assert len([blob async for blob in container.list_blobs()]) == 1
