"""Add last_lightweight_rescrape_at for cooldown tracking.

Revision ID: 006
Revises: 005
Create Date: 2026-01-05

Adds column to track when a lightweight-triggered rescrape was last executed,
enabling cooldown period enforcement to prevent over-triggering.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add last_lightweight_rescrape_at to projects for cooldown tracking
    op.add_column(
        "projects",
        sa.Column("last_lightweight_rescrape_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "last_lightweight_rescrape_at")

