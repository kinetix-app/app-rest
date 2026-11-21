"""Friend requests, people search and friends-only post visibility."""

import pytest
import sqlalchemy as sa

from app.features.accounts.models import Profile, User
from app.features.social.models import friendship
from tests.integration.test_posts import POSTS, posts_api  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
FRIENDS = "/api/v1/friends"
PEOPLE = "/api/v1/people"


@pytest.fixture
async def social(posts_api):  # noqa: F811
    api = posts_api
    async with api.sessions.begin() as session:
        for user_id, name in (
            (api.alice_id, "Alice"),
            (api.bob_id, "Bob"),
            (api.carol_id, "Carol"),
        ):
            await session.execute(
                sa.update(Profile).where(Profile.user_id == user_id).values(display_name=name)
            )
    return api


async def request(api, auth, user_id):
    return await api.client.post(f"{FRIENDS}/requests", auth=auth, json={"user_id": user_id})


async def relationship(api, auth, user_id):
    return (await api.client.get(f"{PEOPLE}/{user_id}", auth=auth)).json()["relationship"]


async def test_search_finds_named_active_people_with_their_relationship(social):
    api = social
    found = (await api.client.get(f"{PEOPLE}?q=bo", auth=api.alice)).json()["items"]
    assert found == [
        {"id": api.bob_id, "display_name": "Bob", "has_picture": False, "relationship": "none"}
    ]
    assert (await api.client.get(f"{PEOPLE}?q=al", auth=api.alice)).json()["items"] == []
    assert (await api.client.get(f"{PEOPLE}?q=%25%25", auth=api.alice)).json()["items"] == []
    for query in ("q=b", "q=%20%20b", ""):
        assert (await api.client.get(f"{PEOPLE}?{query}", auth=api.alice)).status_code == 422
    async with api.sessions.begin() as session:
        await session.execute(
            sa.update(Profile).where(Profile.user_id == api.carol_id).values(display_name=None)
        )
    assert (await api.client.get(f"{PEOPLE}?q=car", auth=api.alice)).json()["items"] == []
    assert (await api.client.get(f"{PEOPLE}/{api.carol_id}", auth=api.alice)).status_code == 404
    me = (await api.client.get(f"{PEOPLE}/{api.alice_id}", auth=api.alice)).json()
    assert (me["relationship"], me["friend_count"]) == ("self", 0)


async def test_request_accept_lists_and_idempotent_retries(social):
    api = social
    for _ in range(2):
        response = await request(api, api.alice, api.bob_id)
        assert response.status_code == 200, response.text
        assert response.json() == {"user_id": api.bob_id, "relationship": "outgoing"}
    assert await relationship(api, api.bob, api.alice_id) == "incoming"
    incoming = (await api.client.get(f"{FRIENDS}/requests", auth=api.bob)).json()
    assert [item["user"]["display_name"] for item in incoming["incoming"]] == ["Alice"]
    assert incoming["outgoing"] == []
    outgoing = (await api.client.get(f"{FRIENDS}/requests", auth=api.alice)).json()
    assert [item["user"]["id"] for item in outgoing["outgoing"]] == [api.bob_id]
    assert (await api.client.get(FRIENDS, auth=api.alice)).json()["items"] == []

    path = f"{FRIENDS}/requests/{api.alice_id}/accept"
    for _ in range(2):
        accepted = await api.client.post(path, auth=api.bob)
        assert accepted.json() == {"user_id": api.alice_id, "relationship": "friends"}
    # The requester cannot accept their own outgoing request.
    assert (
        await api.client.post(f"{FRIENDS}/requests/{api.carol_id}/accept", auth=api.alice)
    ).status_code == 404
    for auth, other, name in ((api.alice, api.bob_id, "Bob"), (api.bob, api.alice_id, "Alice")):
        friends = (await api.client.get(FRIENDS, auth=auth)).json()["items"]
        assert [(item["user"]["id"], item["user"]["display_name"]) for item in friends] == [
            (other, name)
        ]
        assert friends[0]["since"] is not None
    profile = (await api.client.get(f"{PEOPLE}/{api.bob_id}", auth=api.carol)).json()
    assert (profile["relationship"], profile["friend_count"]) == ("none", 1)
    assert (await api.client.get(f"{FRIENDS}/requests", auth=api.bob)).json()["incoming"] == []


async def test_requesting_back_accepts_and_removal_covers_every_state(social):
    api = social
    await request(api, api.carol, api.bob_id)
    back = await request(api, api.bob, api.carol_id)
    assert back.json()["relationship"] == "friends"
    async with api.sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(friendship)) == 1

    # Unfriend, then retries are harmless.
    for _ in range(2):
        assert (
            await api.client.delete(f"{FRIENDS}/{api.carol_id}", auth=api.bob)
        ).status_code == 204
    assert await relationship(api, api.carol, api.bob_id) == "none"
    # Decline an incoming request.
    await request(api, api.carol, api.alice_id)
    assert (await api.client.delete(f"{FRIENDS}/{api.carol_id}", auth=api.alice)).status_code == 204
    assert (await api.client.get(f"{FRIENDS}/requests", auth=api.carol)).json()["outgoing"] == []
    # Cancel an outgoing request.
    await request(api, api.alice, api.carol_id)
    assert (await api.client.delete(f"{FRIENDS}/{api.carol_id}", auth=api.alice)).status_code == 204
    assert await relationship(api, api.carol, api.alice_id) == "none"


