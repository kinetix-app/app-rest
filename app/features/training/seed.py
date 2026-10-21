"""Explicit exercise/media seed command; never runs at application startup."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from azure.core.exceptions import AzureError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.storage.azure import BlobStorage
from app.db.session import create_database_engine
from app.features.training.models import exercise
from app.features.training.seed_dataset import SeedExercise, load_dataset


async def seed_exercises(
    dataset: list[SeedExercise],
    storage: BlobStorage,
    sessions: async_sessionmaker[AsyncSession],
) -> dict[str, int]:
    # Fail early on an unavailable/unmigrated database before writing any blobs.
    async with sessions() as session:
        await session.execute(sa.select(exercise).limit(0))
        await session.rollback()
    await storage.ensure_container()
    rows = []
    media_count = 0
    for item in dataset:
        urls = {}
        for asset in item.assets:
            urls[asset.blob_name] = await storage.upload(
                asset.path, asset.blob_name, asset.digest, asset.content_type
            )
            media_count += 1
        images = {key: urls[asset.blob_name] for key, asset in item.images.items()}
        rows.append(
            item.data.database_values()
            | {
                "image_urls": images,
                "image_url": images[item.default_image],
                "video_url": urls[item.video.blob_name],
                "imported_at": datetime.now(UTC),
            }
        )
    # A single catalogue transaction follows all storage operations: failures leave
    # existing records intact. Content-addressed unreferenced blobs are safe to retry.
    async with sessions() as session:
        async with session.begin():
            for values in rows:
                statement = insert(exercise).values(**values)
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[exercise.c.source, exercise.c.external_id],
                        index_where=sa.text(
                            "user_id IS NULL AND external_id IS NOT NULL AND source <> 'manual'"
                        ),
                        set_={
                            name: statement.excluded[name]
                            for name in values
                            if name not in ("source", "external_id")
                        },
                    )
                )
    return {"exercises": len(rows), "media": media_count}


async def run(dataset_path: Path, *, validate_only: bool = False) -> dict[str, int]:
    dataset = await asyncio.to_thread(load_dataset, dataset_path)
    if validate_only:
        return {"exercises": len(dataset), "media": sum(len(item.assets) for item in dataset)}
    settings = Settings()
    storage = BlobStorage(settings)
    engine = create_database_engine(settings)
    try:
        return await seed_exercises(
            dataset, storage, async_sessionmaker(engine, expire_on_commit=False)
        )
    finally:
        try:
            await storage.close()
        finally:
            await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, required=True, help="Local exercices export directory"
    )
    parser.add_argument(
        "--validate-only", action="store_true", help="Validate inputs without I/O to services"
    )
    args = parser.parse_args()
    try:
        counts = asyncio.run(run(args.dataset, validate_only=args.validate_only))
    except (AzureError, SQLAlchemyError, OSError, ValueError) as error:
        # SDK/DB exception text can contain signed URLs, credentials or SQL values.
        print(
            f"Seed failed ({type(error).__name__}). Check dataset index/metadata/assets, "
            "Azure environment settings and service health; apply migrations before seeding. "
            "No success was recorded. Correct the input/service and rerun safely.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"status": "validated" if args.validate_only else "seeded", **counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
