from io import BytesIO

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from app.core.config import Settings
from app.features.posts.media import MAX_POST_REQUEST_BYTES, normalize_post_image
from app.main import create_app


def test_post_images_keep_feed_resolution_without_metadata():
    output = BytesIO()
    exif = Image.Exif()
    exif[270] = "Private metadata"
    Image.new("RGB", (3000, 1500), "green").save(output, format="PNG", exif=exif)
    with Image.open(BytesIO(normalize_post_image(output.getvalue(), "image/png"))) as image:
        assert image.format == "JPEG"
        assert image.size == (1440, 720)
        assert not image.getexif()


@pytest.mark.anyio
async def test_post_upload_body_is_bounded_even_without_content_length(settings):
    app = create_app(settings)

    async def chunks():
        sent = 0
        while sent <= MAX_POST_REQUEST_BYTES:
            yield b"x" * 1024 * 1024
            sent += 1024 * 1024

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/posts",
            content=chunks(),
            headers={
                "Content-Type": "multipart/form-data; boundary=x",
                "Origin": "http://localhost:8081",
            },
        )
    assert response.status_code == 413
    assert response.json() == {"detail": "Post upload exceeds 25 MiB limit"}
    assert response.headers["access-control-allow-origin"] == "http://localhost:8081"


def test_post_container_must_differ_from_other_containers():
    with pytest.raises(ValidationError, match="post containers must be different"):
        Settings(
            _env_file=None,
            database_url="postgresql://user:test-only-password@127.0.0.1/test",
            azure_storage_post_container="profile-pictures",
        )