async def test_invalid_targets_and_blocked_people(social):
    api = social
    assert (await request(api, api.alice, api.alice_id)).status_code == 422
    assert (await request(api, api.alice, 999_999)).status_code == 404
    for body in ({}, {"user_id": "2"}, {"user_id": 0}, {"user_id": 1, "x": 1}):
        response = await api.client.post(f"{FRIENDS}/requests", auth=api.alice, json=body)
        assert response.status_code == 422, body
    await request(api, api.alice, api.bob_id)
    await api.client.post(f"{FRIENDS}/requests/{api.alice_id}/accept", auth=api.bob)
    async with api.sessions.begin() as session:
        await session.execute(sa.update(User).where(User.id == api.bob_id).values(status="blocked"))
    assert (await api.client.get(f"{PEOPLE}?q=bob", auth=api.alice)).json()["items"] == []
    assert (await api.client.get(f"{PEOPLE}/{api.bob_id}", auth=api.alice)).status_code == 404
    assert (await api.client.get(FRIENDS, auth=api.alice)).json()["items"] == []
    assert (await request(api, api.carol, api.bob_id)).status_code == 404
    assert (await api.client.get(FRIENDS)).status_code == 401


async def test_friends_only_posts_and_friends_feed(social):
    api = social
    await request(api, api.alice, api.bob_id)
    await api.client.post(f"{FRIENDS}/requests/{api.alice_id}/accept", auth=api.bob)
    private_circle = await api.client.post(
        POSTS, auth=api.alice, data={"text": "Friends only", "visibility": "FRIENDS"}
    )
    assert private_circle.status_code == 201, private_circle.text
    friends_post = private_circle.json()
    assert friends_post["visibility"] == "FRIENDS"
    public = (await api.client.post(POSTS, auth=api.alice, data={"text": "Public"})).json()
    carol_post = (await api.client.post(POSTS, auth=api.carol, data={"text": "Carol"})).json()
    path = f"{POSTS}/{friends_post['id']}"

    assert (await api.client.get(path, auth=api.bob)).status_code == 200
    assert (await api.client.get(path, auth=api.carol)).status_code == 404
    assert (await api.client.put(f"{path}/like", auth=api.carol)).status_code == 404

    def ids(response):
        return [item["id"] for item in response.json()["items"]]

    everyone = await api.client.get(POSTS, auth=api.bob)
    assert ids(everyone) == [carol_post["id"], public["id"], friends_post["id"]]
    friends = await api.client.get(f"{POSTS}?scope=friends", auth=api.bob)
    assert ids(friends) == [public["id"], friends_post["id"]]
    assert ids(await api.client.get(f"{POSTS}?scope=friends", auth=api.carol)) == [carol_post["id"]]
    assert ids(await api.client.get(POSTS, auth=api.carol)) == [carol_post["id"], public["id"]]
    assert (await api.client.get(f"{POSTS}?scope=other", auth=api.bob)).status_code == 422

    # Unfriending removes access to friends-only posts immediately.
    await api.client.delete(f"{FRIENDS}/{api.alice_id}", auth=api.bob)
    assert (await api.client.get(path, auth=api.bob)).status_code == 404


async def test_profile_pictures_are_visible_to_any_signed_in_person(social):
    api = social
    name = f"profiles/{api.bob_id}/photo.jpg"
    api.storage.blobs[name] = b"jpeg-bytes"
    async with api.sessions.begin() as session:
        await session.execute(
            sa.update(Profile)
            .where(Profile.user_id == api.bob_id)
            .values(picture_blob_name=name, picture_url="/api/v1/me/profile/picture")
        )
    # Carol is not Bob's friend and can still tell him apart by his photo.
    picture = await api.client.get(f"{PEOPLE}/{api.bob_id}/picture", auth=api.carol)
    assert picture.status_code == 200
    assert picture.content == b"jpeg-bytes"
    assert picture.headers["content-type"] == "image/jpeg"
    assert picture.headers["cache-control"] == "private, max-age=300"
    found = (await api.client.get(f"{PEOPLE}?q=bob", auth=api.carol)).json()["items"]
    assert found[0]["has_picture"] is True
    assert (await api.client.get(f"{PEOPLE}/{api.bob_id}", auth=api.carol)).json()["has_picture"]
    assert (await api.client.get(f"{PEOPLE}/{api.alice_id}", auth=api.alice)).json()[
        "has_picture"
    ] is False

    post = (await api.client.post(POSTS, auth=api.bob, data={"text": "Hi"})).json()
    assert post["author"]["has_picture"] is True
    comment = await api.client.post(
        f"{POSTS}/{post['id']}/comments", auth=api.bob, json={"comment": "Me again"}
    )
    assert comment.json()["author"]["has_picture"] is True

    assert (
        await api.client.get(f"{PEOPLE}/{api.alice_id}/picture", auth=api.bob)
    ).status_code == 404
    assert (await api.client.get(f"{PEOPLE}/999999/picture", auth=api.bob)).status_code == 404
    assert (await api.client.get(f"{PEOPLE}/{api.bob_id}/picture")).status_code == 401
    async with api.sessions.begin() as session:
        await session.execute(sa.update(User).where(User.id == api.bob_id).values(status="blocked"))
    assert (
        await api.client.get(f"{PEOPLE}/{api.bob_id}/picture", auth=api.carol)
    ).status_code == 404
