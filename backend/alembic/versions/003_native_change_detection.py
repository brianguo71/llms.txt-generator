"""Add native change detection fields to projects.

Revision ID: 003
Revises: 002

Adds:
- check_interval_hours: Configurable check frequency (default 24h)
- next_check_at: When the next check is scheduled
- homepage_content_hash: Hash of homepage for change detection

Removes:
- change_detection_method: No longer needed (was for changedetection.io)
- vendor_subscription_id: No longer needed
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new fields for native change detection
    op.add_column(
        "projects",
        sa.Column("check_interval_hours", sa.Integer(), nullable=False, server_default="24"),
    )
    op.add_column(
        "projects",
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("homepage_content_hash", sa.String(64), nullable=True),
    )
    
    # Remove obsolete changedetection.io fields
    op.drop_column("projects", "change_detection_method")
    op.drop_column("projects", "vendor_subscription_id")


def downgrade() -> None:
    # Restore changedetection.io fields
    op.add_column(
        "projects",
        sa.Column("change_detection_method", sa.String(50), nullable=False, server_default="webhook"),
    )
    op.add_column(
        "projects",
        sa.Column("vendor_subscription_id", sa.String(255), nullable=True),
    )
    
    # Remove native change detection fields
    op.drop_column("projects", "homepage_content_hash")
    op.drop_column("projects", "next_check_at")
    op.drop_column("projects", "check_interval_hours")

