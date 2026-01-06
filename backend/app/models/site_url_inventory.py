"""Site URL Inventory model for tracking all URLs discovered on a website."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SiteUrlInventory(Base):
    """Track all URLs discovered on a website via Firecrawl /map.
    
    This provides a reliable URL inventory for detecting new vs existing URLs
    during rescrapes, avoiding false positives from crawl variance.
    """

    __tablename__ = "site_url_inventories"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )

    # Normalized URL (lowercase, no trailing slash)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    
    # Tracking when URL was first and last seen
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="url_inventory")

    # Composite unique constraint - each URL should only appear once per project
    __table_args__ = (
        UniqueConstraint('project_id', 'url', name='uq_site_url_inventory_project_url'),
    )


# Forward reference
from app.models.project import Project  # noqa: E402

