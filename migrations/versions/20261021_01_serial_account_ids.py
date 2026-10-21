"""Convert existing account UUIDs to generated BIGINT identifiers.

Identity, status, profile data and relationships survive the conversion. Internal
IDs change: deploy with the integer-ID backend while application traffic is stopped.
Downgrade preserves account data and relationships but assigns NEW UUIDs; original
UUID values cannot be reconstructed. Back up the database before upgrading if exact
identifier restoration is required.
"""

from alembic import op

revision = "20261021_01"
down_revision = "20261013_01"
branch_labels = None
depends_on = None


def _convert_ids(*, to_bigint: bool) -> None:
    # Lock all affected tables before building mappings so concurrent writers cannot
    # create rows absent from the mapping. Alembic runs this revision transactionally.
    op.execute("LOCK TABLE users, auth_accounts, profiles IN ACCESS EXCLUSIVE MODE")
    old_type, new_type = ("UUID", "BIGINT") if to_bigint else ("BIGINT", "UUID")
    for table in ("users", "auth_accounts"):
        new_id = "row_number() OVER (ORDER BY id)" if to_bigint else "gen_random_uuid()"
        op.execute(
            f"CREATE TEMP TABLE kinetix_{table}_id_map ON COMMIT DROP AS "
            f"SELECT id AS old_id, {new_id} AS new_id FROM {table}"
        )
        op.execute(f"CREATE UNIQUE INDEX ON kinetix_{table}_id_map (old_id)")
        op.execute(f"""
            CREATE FUNCTION pg_temp.kinetix_{table}_id({old_type}) RETURNS {new_type}
            LANGUAGE SQL STRICT STABLE AS
            'SELECT new_id FROM pg_temp.kinetix_{table}_id_map WHERE old_id = $1'
        """)

    op.drop_constraint("fk_auth_accounts_user_id_users", "auth_accounts", type_="foreignkey")
    op.drop_constraint("fk_profiles_user_id_users", "profiles", type_="foreignkey")
    if not to_bigint:
        # Defaults must be removed before changing column type. Owned sequences are
        # explicitly removed below; the original UUID ORM supplies UUID defaults.
        for table in ("users", "auth_accounts"):
            op.execute(f"ALTER TABLE {table} ALTER COLUMN id DROP DEFAULT")
    for table, column, mapping in (
        ("users", "id", "users"),
        ("auth_accounts", "id", "auth_accounts"),
        ("auth_accounts", "user_id", "users"),
        ("profiles", "user_id", "users"),
    ):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {new_type} "
            f"USING pg_temp.kinetix_{mapping}_id({column})"
        )
    op.create_foreign_key(
        "fk_auth_accounts_user_id_users",
        "auth_accounts",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_profiles_user_id_users",
        "profiles",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    for table in ("users", "auth_accounts"):
        op.execute(f"DROP FUNCTION pg_temp.kinetix_{table}_id({old_type})")
        op.execute(f"DROP TABLE pg_temp.kinetix_{table}_id_map")
        if to_bigint:
            op.execute(f"CREATE SEQUENCE {table}_id_seq AS BIGINT OWNED BY {table}.id")
            op.execute(
                f"SELECT setval('{table}_id_seq', COALESCE(MAX(id), 1), "
                f"MAX(id) IS NOT NULL) FROM {table}"
            )
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN id "
                f"SET DEFAULT nextval('{table}_id_seq'::regclass)"
            )
        else:
            op.execute(f"DROP SEQUENCE {table}_id_seq")


def upgrade() -> None:
    _convert_ids(to_bigint=True)


def downgrade() -> None:
    _convert_ids(to_bigint=False)
