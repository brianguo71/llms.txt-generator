"""Add lightweight change detection columns.

Revision ID: 004
Revises: 003
Create Date: 2024-01-05

Adds columns for lightweight change detection:
- projects.next_lightweight_check_at: For staggered scheduling
- pages.last_modified_header: Raw Last-Modified header for conditional requests
- pages.baseline_html_hash: Baseline hash from last full rescrape (two-hash strategy)
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add next_lightweight_check_at to projects for staggered scheduling
    op.add_column(
        "projects",
        sa.Column("next_lightweight_check_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Add last_modified_header to pages (raw string for If-Modified-Since)
    op.add_column(
        "pages",
        sa.Column("last_modified_header", sa.String(255), nullable=True),
    )

    # Add baseline_html_hash to pages (for two-hash strategy)
    op.add_column(
        "pages",
        sa.Column("baseline_html_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pages", "baseline_html_hash")
    op.drop_column("pages", "last_modified_header")
    op.drop_column("projects", "next_lightweight_check_at")

