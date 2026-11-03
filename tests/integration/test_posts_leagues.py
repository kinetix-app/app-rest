"""Sprint 2 persistence and additive upgrades in an isolated test-owned schema."""

from datetime import date
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import create_async_engine

from app.features.leagues.models import league, league_member, league_round, league_score
from app.features.posts.models import FileType, PostType, PostVisibility, file, post
from tests.integration.test_migrations import ROOT, migrate

pytestmark = pytest.mark.integration


@pytest.mark.anyio
async def test_posts_leagues_upgrade_persistence_and_downgrade(integration_url):
    engine = create_async_engine(integration_url)
    schema = "sprint2_" + uuid4().hex
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await connection.run_sync(lambda conn: migrate(conn, "20261025_06"))
                user_id = await connection.scalar(
                    text("INSERT INTO users DEFAULT VALUES RETURNING id")
                )
                before = (await connection.execute(text("SELECT * FROM users"))).all()
                await connection.run_sync(lambda conn: migrate(conn, "head"))
                assert (await connection.execute(text("SELECT * FROM users"))).all() == before
                config = Config(str(ROOT / "alembic.ini"))
                await connection.run_sync(
                    lambda conn: (config.attributes.update(connection=conn), command.check(config))
                )
                post_id = await connection.scalar(
                    post.insert()
                    .values(
                        text="Test",
                        user_id=user_id,
                        visibility=PostVisibility.PRIVATE,
                        type=PostType.SESSION,
                    )
                    .returning(post.c.id)
                )
                await connection.execute(
                    file.insert().values(
                        post_id=post_id,
                        order=1,
                        type=FileType.IMAGE,
                        url="https://bucket.example/test",
                        file_name="test.jpg",
                        file_size=5_000_000_000,
                    )
                )
                await connection.execute(
                    text("INSERT INTO post_like (post_id,user_id) VALUES (:post,:user)"),
                    {"post": post_id, "user": user_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO post_comment (post_id,user_id,comment) "
                        "VALUES (:post,:user,'Test')"
                    ),
                    {"post": post_id, "user": user_id},
                )
                league_id = await connection.scalar(
                    league.insert()
                    .values(name="Test league", created_by=user_id)
                    .returning(league.c.id)
                )
                await connection.execute(
                    league_member.insert().values(user_id=user_id, league_id=league_id)
                )
                round_id = await connection.scalar(
                    league_round.insert()
                    .values(
                        league_id=league_id,
                        start_date=date(2026, 11, 2),
                        end_date=date(2026, 11, 8),
                    )
                    .returning(league_round.c.id)
                )
                await connection.execute(
                    league_score.insert().values(
                        league_id=league_id, user_id=user_id, round_id=round_id, score=12
                    )
                )
                assert await connection.scalar(select(post.c.visibility)) == PostVisibility.PRIVATE
                assert await connection.scalar(select(file.c.file_size)) == 5_000_000_000
                assert (await connection.scalar(select(post.c.created_at))).tzinfo is not None
                assert await connection.scalar(select(league_score.c.score)) == 12
                for table, values in (
                    ("post_like", "(post_id,user_id) VALUES (1,1)"),
                    ("league_member", "(user_id,league_id) VALUES (1,1)"),
                    ("league_score", "(league_id,user_id,round_id,score) VALUES (1,1,1,0)"),
                    ("post_comment", "(post_id,user_id,comment) VALUES (99999,1,'Invalid')"),
                ):
                    with pytest.raises(IntegrityError):
                        async with connection.begin_nested():
                            await connection.execute(text(f"INSERT INTO {table} {values}"))
                with pytest.raises(StatementError):
                    await connection.execute(
                        post.insert().values(
                            text="Invalid",
                            user_id=user_id,
                            visibility="INVALID",
                            type=PostType.SESSION,
                        )
                    )
                # Database categories deliberately have no CHECK or native enum restriction.
                await connection.execute(text("UPDATE post SET visibility='OTHER'"))
                assert (
                    await connection.run_sync(
                        lambda conn: inspect(conn).get_check_constraints("post")
                    )
                    == []
                )
                await connection.run_sync(lambda conn: migrate(conn, "20261025_06", downgrade=True))
                assert (await connection.execute(text("SELECT * FROM users"))).all() == before
                await connection.run_sync(lambda conn: migrate(conn, "head"))
                assert await connection.scalar(text("SELECT count(*) FROM post")) == 0
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
