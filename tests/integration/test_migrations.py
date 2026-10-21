"""Verify real migration DDL and populated upgrades in isolated test-owned schemas."""

import re
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
                for ddl in re.findall(r"CREATE (?:TABLE|INDEX) .*?;(?=\n|$)", sql, re.S):
                    # Table bodies contain semicolons only inside line comments.
                    await connection.execute(text(ddl))
                await connection.execute(text(f'SET LOCAL search_path TO "{migrated}"'))
                await connection.run_sync(lambda conn: migrate(conn, "head"))
                actual = await connection.run_sync(lambda conn: schema_signature(conn, migrated))
                expected = await connection.run_sync(lambda conn: schema_signature(conn, draft))
                assert len(actual) == 19
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
