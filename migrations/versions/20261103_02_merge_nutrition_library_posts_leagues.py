"""Merge nutrition library and posts/leagues migration branches.

Revision ID: 20261103_02
Revises: 20261103_01, 20261102_01
"""

from collections.abc import Sequence

revision: str = "20261103_02"
down_revision: str | Sequence[str] | None = ("20261103_01", "20261102_01")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
