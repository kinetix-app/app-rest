"""Preserve image variants and protect imported global catalogue identities."""

from alembic import op

revision = "20261021_03"
down_revision = "20261021_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE exercise ADD COLUMN image_urls JSONB")
    # Fail on pre-existing duplicate imports rather than deleting data implicitly.
    op.execute("""
        CREATE UNIQUE INDEX ix_exercise_catalogue_source_external_id
        ON exercise (source, external_id)
        WHERE user_id IS NULL AND external_id IS NOT NULL AND source <> 'manual'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX ix_exercise_catalogue_source_external_id")
    op.execute("ALTER TABLE exercise DROP COLUMN image_urls")
