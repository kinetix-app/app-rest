"""Consolidate active weekly rounds, daily scores and source snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_06"
down_revision = "20261117_05"
branch_labels = None
depends_on = None

_SCORE_COLUMNS = (
    "league_id, user_id, local_day, round_id, session_id, score, volume_kg_reps, "
    "duration_us, body_weight_kg, ended_at, formula_version"
)
_SNAPSHOT_COLUMNS = (
    ("league_score", sa.Numeric(40, 0)),
    ("league_volume_kg_reps", sa.Numeric(40, 6)),
    ("league_duration_us", sa.BigInteger()),
    ("league_body_weight_kg", sa.Numeric(10, 6)),
    ("league_formula_version", sa.String(100)),
)
_DAILY_COLUMNS = (
    ("local_day", sa.Date()),
    ("session_id", sa.BigInteger()),
    ("volume_kg_reps", sa.Numeric(40, 6)),
    ("duration_us", sa.BigInteger()),
    ("body_weight_kg", sa.Numeric(10, 6)),
    ("ended_at", sa.DateTime(timezone=True)),
    ("formula_version", sa.String(100)),
)
_LEGACY_SCORE_FKS = (
    ("fk_league_score_league_id_league", "league", "league_id"),
    ("fk_league_score_round_id_league_round", "league_round", "round_id"),
    ("fk_league_score_user_id_users", "users", "user_id"),
)


def _round_sequence(destination: str, source: str) -> None:
    # Keep IDs allocated by either sequence, even if unused or rolled back.
    op.execute(f"""
        WITH sequence_state AS (
            SELECT (SELECT max(id) FROM {destination}) AS max_id,
                   pg_sequence_last_value(pg_get_serial_sequence('{destination}', 'id')::regclass)
                       AS destination_value,
                   pg_sequence_last_value(pg_get_serial_sequence('{source}', 'id')::regclass)
                       AS source_value
        )
        SELECT setval(pg_get_serial_sequence('{destination}', 'id')::regclass,
                      GREATEST(max_id, destination_value, source_value, 1),
                      COALESCE(max_id, destination_value, source_value) IS NOT NULL)
        FROM sequence_state
    """)


def _result_round_fk(previous: str, target: str) -> None:
    op.drop_constraint(
        f"fk_league_result_league_id_{previous}", "league_result", type_="foreignkey"
    )
    op.create_foreign_key(
        f"fk_league_result_league_id_{target}",
        "league_result",
        target,
        ["league_id", "round_id"],
        ["league_id", "id"],
    )


def upgrade() -> None:
    # Keep the copy and old-table retirement in one transaction with writes excluded.
    op.execute("""
        LOCK TABLE training_session, league_score, league_round, league_daily_score,
          league_scoring_round, league_session_calculation, league_result
        IN ACCESS EXCLUSIVE MODE
    """)
    op.execute("TRUNCATE league_score, league_round")
    op.drop_column("league_round", "start_date")
    op.drop_column("league_round", "end_date")
    op.add_column("league_round", sa.Column("start_at", sa.DateTime(timezone=True), nullable=False))
    op.add_column("league_round", sa.Column("end_at", sa.DateTime(timezone=True), nullable=False))
    op.create_unique_constraint(
        "uq_league_round_league_id", "league_round", ["league_id", "start_at"]
    )
    op.create_unique_constraint("uq_league_round_league_id_id", "league_round", ["league_id", "id"])
    op.execute("""
        INSERT INTO league_round (id, league_id, start_at, end_at)
        SELECT id, league_id, start_at, end_at FROM league_scoring_round
    """)
    _round_sequence("league_round", "league_scoring_round")

    for name, column_type in _SNAPSHOT_COLUMNS:
        op.add_column("training_session", sa.Column(name, column_type, nullable=True))
    op.execute("""
        UPDATE training_session AS session
        SET league_score = snapshot.score,
            league_volume_kg_reps = snapshot.volume_kg_reps,
            league_duration_us = snapshot.duration_us,
            league_body_weight_kg = snapshot.body_weight_kg,
            league_formula_version = snapshot.formula_version
        FROM league_session_calculation AS snapshot
        WHERE session.id = snapshot.session_id AND session.user_id = snapshot.user_id
    """)

    for name, _, _ in _LEGACY_SCORE_FKS:
        op.drop_constraint(name, "league_score", type_="foreignkey")
    op.drop_constraint("pk_league_score", "league_score", type_="primary")
    op.drop_column("league_score", "created_at")
    op.alter_column("league_score", "score", existing_type=sa.Integer(), type_=sa.Numeric(40, 0))
    for name, column_type in _DAILY_COLUMNS:
        op.add_column("league_score", sa.Column(name, column_type, nullable=False))
    op.create_primary_key("pk_league_score", "league_score", ["league_id", "user_id", "local_day"])
    op.create_foreign_key(
        "fk_league_score_user_id_league_member",
        "league_score",
        "league_member",
        ["user_id", "league_id"],
        ["user_id", "league_id"],
    )
    op.create_foreign_key(
        "fk_league_score_league_id_league_round",
        "league_score",
        "league_round",
        ["league_id", "round_id"],
        ["league_id", "id"],
    )
    op.create_foreign_key(
        "fk_league_score_session_id_training_session",
        "league_score",
        "training_session",
        ["session_id", "user_id"],
        ["id", "user_id"],
    )
    op.execute(f"""
        INSERT INTO league_score ({_SCORE_COLUMNS})
        SELECT {_SCORE_COLUMNS} FROM league_daily_score
    """)
    _result_round_fk("league_scoring_round", "league_round")
    op.drop_table("league_daily_score")
    op.drop_table("league_session_calculation")
    op.drop_table("league_scoring_round")


def downgrade() -> None:
    # Restore active rows to the former schema. Discarded legacy aggregates stay discarded.
    op.execute("""
        LOCK TABLE training_session, league_score, league_round, league_result
        IN ACCESS EXCLUSIVE MODE
    """)
    op.create_table(
        "league_scoring_round",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("league_id", sa.BigInteger, sa.ForeignKey("league.id"), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("league_id", "start_at"),
        sa.UniqueConstraint("league_id", "id", name="uq_league_scoring_round_league_id_id"),
    )
    op.execute("""
        INSERT INTO league_scoring_round (id, league_id, start_at, end_at)
        SELECT id, league_id, start_at, end_at FROM league_round
    """)
    _round_sequence("league_scoring_round", "league_round")
    op.create_table(
        "league_session_calculation",
        sa.Column("session_id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("score", sa.Numeric(40, 0)),
        sa.Column("volume_kg_reps", sa.Numeric(40, 6), nullable=False),
        sa.Column("duration_us", sa.BigInteger, nullable=False),
        sa.Column("body_weight_kg", sa.Numeric(10, 6)),
        sa.Column("formula_version", sa.String(100), nullable=False),
        sa.UniqueConstraint("session_id", "user_id"),
        sa.ForeignKeyConstraint(
            ["session_id", "user_id"], ["training_session.id", "training_session.user_id"]
        ),
    )
    op.execute("""
        INSERT INTO league_session_calculation
          (session_id, user_id, score, volume_kg_reps, duration_us, body_weight_kg, formula_version)
        SELECT id, user_id, league_score, league_volume_kg_reps, league_duration_us,
               league_body_weight_kg, league_formula_version
        FROM training_session WHERE league_formula_version IS NOT NULL
    """)
    op.create_table(
        "league_daily_score",
        sa.Column("league_id", sa.BigInteger, nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("round_id", sa.BigInteger, nullable=False),
        sa.Column("score", sa.Numeric(40, 0), nullable=False),
        *(sa.Column(name, column_type, nullable=False) for name, column_type in _DAILY_COLUMNS),
        sa.PrimaryKeyConstraint("league_id", "user_id", "local_day"),
        sa.ForeignKeyConstraint(
            ["user_id", "league_id"], ["league_member.user_id", "league_member.league_id"]
        ),
        sa.ForeignKeyConstraint(
            ["league_id", "round_id"], ["league_scoring_round.league_id", "league_scoring_round.id"]
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "user_id"],
            ["league_session_calculation.session_id", "league_session_calculation.user_id"],
        ),
    )
    op.execute(f"""
        INSERT INTO league_daily_score ({_SCORE_COLUMNS})
        SELECT {_SCORE_COLUMNS} FROM league_score
    """)
    _result_round_fk("league_round", "league_scoring_round")

    op.execute("TRUNCATE league_score, league_round")
    for name in (
        "fk_league_score_user_id_league_member",
        "fk_league_score_league_id_league_round",
        "fk_league_score_session_id_training_session",
    ):
        op.drop_constraint(name, "league_score", type_="foreignkey")
    op.drop_constraint("pk_league_score", "league_score", type_="primary")
    for name, _ in _DAILY_COLUMNS:
        op.drop_column("league_score", name)
    op.alter_column("league_score", "score", existing_type=sa.Numeric(40, 0), type_=sa.Integer())
    op.add_column(
        "league_score",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_primary_key("pk_league_score", "league_score", ["league_id", "user_id", "round_id"])
    for name, target, column in _LEGACY_SCORE_FKS:
        op.create_foreign_key(name, "league_score", target, [column], ["id"])
    op.drop_constraint("uq_league_round_league_id", "league_round", type_="unique")
    op.drop_constraint("uq_league_round_league_id_id", "league_round", type_="unique")
    op.drop_column("league_round", "start_at")
    op.drop_column("league_round", "end_at")
    op.add_column("league_round", sa.Column("start_date", sa.Date(), nullable=False))
    op.add_column("league_round", sa.Column("end_date", sa.Date(), nullable=False))
    for name, _ in _SNAPSHOT_COLUMNS:
        op.drop_column("training_session", name)
