"""Remove scheduling columns from projects table (migrated to Redis).

This migration removes columns that are now managed by Redis sorted sets:
- projects.check_interval_hours -> Redis hash (schedule:intervals)
- projects.next_check_at -> Redis sorted set (schedule:full_check)
- projects.next_lightweight_check_at -> Redis sorted set (schedule:lightweight_check)
- projects.last_lightweight_rescrape_at -> Redis sorted set (schedule:cooldowns)
- projects.homepage_content_hash -> No longer needed

Also removes unused columns from pages and crawl_jobs tables:
- projects.sitemap_url -> Never used
- pages.nlp_summary -> Never used
- pages.is_in_nav -> Never used
- pages.last_modified -> Never used (last_modified_header is used)
- pages.sitemap_lastmod -> Never used
- pages.depth -> Only default value used
- pages.baseline_html_hash -> Write-only, incomplete feature
- crawl_jobs.pages_discovered -> Never updated

Revision ID: 009
Revises: 008
Create Date: 2026-01-06
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    # Projects table - remove scheduling columns (now in Redis)
    op.drop_column("projects", "check_interval_hours")
    op.drop_column("projects", "next_check_at")
    op.drop_column("projects", "next_lightweight_check_at")
    op.drop_column("projects", "last_lightweight_rescrape_at")
    op.drop_column("projects", "homepage_content_hash")
    op.drop_column("projects", "sitemap_url")
    
    # Pages table - remove unused columns
    op.drop_column("pages", "nlp_summary")
    op.drop_column("pages", "is_in_nav")
    op.drop_column("pages", "last_modified")
    op.drop_column("pages", "sitemap_lastmod")
    op.drop_column("pages", "depth")
    op.drop_column("pages", "baseline_html_hash")
    
    # Crawl jobs table - remove unused column
    op.drop_column("crawl_jobs", "pages_discovered")


def downgrade():
    # Crawl jobs table
    op.add_column(
        "crawl_jobs",
        sa.Column("pages_discovered", sa.Integer(), nullable=False, server_default="0"),
    )
    
    # Pages table
    op.add_column(
        "pages",
        sa.Column("baseline_html_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "pages",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "pages",
        sa.Column("sitemap_lastmod", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pages",
        sa.Column("last_modified", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pages",
        sa.Column("is_in_nav", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "pages",
        sa.Column("nlp_summary", sa.String(500), nullable=True),
    )
    
    # Projects table
    op.add_column(
        "projects",
        sa.Column("sitemap_url", sa.String(2048), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("homepage_content_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("last_lightweight_rescrape_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("next_lightweight_check_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("check_interval_hours", sa.Integer(), nullable=False, server_default="24"),
    )

