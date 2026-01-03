"""SiteOverview model for storing site-level LLM-generated content."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SiteOverview(Base):
    """Stores site-level overview content (title, tagline, overview)."""

    __tablename__ = "site_overviews"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        unique=True,  # One overview per project
        index=True,
    )

    # Site-level content (from LLM)
    site_title: Mapped[str] = mapped_column(String(255))
    tagline: Mapped[str] = mapped_column(Text)  # One-sentence blockquote (5-15 words)
    overview: Mapped[str] = mapped_column(Text)  # Multi-paragraph overview (50-200 words)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="site_overview")


# Forward reference
from app.models.project import Project  # noqa: E402

