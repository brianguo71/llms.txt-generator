"""Initial schema - consolidated migration.

Revision ID: 001
Revises:
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Projects table
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("url", sa.String(2048), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sitemap_url", sa.String(2048), nullable=True),
        sa.Column("change_detection_method", sa.String(50), nullable=False, server_default="webhook"),
        sa.Column("vendor_subscription_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Pages table
    op.create_table(
        "pages",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("url", sa.String(2048), nullable=False, index=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("h1", sa.String(512), nullable=True),
        sa.Column("h2s", ARRAY(sa.String(200)), nullable=True),
        sa.Column("first_paragraph", sa.Text, nullable=True),
        sa.Column("nlp_summary", sa.String(500), nullable=True),
        sa.Column("etag", sa.String(255), nullable=True),
        sa.Column("last_modified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("sitemap_lastmod", sa.DateTime(timezone=True), nullable=True),
        sa.Column("depth", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_in_nav", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pages_version", "pages", ["version"])

    # Crawl jobs table
    op.create_table(
        "crawl_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("trigger_reason", sa.String(100), nullable=False, server_default="initial"),
        sa.Column("pages_discovered", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pages_crawled", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pages_changed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
    )

    # Generated files table (current version)
    op.create_table(
        "generated_files",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Generated file versions table (history)
    op.create_table(
        "generated_file_versions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("trigger_reason", sa.String(50), nullable=True),
    )
    op.create_index("ix_generated_file_versions_project_id", "generated_file_versions", ["project_id"])
    op.create_index("ix_generated_file_versions_version", "generated_file_versions", ["version"])
    op.create_index(
        "ix_generated_file_versions_project_version",
        "generated_file_versions",
        ["project_id", "version"],
        unique=True,
    )

    # Curated pages table (LLM-generated page descriptions)
    op.create_table(
        "curated_pages",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_curated_pages_project_id", "curated_pages", ["project_id"])
    op.create_unique_constraint("uq_curated_pages_project_url", "curated_pages", ["project_id", "url"])

    # Site overviews table (LLM-generated site descriptions)
    op.create_table(
        "site_overviews",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("site_title", sa.String(255), nullable=False),
        sa.Column("tagline", sa.Text, nullable=False),
        sa.Column("overview", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_site_overviews_project_id", "site_overviews", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_site_overviews_project_id")
    op.drop_table("site_overviews")
    op.drop_constraint("uq_curated_pages_project_url", "curated_pages")
    op.drop_index("ix_curated_pages_project_id")
    op.drop_table("curated_pages")
    op.drop_index("ix_generated_file_versions_project_version")
    op.drop_index("ix_generated_file_versions_version")
    op.drop_index("ix_generated_file_versions_project_id")
    op.drop_table("generated_file_versions")
    op.drop_table("generated_files")
    op.drop_table("crawl_jobs")
    op.drop_index("ix_pages_version")
    op.drop_table("pages")
    op.drop_table("projects")
