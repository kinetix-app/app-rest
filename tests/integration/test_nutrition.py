"""Nutrition API persistence, totals, ownership and deletion behaviour."""

from datetime import date
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
from app.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def nutrition_api(integration_url):
    """A migrated isolated schema with two authenticated local accounts."""
    schema = "nutrition_" + uuid4().hex
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
            basic_auth_users={
                "alice": SecretStr("password"),
                "bob": SecretStr("password"),
            },
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
                yield SimpleNamespace(client=client, alice=alice, bob=bob)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


def food_payload(name="Oats", **overrides):
    return {
        "name": name,
        "brand": "Kinetix",
        "calories": "370.00",
        "protein": "13.00",
        "carbohydrates": "60.00",
        "fats": "7.00",
        **overrides,
    }


def decimal(value):
    return Decimal(str(value))


async def create_food(api, name="Oats", **overrides):
    response = await api.client.post(
        "/api/v1/foods", auth=api.alice, json=food_payload(name, **overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_recipe(api, food_id, name="Breakfast bowl", servings=2):
    response = await api.client.post(
        "/api/v1/recipes",
        auth=api.alice,
        json={
            "name": name,
            "servings": servings,
            "ingredients": [{"food_id": food_id, "quantity_grams": "100.00"}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_food_crud_search_validation_and_isolation(nutrition_api):
    api = nutrition_api
    created = await create_food(api, "Apple pie", barcode="123")
    food_id = created["id"]
    assert created["name"] == "Apple pie"
    assert created["user_id"] > 0

    searched = await api.client.get("/api/v1/foods", auth=api.alice, params={"name": "APPLE"})
    assert searched.status_code == 200
    assert [item["id"] for item in searched.json()] == [food_id]
    assert (
        await api.client.get("/api/v1/foods", auth=api.bob, params={"name": "apple"})
    ).json() == []
    assert (await api.client.get(f"/api/v1/foods/{food_id}", auth=api.bob)).status_code == 404

    updated = await api.client.patch(
        f"/api/v1/foods/{food_id}", auth=api.alice, json={"brand": "Updated"}
    )
    assert updated.status_code == 200
    assert updated.json()["brand"] == "Updated"
    assert (
        await api.client.patch(f"/api/v1/foods/{food_id}", auth=api.alice, json={"name": None})
    ).status_code == 422
    assert (await api.client.get(f"/api/v1/foods/{food_id}", auth=api.alice)).json()[
        "brand"
    ] == "Updated"

    invalid = await api.client.post(
        "/api/v1/foods", auth=api.alice, json=food_payload("Invalid", calories="-1")
    )
    assert invalid.status_code == 422
    assert (await api.client.delete(f"/api/v1/foods/{food_id}", auth=api.bob)).status_code == 404
    assert (await api.client.delete(f"/api/v1/foods/{food_id}", auth=api.alice)).status_code == 204
    assert (await api.client.get(f"/api/v1/foods/{food_id}", auth=api.alice)).status_code == 404


async def test_recipes_calculate_macros_and_protect_owned_foods(nutrition_api):
    api = nutrition_api
    food = await create_food(api, "Rice", calories="360", protein="7", carbohydrates="80", fats="1")
    recipe = await create_recipe(api, food["id"])
    assert recipe["name"] == "Breakfast bowl"
    assert recipe["servings"] == 2
    assert decimal(recipe["calories"]) == Decimal("180")
    assert decimal(recipe["protein"]) == Decimal("3.5")
    assert decimal(recipe["carbohydrates"]) == Decimal("40")
    assert decimal(recipe["fats"]) == Decimal("0.5")
    assert (await api.client.get("/api/v1/recipes", auth=api.bob)).json() == []
    assert (
        await api.client.delete(f"/api/v1/foods/{food['id']}", auth=api.alice)
    ).status_code == 409
    assert (
        await api.client.delete(f"/api/v1/recipes/{recipe['id']}", auth=api.bob)
    ).status_code == 404
    assert (
        await api.client.delete(f"/api/v1/recipes/{recipe['id']}", auth=api.alice)
    ).status_code == 204
    assert (
        await api.client.delete(f"/api/v1/foods/{food['id']}", auth=api.alice)
    ).status_code == 204

    unknown = await api.client.post(
        "/api/v1/recipes",
        auth=api.alice,
        json={"name": "Missing", "ingredients": [{"food_id": 999999, "quantity_grams": "10"}]},
    )
    assert unknown.status_code == 404


async def test_diary_records_food_and_recipe_totals_and_enforces_ownership(nutrition_api):
    api = nutrition_api
    food = await create_food(
        api, "Yogurt", calories="100", protein="10", carbohydrates="5", fats="4"
    )
    recipe = await create_recipe(api, food["id"], servings=2)
    day = date(2026, 10, 24).isoformat()

    food_item = await api.client.post(
        "/api/v1/nutrition/meal-items",
        auth=api.alice,
        json={
            "date": day,
            "meal_type": "breakfast",
            "food_id": food["id"],
            "quantity_grams": "150",
        },
    )
    assert food_item.status_code == 201, food_item.text
    assert decimal(food_item.json()["calories"]) == Decimal("150")
    recipe_item = await api.client.post(
        "/api/v1/nutrition/recipe-items",
        auth=api.alice,
        json={"date": day, "meal_type": "dinner", "recipe_id": recipe["id"], "servings": "1.5"},
    )
    assert recipe_item.status_code == 201, recipe_item.text
    assert decimal(recipe_item.json()["calories"]) == Decimal("75")

    recorded = await api.client.get(f"/api/v1/nutrition/days/{day}", auth=api.alice)
    assert recorded.status_code == 200
    body = recorded.json()
    assert decimal(body["calories"]) == Decimal("225")
    assert decimal(body["protein"]) == Decimal("22.5")
    assert decimal(body["carbohydrates"]) == Decimal("11.25")
    assert decimal(body["fats"]) == Decimal("9")
    assert len(body["items"]) == 2
    assert (await api.client.get(f"/api/v1/nutrition/days/{day}", auth=api.bob)).json()[
        "items"
    ] == []
    assert (
        await api.client.delete(
            f"/api/v1/nutrition/meal-items/{food_item.json()['id']}", auth=api.bob
        )
    ).status_code == 404
    assert (
        await api.client.delete(
            f"/api/v1/nutrition/meal-items/{food_item.json()['id']}", auth=api.alice
        )
    ).status_code == 204
    assert (
        await api.client.delete(f"/api/v1/recipes/{recipe['id']}", auth=api.alice)
    ).status_code == 409
    assert (
        await api.client.delete(f"/api/v1/foods/{food['id']}", auth=api.alice)
    ).status_code == 409
    assert (
        await api.client.post(
            "/api/v1/nutrition/meal-items",
            auth=api.bob,
            json={"date": day, "meal_type": "lunch", "food_id": food["id"], "quantity_grams": "20"},
        )
    ).status_code == 404


async def test_nutrition_goal_is_single_per_user_and_can_be_updated(nutrition_api):
    api = nutrition_api
    path = "/api/v1/nutrition-goals"
    payload = {"calories": "2200", "protein": "150", "carbohydrates": "250", "fats": "70"}
    assert (await api.client.get(f"{path}/me", auth=api.alice)).status_code == 404
    created = await api.client.post(path, auth=api.alice, json=payload)
    assert created.status_code == 201, created.text
    assert decimal(created.json()["calories"]) == Decimal("2200")
    assert (await api.client.post(path, auth=api.alice, json=payload)).status_code == 409
    changed = await api.client.patch(
        f"{path}/me", auth=api.alice, json={**payload, "calories": "2300"}
    )
    assert changed.status_code == 200
    assert decimal(changed.json()["calories"]) == Decimal("2300")
    assert (await api.client.get(f"{path}/me", auth=api.bob)).status_code == 404
    assert (await api.client.patch(f"{path}/me", auth=api.bob, json=payload)).status_code == 404
    assert (
        await api.client.post(path, auth=api.alice, json={**payload, "calories": 0})
    ).status_code == 422
