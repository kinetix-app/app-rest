"""Verify real migration DDL and populated upgrades in isolated test-owned schemas."""

import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def migrate(connection, target, *, downgrade=False):
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    (command.downgrade if downgrade else command.upgrade)(config, target)


def schema_signature(connection, schema):
    inspector = inspect(connection)
    result = {}
    for table in inspector.get_table_names(schema=schema):
        if table == "alembic_version":
            continue
        columns = []
        for column in inspector.get_columns(table, schema=schema):
            default = (
                (column["default"] or "").replace(f'"{schema}".', "").replace(schema + ".", "")
            )
            default = default.replace("CURRENT_TIMESTAMP", "now()")
            columns.append((column["name"], repr(column["type"]), column["nullable"], default))
        foreign_keys = sorted(
            (
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                fk["options"].get("ondelete"),
            )
            for fk in inspector.get_foreign_keys(table, schema=schema)
        )
        result[table] = (
            columns,
            inspector.get_pk_constraint(table, schema=schema)["constrained_columns"],
            foreign_keys,
            sorted(
                (
                    tuple(index["column_names"]),
                    index["unique"],
                    index["dialect_options"].get("postgresql_where"),
                )
                for index in inspector.get_indexes(table, schema=schema)
                if not index.get("duplicates_constraint")
            ),
            sorted(
                tuple(unique["column_names"])
                for unique in inspector.get_unique_constraints(table, schema=schema)
            ),
        )
    return result


