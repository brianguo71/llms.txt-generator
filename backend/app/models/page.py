"""Page model for crawled website pages."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Page(Base):
    """A crawled page from a tracked website."""

    __tablename__ = "pages"

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

    # Page data
    url: Mapped[str] = mapped_column(String(2048), index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    h1: Mapped[str | None] = mapped_column(String(512), nullable=True)
    h2s: Mapped[list[str] | None] = mapped_column(ARRAY(String(200)), nullable=True)
    first_paragraph: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Fingerprinting for change detection
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_modified_header: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Raw header for If-Modified-Since
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_length: Mapped[int | None] = mapped_column(nullable=True)  # For Content-Length based change detection
    sample_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Semantic fingerprint hash

    # Versioning (higher version = more recent crawl)
    version: Mapped[int] = mapped_column(default=1, index=True)

    # Metadata
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="pages")


# Forward reference
from app.models.project import Project  # noqa: E402

