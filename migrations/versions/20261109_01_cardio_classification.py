"""Classify previously imported provider cardio exercises without changing history.

Revision ID: 20261109_01
Revises: 20261103_02
"""

from alembic import op

revision = "20261109_01"
down_revision = "20261103_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE exercise SET activity_type = 'cardio'
        WHERE user_id IS NULL AND source = 'ascend_edb_v2'
          AND external_id IS NOT NULL AND imported_at IS NOT NULL
          AND activity_type = 'gym'
          AND EXISTS (
            SELECT 1 FROM unnest(exercise_types) AS provider_type
            WHERE lower(trim(provider_type)) = 'cardio'
          )
    """)


def downgrade() -> None:
    # The previous classification cannot be reconstructed safely.
    pass
