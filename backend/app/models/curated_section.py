"""CuratedSection model for storing section-level LLM-generated content."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CuratedSection(Base):
    """Stores section-level curated data (prose descriptions and page assignments).
    
    Each section corresponds to an H2 in the llms.txt output, with:
    - A prose description explaining the section's theme
    - A list of page URLs belonging to this section
    - A content hash for change detection
    """

    __tablename__ = "curated_sections"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_curated_sections_project_name"),
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

    # Section identification
    name: Mapped[str] = mapped_column(String(100))  # e.g., "Platform Features"
    
    # Section content (from LLM)
    description: Mapped[str] = mapped_column(Text)  # Prose description (50-300 words)
    
    # List of page URLs in this section (for quick lookup)
    page_urls: Mapped[list] = mapped_column(JSONB, default=list)
    
    # Hash of all page content hashes in this section
    # Used to detect if any page in section changed and needs re-curation
    content_hash: Mapped[str] = mapped_column(String(64))

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
    project: Mapped["Project"] = relationship("Project", back_populates="curated_sections")


# Forward reference
from app.models.project import Project  # noqa: E402

