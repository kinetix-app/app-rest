"""Add timezone and exact membership metadata without reinterpreting legacy rows."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_01"
down_revision = "20261116_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("league", sa.Column("timezone", sa.String(100), nullable=True))
    op.add_column(
        "league_member", sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "league_member",
        sa.Column("role", sa.String(16), nullable=True, comment="Values: admin, member"),
    )

    op.create_table(
        "league_invitation",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("league_id", sa.BigInteger(), sa.ForeignKey("league.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("league_invitation")
    op.drop_column("league_member", "role")
    op.drop_column("league_member", "joined_at")
    op.drop_column("league", "timezone")