@pytest.mark.anyio
async def test_clean_migration_matches_sql_draft_and_downgrades(integration_url):
    engine = create_async_engine(integration_url)
    migrated = "migration_" + uuid4().hex
    draft = "draft_" + uuid4().hex
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                for schema in (migrated, draft):
                    await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{draft}"'))
                sql = (ROOT / "db-schema.sql").read_text()
                for ddl in re.findall(
                    r"CREATE (?:TABLE|(?:UNIQUE )?INDEX) .*?;(?=\n|$)", sql, re.S
                ):
                    # Table bodies contain semicolons only inside line comments.
                    await connection.execute(text(ddl))
                await connection.execute(text(f'SET LOCAL search_path TO "{migrated}"'))
                await connection.run_sync(lambda conn: migrate(conn, "head"))
                actual = await connection.run_sync(lambda conn: schema_signature(conn, migrated))
                expected = await connection.run_sync(lambda conn: schema_signature(conn, draft))
                assert len(actual) == 20
                assert actual == expected
                # Empty-account upgrades must leave sequences ready to generate ID 1.
                assert (
                    await connection.scalar(text("INSERT INTO users DEFAULT VALUES RETURNING id"))
                    == 1
                )
                await connection.run_sync(lambda conn: migrate(conn, "base", downgrade=True))
                assert (
                    await connection.run_sync(lambda conn: schema_signature(conn, migrated)) == {}
                )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_populated_uuid_upgrade_preserves_accounts_and_relationships(integration_url):
    engine = create_async_engine(integration_url)
    schema = "migration_" + uuid4().hex
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await connection.run_sync(lambda conn: migrate(conn, "20261013_01"))
                for name, status in (("Alice", "active"), ("Bob", "blocked")):
                    user_id = uuid4()
                    await connection.execute(
                        text("INSERT INTO users (id, status) VALUES (:id, :status)"),
                        {"id": user_id, "status": status},
                    )
                    await connection.execute(
                        text(
                            "INSERT INTO profiles (user_id, display_name, timezone) "
                            "VALUES (:id, :name, 'Europe/Madrid')"
                        ),
                        {"id": user_id, "name": name},
                    )
                    for issuer in ("urn:test:primary", "urn:test:linked"):
                        await connection.execute(
                            text(
                                "INSERT INTO auth_accounts (id, user_id, issuer, subject) "
                                "VALUES (:id, :user_id, :issuer, :subject)"
                            ),
                            {"id": uuid4(), "user_id": user_id, "issuer": issuer, "subject": name},
                        )
                query = text(
                    "SELECT a.issuer, a.subject, u.status, p.display_name, p.timezone, "
                    "u.created_at, u.updated_at, a.created_at, p.created_at, p.updated_at "
                    "FROM users u JOIN auth_accounts a ON a.user_id = u.id "
                    "JOIN profiles p ON p.user_id = u.id ORDER BY a.issuer, a.subject"
                )
                before = (await connection.execute(query)).all()
                await connection.run_sync(lambda conn: migrate(conn, "head"))
                assert (await connection.execute(query)).all() == before
                assert (
                    await connection.scalar(text("INSERT INTO users DEFAULT VALUES RETURNING id"))
                    == 3
                )
                assert (
                    await connection.scalar(
                        text(
                            "INSERT INTO auth_accounts (user_id, issuer, subject) "
                            "VALUES (3, 'urn:test:new', 'new') RETURNING id"
                        )
                    )
                    == 5
                )
                # Remove the new test account before comparing original account rows.
                await connection.execute(text("DELETE FROM auth_accounts WHERE user_id = 3"))
                await connection.execute(text("DELETE FROM users WHERE id = 3"))
                await connection.run_sync(lambda conn: migrate(conn, "20261013_01", downgrade=True))
                assert (await connection.execute(query)).all() == before
                assert (
                    await connection.scalar(text("SELECT pg_typeof(id)::text FROM users LIMIT 1"))
                    == "uuid"
                )
                await connection.run_sync(lambda conn: migrate(conn, "head"))
                assert (await connection.execute(query)).all() == before
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_completed_session_upgrade_preserves_legacy_utc_and_mass(integration_url):
    engine = create_async_engine(integration_url)
    schema = "migration_" + uuid4().hex
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await connection.run_sync(lambda conn: migrate(conn, "20261021_03"))
                await connection.execute(text("INSERT INTO users DEFAULT VALUES"))
                await connection.execute(
                    text("INSERT INTO exercise (activity_type,name) VALUES ('gym','Legacy')")
                )
                await connection.execute(
                    text(
                        "INSERT INTO training_session (user_id,activity_type,started_at,ended_at) "
                        "VALUES (1,'gym','2026-10-20 14:00:00','2026-10-20 15:00:00')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO session_exercise (session_id,exercise_id,exercise_order) "
                        "VALUES (1,1,1)"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO exercise_set (session_exercise_id,set_number,reps,weight_kg) "
                        "VALUES (1,1,8,42.50)"
                    )
                )
                await connection.execute(text("SET LOCAL TIME ZONE 'Pacific/Honolulu'"))
                await connection.run_sync(lambda conn: migrate(conn, "head"))
                row = (
                    await connection.execute(
                        text(
                            "SELECT started_at AT TIME ZONE 'UTC', ended_at AT TIME ZONE 'UTC',"
                            "client_session_id,payload_fingerprint FROM training_session"
                        )
                    )
                ).one()
                assert row == (datetime(2026, 10, 20, 14), datetime(2026, 10, 20, 15), None, None)
                assert (
                    str(await connection.scalar(text("SELECT weight_kg FROM exercise_set")))
                    == "42.500000"
                )
                await connection.run_sync(lambda conn: migrate(conn, "20261021_03", downgrade=True))
                assert (
                    str(await connection.scalar(text("SELECT started_at FROM training_session")))
                    == "2026-10-20 14:00:00"
                )
                assert (
                    str(await connection.scalar(text("SELECT weight_kg FROM exercise_set")))
                    == "42.50"
                )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_independent_exercise_upgrade_preserves_history_and_cleans_draft_json(
    integration_url,
):
    import json

    engine = create_async_engine(integration_url)
    schema = "migration_" + uuid4().hex
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await connection.run_sync(lambda conn: migrate(conn, "20261025_01"))
                for statement in (
                    "INSERT INTO users DEFAULT VALUES",
                    "INSERT INTO exercise (activity_type,name) VALUES ('gym','Legacy')",
                    "INSERT INTO routine (user_id,name) VALUES (1,'Origin')",
                    "INSERT INTO routine_exercise (routine_id,exercise_id,exercise_order) "
                    "VALUES (1,1,1)",
                    "INSERT INTO training_session "
                    "(user_id,routine_id,activity_type,started_at,ended_at) "
                    "VALUES (1,1,'gym','2026-10-25T10:00:00Z','2026-10-25T11:00:00Z')",
                    "INSERT INTO session_exercise "
                    "(session_id,routine_exercise_id,exercise_id,exercise_order,notes) "
                    "VALUES (1,1,1,1,'keep')",
                    "INSERT INTO exercise_set "
                    "(session_exercise_id,set_number,reps,weight_kg,completed) "
                    "VALUES (1,1,8,45.359237,true)",
                    "INSERT INTO routine_slot_provenance "
                    "(user_id,routine_id,routine_exercise_id,exercise_id) VALUES (1,1,1,1)",
                ):
                    await connection.execute(text(statement))
                snapshot = {
                    "name": "Origin",
                    "routine_id": 1,
                    "started_at": "2026-10-25T10:00:00Z",
                    "exercises": [
                        {
                            "client_id": str(uuid4()),
                            "exercise_id": 1,
                            "routine_exercise_id": 1,
                            "sets": [],
                        }
                    ],
                }
                await connection.execute(
                    text(
                        "INSERT INTO session_draft (user_id,client_session_id,snapshot) "
                        "VALUES (1,:key,CAST(:snapshot AS jsonb))"
                    ),
                    {"key": uuid4(), "snapshot": json.dumps(snapshot)},
                )
                history_query = text(
                    "SELECT s.user_id,s.routine_id,s.started_at,s.ended_at,e.id,e.exercise_id,"
                    "e.exercise_order,e.notes,v.id,v.reps,v.weight_kg,v.completed "
                    "FROM training_session s JOIN session_exercise e ON e.session_id=s.id "
                    "JOIN exercise_set v ON v.session_exercise_id=e.id"
                )
                before = (await connection.execute(history_query)).all()
                await connection.run_sync(lambda conn: migrate(conn, "head"))
                assert (await connection.execute(history_query)).all() == before
                actual = await connection.run_sync(lambda conn: schema_signature(conn, schema))
                assert "routine_slot_provenance" not in actual
                assert "routine_exercise_id" not in [
                    col[0] for col in actual["session_exercise"][0]
                ]
                saved = await connection.scalar(text("SELECT snapshot FROM session_draft"))
                assert "routine_exercise_id" not in saved["exercises"][0]
                assert saved["routine_id"] == 1
                assert (
                    await connection.scalar(text("SELECT finish_update_routine FROM session_draft"))
                    is False
                )
                # Removing template slots no longer affects any recorded exercise/set.
                await connection.execute(text("DELETE FROM routine_exercise WHERE id=1"))
                assert (await connection.execute(history_query)).all() == before
                await connection.run_sync(lambda conn: migrate(conn, "20261025_01", downgrade=True))
                assert (await connection.execute(history_query)).all() == before
                assert (
                    await connection.scalar(
                        text("SELECT routine_exercise_id FROM session_exercise")
                    )
                    is None
                )
                await connection.run_sync(lambda conn: migrate(conn, "head"))
                assert (await connection.execute(history_query)).all() == before
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
