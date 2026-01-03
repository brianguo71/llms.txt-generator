"""Add curated_sections table for Profound-style llms.txt.

Revision ID: 002
Revises: 001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add last_checked_at column to projects
    op.add_column(
        "projects",
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    
    # Curated sections table (LLM-generated section descriptions)
    op.create_table(
        "curated_sections",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),  # e.g., "Platform Features"
        sa.Column("description", sa.Text, nullable=False),  # Prose description (50-300 words)
        sa.Column("page_urls", postgresql.JSONB, nullable=False, server_default="[]"),  # List of URLs
        sa.Column("content_hash", sa.String(64), nullable=False),  # Hash of all page hashes
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_curated_sections_project_id", "curated_sections", ["project_id"])
    op.create_unique_constraint("uq_curated_sections_project_name", "curated_sections", ["project_id", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_curated_sections_project_name", "curated_sections")
    op.drop_index("ix_curated_sections_project_id")
    op.drop_table("curated_sections")
    op.drop_column("projects", "last_checked_at")

