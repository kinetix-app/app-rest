"""Picture URLs expose display identity without leaking storage names or private profiles."""

import sqlalchemy as sa
from pydantic import HttpUrl, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.models import Profile
from app.features.leagues.models import league_member

_http_url = TypeAdapter(HttpUrl)


def picture_url(league_id: int, name: str | None) -> str | None:
    revision = name.rsplit("/", 1)[-1].removesuffix(".jpg") if name else None
    return f"/api/v1/leagues/{league_id}/picture?v={revision}" if revision else None


def member_picture_url(
    league_id: int, user_id: int, blob_name: str | None, public_url: str | None
) -> str | None:
    if blob_name and blob_name.startswith(f"profiles/{user_id}/"):
        revision = blob_name.rsplit("/", 1)[-1].removesuffix(".jpg")
        return f"/api/v1/leagues/{league_id}/members/{user_id}/picture?v={revision}"
    if public_url:
        try:
            url = _http_url.validate_python(public_url)
        except ValidationError:
            return None
        if url.scheme == "https" and not url.username and not url.password:
            return str(url)
    return None


async def member_picture_urls(session: AsyncSession, league_id: int) -> dict[int, str | None]:
    rows = (
        await session.execute(
            sa.select(league_member.c.user_id, Profile.picture_blob_name, Profile.picture_url)
            .outerjoin(Profile, Profile.user_id == league_member.c.user_id)
            .where(league_member.c.league_id == league_id)
        )
    ).mappings()
    return {
        row.user_id: member_picture_url(
            league_id, row.user_id, row.picture_blob_name, row.picture_url
        )
        for row in rows
    }
