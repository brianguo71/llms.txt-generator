"""CuratedPage model for storing LLM-generated page descriptions."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CuratedPage(Base):
    """Stores per-page curated data (LLM-generated descriptions)."""

    __tablename__ = "curated_pages"
    __table_args__ = (
        UniqueConstraint("project_id", "url", name="uq_curated_pages_project_url"),
    )

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

    # Page identification
    url: Mapped[str] = mapped_column(String(2048))
    
    # Curated content (from LLM)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100))
    
    # Hash of the page content when this description was generated
    # Used to detect if page has changed and needs re-curation
    content_hash: Mapped[str] = mapped_column(String(64))

    # Fingerprinting for lightweight change detection
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_modified_header: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Raw header for If-Modified-Since
    content_length: Mapped[int | None] = mapped_column(nullable=True)  # For Content-Length based change detection
    sample_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Semantic fingerprint hash

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
    project: Mapped["Project"] = relationship("Project", back_populates="curated_pages")


# Forward reference
from app.models.project import Project  # noqa: E402

