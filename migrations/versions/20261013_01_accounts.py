"""Local accounts, trusted identities and private profiles (ACC01, app-rest#1)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'blocked', 'deleted')", name=op.f("ck_users_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_table(
        "auth_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_auth_accounts_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_accounts")),
        sa.UniqueConstraint("issuer", "subject", name="uq_auth_accounts_identity"),
    )
    op.create_index(op.f("ix_auth_accounts_user_id"), "auth_accounts", ["user_id"])
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("timezone", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_profiles_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_profiles")),
    )


def downgrade() -> None:
    op.drop_table("profiles")
    op.drop_index(op.f("ix_auth_accounts_user_id"), table_name="auth_accounts")
    op.drop_table("auth_accounts")
    op.drop_table("users")
