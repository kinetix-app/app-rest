"""Preserve active scoring and result state when retiring the legacy layout."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.features.leagues.scoring import credit_completed_session
from tests.integration.test_migrations import migrate

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_populated_league_scoring_upgrade_and_downgrade(integration_url):
    engine = create_async_engine(integration_url)
    schema = "league_consolidation_" + uuid4().hex
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await conn.run_sync(lambda db: migrate(db, "20261117_05"))

                async def execute(sql, **values):
                    return await conn.execute(text(sql), values)

                async def rows(sql):
                    return (await execute(sql)).all()

                owner = (
                    await execute("INSERT INTO users DEFAULT VALUES RETURNING id")
                ).scalar_one()
                peer = (await execute("INSERT INTO users DEFAULT VALUES RETURNING id")).scalar_one()
                league_id = (
                    await execute(
                        "INSERT INTO league (name, timezone, created_by) "
                        "VALUES ('Active', 'UTC', :owner) RETURNING id",
                        owner=owner,
                    )
                ).scalar_one()
                await execute(
                    """
                    INSERT INTO league_member (league_id, user_id, role, joined_at)
                    VALUES (:league, :owner, 'admin', '2026-11-02T00:00:00Z'),
                           (:league, :peer, 'member', '2026-11-03T00:00:00Z')
                    """,
                    league=league_id,
                    owner=owner,
                    peer=peer,
                )
                await execute(
                    """
                    INSERT INTO league_round (id, league_id, start_date, end_date)
                    VALUES (55, :league, '2020-01-06', '2020-01-12')
                    """,
                    league=league_id,
                )
                await execute(
                    "INSERT INTO league_score (league_id, user_id, round_id, score) "
                    "VALUES (:league, :owner, 55, 1)",
                    league=league_id,
                    owner=owner,
                )
                await execute(
                    """
                    INSERT INTO league_scoring_round (id, league_id, start_at, end_at)
                    VALUES (55, :league, '2026-11-02T00:00:00Z', '2026-11-09T00:00:00Z'),
                           (56, :league, '2026-11-09T00:00:00Z', '2026-11-16T00:00:00Z')
                    """,
                    league=league_id,
                )
                await execute("SELECT setval(pg_get_serial_sequence('league_round','id'), 900)")
                await execute(
                    "SELECT setval(pg_get_serial_sequence('league_scoring_round','id'), 800)"
                )
                sessions = await execute(
                    """
                    INSERT INTO training_session
                      (user_id, activity_type, started_at, ended_at, notes)
                    VALUES (:owner, 'gym', '2026-11-04T12:00:00Z',
                            '2026-11-04T13:00:00.123456Z', 'Preserved'),
                           (:owner, 'cycling', '2026-11-05T12:00:00Z',
                            '2026-11-05T13:00:00Z', NULL),
                           (:peer, 'gym', '2026-11-06T12:00:00Z', NULL, 'Unprocessed')
                    RETURNING id
                    """,
                    owner=owner,
                    peer=peer,
                )
                credited, no_credit, unprocessed = sessions.scalars().all()
                await execute(
                    """
                    INSERT INTO league_session_calculation
                        (session_id, user_id, score, volume_kg_reps, duration_us,
                         body_weight_kg, formula_version)
                    VALUES (:credited, :owner, 9007199254740993, 812.123456,
                            3600123456, 81.654321, 'migration-v1'),
                           (:no_credit, :owner, NULL, 0, 3600000000, NULL, 'migration-v1')
                    """,
                    credited=credited,
                    no_credit=no_credit,
                    owner=owner,
                )
                await execute(
                    """
                    INSERT INTO league_daily_score
                        (league_id, user_id, local_day, round_id, session_id, score,
                         volume_kg_reps, duration_us, body_weight_kg, ended_at, formula_version)
                    SELECT :league, s.user_id, '2026-11-04', 55, s.session_id, s.score,
                           s.volume_kg_reps, s.duration_us, s.body_weight_kg,
                           t.ended_at, s.formula_version
                    FROM league_session_calculation s JOIN training_session t ON t.id=s.session_id
                    WHERE s.session_id=:credited
                    """,
                    league=league_id,
                    credited=credited,
                )
                result_id = (
                    await execute(
                        """
                        INSERT INTO league_result (league_id, round_id, snapshot)
                        VALUES (:league, 55, '{"standings":[{"score":"9007199254740993"}]}'::jsonb)
                        RETURNING id
                        """,
                        league=league_id,
                    )
                ).scalar_one()
                await execute(
                    "UPDATE league_member SET last_seen_result_id=:result "
                    "WHERE league_id=:league AND user_id=:peer",
                    result=result_id,
                    league=league_id,
                    peer=peer,
                )
                score_fields = (
                    "league_id, user_id, local_day, round_id, session_id, score, "
                    "volume_kg_reps, duration_us, body_weight_kg, ended_at, formula_version"
                )
                round_fields = "id, league_id, start_at, end_at"
                old_rounds = await rows(
                    f"SELECT {round_fields} FROM league_scoring_round ORDER BY id"
                )
                old_scores = await rows(f"SELECT {score_fields} FROM league_daily_score")
                old_snapshots = await rows("""
                    SELECT session_id, user_id, score, volume_kg_reps, duration_us,
                           body_weight_kg, formula_version
                    FROM league_session_calculation ORDER BY session_id
                """)
                saved_results = await rows("SELECT * FROM league_result")
                memberships = await rows("SELECT * FROM league_member ORDER BY user_id")
                history = await rows(
                    "SELECT id, notes, started_at, ended_at FROM training_session ORDER BY id"
                )

                await conn.run_sync(lambda db: migrate(db, "head"))
                assert (
                    await rows(f"SELECT {round_fields} FROM league_round ORDER BY id") == old_rounds
                )
                assert await rows(f"SELECT {score_fields} FROM league_score") == old_scores
                async with AsyncSession(bind=conn) as league_session:
                    await credit_completed_session(league_session, owner, no_credit)
                    await credit_completed_session(league_session, owner, credited)
                assert (
                    await rows("""
                    SELECT id, user_id, league_score, league_volume_kg_reps, league_duration_us,
                           league_body_weight_kg, league_formula_version
                    FROM training_session WHERE league_formula_version IS NOT NULL ORDER BY id
                """)
                    == old_snapshots
                )
                assert await rows("SELECT * FROM league_result") == saved_results
                assert await rows("SELECT * FROM league_member ORDER BY user_id") == memberships
                assert (
                    await rows(
                        "SELECT id, notes, started_at, ended_at FROM training_session ORDER BY id"
                    )
                    == history
                )
                assert (
                    await execute(
                        "SELECT league_formula_version FROM training_session WHERE id=:id",
                        id=unprocessed,
                    )
                ).scalar_one() is None
                assert await rows("""
                    SELECT to_regclass('league_daily_score'),
                           to_regclass('league_scoring_round'),
                           to_regclass('league_session_calculation')
                """) == [(None, None, None)]

                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await execute(
                            f"INSERT INTO league_score ({score_fields}) "
                            "SELECT league_id, :peer, local_day, round_id, session_id, score,"
                            " volume_kg_reps, duration_us, body_weight_kg, ended_at, "
                            "formula_version FROM league_score",
                            peer=peer,
                        )

                next_round = (
                    await execute(
                        """
                        INSERT INTO league_round (league_id, start_at, end_at)
                        VALUES (:league, '2026-11-16T00:00:00Z', '2026-11-23T00:00:00Z')
                        RETURNING id
                        """,
                        league=league_id,
                    )
                ).scalar_one()
                assert next_round > 900
                await execute("DELETE FROM league_round WHERE id=:id", id=next_round)
                await conn.run_sync(lambda db: migrate(db, "20261117_05", downgrade=True))
                assert (
                    await rows(f"SELECT {round_fields} FROM league_scoring_round ORDER BY id")
                    == old_rounds
                )
                assert await rows(f"SELECT {score_fields} FROM league_daily_score") == old_scores
                assert await rows("SELECT * FROM league_result") == saved_results
                assert await rows("SELECT * FROM league_member ORDER BY user_id") == memberships
                assert (
                    await rows("""
                    SELECT session_id, user_id, score, volume_kg_reps, duration_us,
                           body_weight_kg, formula_version
                    FROM league_session_calculation ORDER BY session_id
                """)
                    == old_snapshots
                )
                assert await rows("SELECT * FROM league_round") == []
                assert await rows("SELECT * FROM league_score") == []
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
