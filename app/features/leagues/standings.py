"""Private, timezone-aware round and general standings.

Versioned scoring rounds intentionally do not reinterpret legacy DATE rounds or
legacy integer totals. All score/result writers serialize on the league row.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.accounts.models import Profile
from app.features.leagues.errors import LeagueNotFound
from app.features.leagues.models import league, league_member
from app.features.leagues.presentation import member_picture_urls
from app.features.leagues.scoring import ensure_round
from app.features.leagues.scoring_models import league_daily_score, league_scoring_round


class LegacyLeagueUnavailable(Exception):
    """Legacy rows require an explicit product migration, not inferred timestamps."""


async def lock_league(session: AsyncSession, user_id: int, league_id: int):
    row = (
        (
            await session.execute(
                sa.select(league)
                .where(
                    league.c.id == league_id,
                    sa.exists().where(
                        league_member.c.league_id == league_id, league_member.c.user_id == user_id
                    ),
                )
                .with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LeagueNotFound
    if row["timezone"] is None:
        raise LegacyLeagueUnavailable
    return row


async def materialize_rounds(session: AsyncSession, row, now: datetime):
    """Retain empty/missed weeks, including the first partial week."""
    instant = row["created_at"]
    current = None
    while instant <= now:
        current = await ensure_round(session, row, instant)
        instant = current["end_at"]
    return current


def rank_totals(members, totals):
    ordered = sorted(
        members, key=lambda member: (-totals.get(member["user_id"], 0), member["user_id"])
    )
    result = []
    previous = None
    position = 0
    for index, member in enumerate(ordered, 1):
        total = totals.get(member["user_id"], 0)
        if total != previous:
            position = index
        result.append(
            {
                "user_id": member["user_id"],
                "display_name": member["display_name"],
                "score": str(total),
                "position": position,
            }
        )
        previous = total
    return result


async def round_standings(session: AsyncSession, round_row, viewer_id: int):
    members = (
        (
            await session.execute(
                sa.select(league_member.c.user_id, Profile.display_name)
                .outerjoin(Profile, Profile.user_id == league_member.c.user_id)
                .where(
                    league_member.c.league_id == round_row["league_id"],
                    league_member.c.joined_at < round_row["end_at"],
                )
            )
        )
        .mappings()
        .all()
    )
    daily = (
        (
            await session.execute(
                sa.select(league_daily_score)
                .where(league_daily_score.c.round_id == round_row["id"])
                .order_by(league_daily_score.c.local_day, league_daily_score.c.user_id)
            )
        )
        .mappings()
        .all()
    )
    totals = {}
    contributions = []
    for item in daily:
        uid = item["user_id"]
        totals[uid] = totals.get(uid, 0) + int(item["score"])
        entry = {
            "user_id": uid,
            "local_day": item["local_day"].isoformat(),
            "score": str(int(item["score"])),
        }
        if uid == viewer_id:
            entry["calculation"] = {
                "session_id": item["session_id"],
                "volume_kg_reps": str(item["volume_kg_reps"]),
                "duration_us": str(item["duration_us"]),
                "body_weight_kg": str(item["body_weight_kg"]),
                "formula_version": item["formula_version"],
            }
        contributions.append(entry)
    return {
        "id": round_row["id"],
        "start_at": round_row["start_at"],
        "end_at": round_row["end_at"],
        "standings": rank_totals(members, totals),
        "contributions": contributions,
    }


async def get_standings(session: AsyncSession, user_id: int, league_id: int):
    try:
        row = await lock_league(session, user_id, league_id)
        now = datetime.now(UTC)
        current = await materialize_rounds(session, row, now)
        rounds = (
            (
                await session.execute(
                    sa.select(league_scoring_round)
                    .where(league_scoring_round.c.league_id == league_id)
                    .order_by(league_scoring_round.c.start_at.desc())
                )
            )
            .mappings()
            .all()
        )
        details = [await round_standings(session, item, user_id) for item in rounds]
        members = (
            (
                await session.execute(
                    sa.select(league_member.c.user_id, Profile.display_name)
                    .outerjoin(Profile, Profile.user_id == league_member.c.user_id)
                    .where(league_member.c.league_id == league_id)
                )
            )
            .mappings()
            .all()
        )
        totals = {}
        for detail in details:
            for member in detail["standings"]:
                uid = member["user_id"]
                totals[uid] = totals.get(uid, 0) + int(member["score"])
        pictures = await member_picture_urls(session, league_id)
        for detail in details:
            for member in detail["standings"]:
                member["picture_url"] = pictures.get(member["user_id"])
        general = rank_totals(members, totals)
        for member in general:
            member["picture_url"] = pictures.get(member["user_id"])
        result = {
            "timezone": row["timezone"],
            "current_round_id": current["id"],
            "rounds": details,
            "general": general,
        }
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise
