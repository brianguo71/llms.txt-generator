"""Add fingerprinting fields to curated_pages for lightweight change detection.

Revision ID: 008
Revises: 007
Create Date: 2026-01-06

Adds columns to curated_pages for lightweight change detection:
- etag: HTTP ETag header
- last_modified_header: Raw Last-Modified header for If-Modified-Since
- content_length: Content-Length header for change detection
- sample_hash: Semantic fingerprint hash
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add fingerprinting fields to curated_pages
    op.add_column(
        "curated_pages",
        sa.Column("etag", sa.String(255), nullable=True),
    )
    op.add_column(
        "curated_pages",
        sa.Column("last_modified_header", sa.String(255), nullable=True),
    )
    op.add_column(
        "curated_pages",
        sa.Column("content_length", sa.Integer(), nullable=True),
    )
    op.add_column(
        "curated_pages",
        sa.Column("sample_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("curated_pages", "sample_hash")
    op.drop_column("curated_pages", "content_length")
    op.drop_column("curated_pages", "last_modified_header")
    op.drop_column("curated_pages", "etag")

