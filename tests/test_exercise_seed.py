import json
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.storage.azure import BlobStorage
from app.features.training.seed import main
from app.features.training.seed_dataset import load_dataset


def test_export_preserves_metadata_and_every_media_variant(exercise_export):
    (item,) = load_dataset(exercise_export)
    assert len(item.assets) == 3
    assert item.default_image == "480p"
    assert item.data.database_values() == {
        "source": "ascend_edb_v2",
        "external_id": "exr_seed_test",
        "activity_type": "gym",
        "name": "Bench press",
        "overview": "A test movement",
        "body_parts": ["CHEST"],
        "equipments": ["BARBELL"],
        "exercise_types": ["STRENGTH"],
        "target_muscles": ["PECTORALIS"],
        "secondary_muscles": ["TRICEPS"],
        "instructions": ["Press"],
        "exercise_tips": ["Control"],
        "variations": ["Dumbbells"],
        "keywords": ["barbell"],
        "related_exercise_ids": ["exr_related"],
    }
    assert item.assets == load_dataset(exercise_export)[0].assets
    image = item.images["480p"]
    image.path.write_bytes(b"changed image")
    (changed,) = load_dataset(exercise_export)
    assert changed.images["480p"].blob_name != image.blob_name


@pytest.mark.parametrize(
    "problem", ["missing", "empty", "unmapped", "unindexed", "mismatch", "extra_field", "default"]
)
def test_invalid_export_fails_preflight(exercise_export, problem):
    folder = exercise_export / "bench-press"
    metadata_path = folder / "data.json"
    metadata = json.loads(metadata_path.read_text())
    if problem == "missing":
        (folder / "video.mp4").unlink()
    elif problem == "empty":
        (folder / "video.mp4").write_bytes(b"")
    elif problem == "unmapped":
        (folder / "images" / "1080p.jpg").write_bytes(b"unmapped")
    elif problem == "unindexed":
        (exercise_export / "index.json").write_text("{}")
    elif problem == "mismatch":
        metadata["exerciseId"] = "another_id"
    elif problem == "extra_field":
        metadata["unknownMedia"] = "do not discard"
    else:
        metadata["imageUrl"] = "https://provider.example/not-a-variant.jpg"
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises((ValueError, OSError)):
        load_dataset(exercise_export)


def test_export_rejects_path_escape(exercise_export, tmp_path):
    outside = tmp_path / "private.mp4"
    outside.write_bytes(b"outside export")
    video = exercise_export / "bench-press" / "video.mp4"
    video.unlink()
    video.symlink_to(outside)
    with pytest.raises(ValueError, match="inside the dataset"):
        load_dataset(exercise_export)


def test_validate_only_and_failed_cli_do_not_report_success(exercise_export, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["seed", "--dataset", str(exercise_export), "--validate-only"])
    monkeypatch.setattr("app.features.training.seed.Settings", lambda: pytest.fail("No services"))
    assert main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "validated",
        "exercises": 1,
        "media": 3,
    }
    (exercise_export / "bench-press" / "video.mp4").unlink()
    assert main() == 1
    output = capsys.readouterr()
    assert not output.out
    assert "Seed failed (FileNotFoundError)" in output.err


@pytest.mark.parametrize(
    "options",
    [
        {"azure_storage_account_url": "http://localhost:10000/account"},
        {"azure_storage_container": "invalid--name"},
        {
            "azure_storage_account_url": "https://example.test/?token=secret",
            "azure_storage_account_key": SecretStr("secret"),
            "azure_storage_media_base_url": "https://example.test",
        },
        {
            "app_env": "production",
            "clerk_issuer": "https://example.clerk.accounts.dev",
            "clerk_secret_key": SecretStr("secret"),
            "azure_storage_local_public_read": True,
        },
    ],
)
def test_storage_configuration_rejects_partial_unsafe_or_public_production_settings(options):
    settings_values = {"_env_file": None, "postgres_password": SecretStr("test"), **options}
    with pytest.raises(ValidationError):
        Settings(**settings_values)


@pytest.mark.anyio
async def test_storage_lifecycle_readiness_and_failure_recovery(settings, monkeypatch):
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    storage = AsyncMock()
    settings.azure_storage_account_url = "http://storage.example"
    monkeypatch.setattr("app.main.BlobStorage", lambda _: storage)
    # Isolate storage readiness from the deliberately unavailable test DB.
    app = create_app(settings)
    # A real connection cannot be made to port 1; replace only the engine connection context.
    from unittest.mock import MagicMock

    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=AsyncMock())
    connection.__aexit__ = AsyncMock()
    async with LifespanManager(app):
        monkeypatch.setattr(type(app.state.engine), "connect", lambda _: connection)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/health/ready")).status_code == 200
            storage.check.side_effect = TimeoutError()
            assert (await client.get("/health/ready")).status_code == 503
            assert (await client.get("/health/live")).status_code == 200
            storage.check.side_effect = None
            assert (await client.get("/health/ready")).status_code == 200
    storage.close.assert_awaited_once()


@pytest.mark.anyio
async def test_mutated_asset_is_not_uploaded(settings, exercise_export):
    settings.azure_storage_account_url = "http://localhost:10000/account"
    settings.azure_storage_account_name = "account"
    settings.azure_storage_account_key = SecretStr("a2V5")
    storage = BlobStorage(settings)
    storage.container = AsyncMock()
    (item,) = load_dataset(exercise_export)
    item.video.path.write_bytes(b"changed")
    try:
        with pytest.raises(ValueError, match="changed after validation"):
            await storage.upload(
                item.video.path, item.video.blob_name, item.video.digest, item.video.content_type
            )
        storage.container.upload_blob.assert_not_awaited()
    finally:
        await storage.close()


@pytest.mark.anyio
async def test_explicit_account_name_supports_compose_hostname(settings):
    settings.azure_storage_account_name = "kinetixlocal"
    settings.azure_storage_account_url = "http://azurite:10000/kinetixlocal"
    settings.azure_storage_account_key = SecretStr("a2V5")
    storage = BlobStorage(settings)
    try:
        assert storage.client.account_name == "kinetixlocal"
        assert storage.container.url == "http://azurite:10000/kinetixlocal/exercises"
    finally:
        await storage.close()
