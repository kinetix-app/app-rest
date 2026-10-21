"""Async Azure Blob Storage adapter shared by the API and explicit seed commands."""

import asyncio
import logging
from hashlib import sha256
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import BlobServiceClient
from fastapi import Depends, HTTPException, Request

from app.core.config import Settings

# Azure's INFO HTTP policy logs URL queries even when logging_enable=False.
# Give both SDK logging policies a disabled, dedicated logger instead.
_http_logger = logging.getLogger("kinetix.storage.http")
_http_logger.disabled = True


class BlobStorage:
    def __init__(self, settings: Settings):
        if not all(
            (
                settings.azure_storage_account_name,
                settings.azure_storage_account_url,
                settings.azure_storage_account_key,
            )
        ):
            raise ValueError("Configure Azure storage before using blob operations")
        self.settings = settings
        self.client = BlobServiceClient(
            settings.azure_storage_account_url,
            credential={
                "account_name": settings.azure_storage_account_name,
                "account_key": settings.azure_storage_account_key.get_secret_value(),
            },
            # Shared with pinned Azurite 3.37; newer SDK defaults can outpace the emulator.
            api_version="2026-06-06",
            retry_total=0,
            connection_timeout=settings.database_timeout_seconds,
            read_timeout=settings.azure_storage_timeout_seconds,
            logging_enable=False,
            logger=_http_logger,
        )
        self.container = self.client.get_container_client(settings.azure_storage_container)

    async def close(self) -> None:
        await self.client.close()

    async def check(self) -> None:
        # Check the configured account without requiring the seed container to exist yet.
        async with asyncio.timeout(self.settings.database_timeout_seconds):
            await self.client.get_account_information()

    async def ensure_container(self) -> None:
        async with asyncio.timeout(self.settings.azure_storage_timeout_seconds):
            public_access = "blob" if self.settings.azure_storage_local_public_read else None
            try:
                await self.container.create_container(public_access=public_access)
            except ResourceExistsError:
                properties = await self.container.get_container_properties()
                if public_access and properties.public_access != public_access:
                    raise ValueError(
                        "Existing container is private; configure local blob read access explicitly"
                    ) from None

    def media_url(self, name: str) -> str:
        assert self.settings.azure_storage_media_base_url is not None
        return (
            f"{self.settings.azure_storage_media_base_url.rstrip('/')}/"
            f"{self.settings.azure_storage_container}/{quote(name, safe='/')}"
        )

    async def upload(self, path: Path, name: str, digest: str, content_type: str) -> str:
        # Local disk reads and hashing must not block the event loop. Only one asset is
        # held in memory at a time; changed inputs invalidate the preflight manifest.
        def read() -> bytes:
            data = path.read_bytes()
            if sha256(data).hexdigest() != digest:
                raise ValueError("Asset changed after validation; rerun the seed command")
            return data

        data = await asyncio.to_thread(read)
        async with asyncio.timeout(self.settings.azure_storage_timeout_seconds):
            try:
                await self.container.upload_blob(
                    name,
                    data,
                    overwrite=False,
                    content_settings=ContentSettings(content_type=content_type),
                    metadata={"sha256": digest},
                )
            except ResourceExistsError:
                properties = await self.container.get_blob_client(name).get_blob_properties()
                if (
                    properties.size != len(data)
                    or properties.metadata.get("sha256") != digest
                    or properties.content_settings.content_type != content_type
                ):
                    raise ValueError(
                        "Existing seed blob differs from its content identity"
                    ) from None
        return self.media_url(name)


def get_blob_storage(request: Request) -> BlobStorage:
    storage = request.app.state.blob_storage
    if storage is None:
        raise HTTPException(status_code=503, detail="Blob storage is not configured")
    return storage


AzureStorage = Annotated[BlobStorage, Depends(get_blob_storage)]
