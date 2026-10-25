"""merge nutrition goals and workout sessions

Revision ID: fe73e224195b
Revises: 070e2248c9a4, 20261025_02
"""

from collections.abc import Sequence

revision: str = "fe73e224195b"
down_revision: str | Sequence[str] | None = ("070e2248c9a4", "20261025_02")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
