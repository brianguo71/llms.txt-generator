"""Add content_length and sample_hash for header-less sites.

Revision ID: 005
Revises: 004
Create Date: 2026-01-05

Adds columns for enhanced change detection on sites without ETags/Last-Modified:
- pages.content_length: Content-Length header tracking
- pages.sample_hash: Hash of first 5KB for header-less sites
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add content_length to pages for Content-Length based change detection
    op.add_column(
        "pages",
        sa.Column("content_length", sa.Integer(), nullable=True),
    )

    # Add sample_hash to pages (hash of first 5KB for header-less sites)
    op.add_column(
        "pages",
        sa.Column("sample_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pages", "sample_hash")
    op.drop_column("pages", "content_length")

