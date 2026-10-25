from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.features.accounts.errors import InvalidPicture, PictureTooLarge, UnsupportedPicture
from app.features.accounts.pictures import MAX_PICTURE_BYTES, normalize_picture
from app.main import create_app


def picture_bytes(format="PNG", size=(24, 32)):
    output = BytesIO()
    image = Image.new("RGB", size, "red")
    exif = Image.Exif()
    exif[270] = "Private metadata"
    image.save(output, format=format, exif=exif)
    return output.getvalue()


@pytest.mark.parametrize(
    "format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
def test_normalization_strips_metadata_and_resizes(format, mime):
    normalized = normalize_picture(picture_bytes(format, (1200, 600)), mime)
    with Image.open(BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.size == (1024, 512)
        assert not image.getexif()
        assert "icc_profile" not in image.info


@pytest.mark.parametrize(
    "data,mime,error",
    [
        (b"bad", "image/png", InvalidPicture),
        (b"bad", "image/gif", UnsupportedPicture),
        (picture_bytes(), "image/jpeg", UnsupportedPicture),
        (b"a" * (MAX_PICTURE_BYTES + 1), "image/png", PictureTooLarge),
    ],
    ids=["corrupt", "unsupported", "format-mismatch", "oversized"],
)
def test_reject_invalid_images(data, mime, error):
    with pytest.raises(error):
        normalize_picture(data, mime)


def test_large_decoded_image_is_rejected():
    with pytest.raises(InvalidPicture):
        normalize_picture(picture_bytes(size=(4001, 4000)), "image/png")


@pytest.mark.anyio
async def test_multipart_entire_body_is_bounded_even_without_content_length(settings):
    app = create_app(settings)

    async def chunks():
        for _ in range(7):
            yield b"x" * 1024 * 1024

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/me/profile/picture",
            content=chunks(),
            headers={
                "Content-Type": "multipart/form-data; boundary=x",
                "Origin": "http://localhost:8081",
            },
        )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://localhost:8081"
