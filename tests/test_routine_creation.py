"""Transport bounds permit the full routine contract without unbounded uploads."""

import json

import httpx
import pytest
from fastapi import FastAPI, Request

from app.features.accounts.upload_limit import ProfileUploadLimit
from app.features.training.creation import MAX_ROUTINE_CONTENT_BYTES, parse_create


@pytest.fixture
def create_transport():
    app = FastAPI()
    app.add_middleware(ProfileUploadLimit)

    @app.post("/api/v1/routines")
    async def create(request: Request):
        try:
            data, file = await parse_create(request)
            return {
                "slots": len(data.exercises),
                "sets": sum(len(slot.sets or []) for slot in data.exercises),
                "image": file is not None,
            }
        finally:
            await request.close()

    return app


@pytest.mark.anyio
async def test_multipart_accepts_maximum_planned_set_content(create_transport):
    slot = {
        "exercise_id": 2**63 - 1,
        "sets": [{"reps": 2147483647, "weight": {"value": "999999.99", "unit": "kg"}}] * 100,
    }
    content = json.dumps({"name": "n" * 150, "notes": "文" * 1000, "exercises": [slot] * 500})
    assert 1024 * 1024 < len(content.encode()) < MAX_ROUTINE_CONTENT_BYTES
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_transport), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/routines", files={"content": (None, content)})
    assert response.status_code == 200, response.text
    assert response.json() == {"slots": 500, "sets": 50000, "image": False}


@pytest.mark.anyio
async def test_content_has_independent_size_limit(create_transport):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_transport), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/routines", files={"content": (None, "x" * (MAX_ROUTINE_CONTENT_BYTES + 1))}
        )
    assert response.status_code == 413


@pytest.mark.anyio
async def test_multipart_total_is_bounded_without_content_length(create_transport):
    async def chunks():
        for _ in range(22):
            yield b"x" * 1024 * 1024

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_transport), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/routines",
            content=chunks(),
            headers={"Content-Type": "multipart/form-data; boundary=x"},
        )
    assert response.status_code == 413
