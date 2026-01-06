"""CrawlJob model for tracking crawl operations."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CrawlJob(Base):
    """A crawl job for a project."""

    __tablename__ = "crawl_jobs"

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

    # Job status
    status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending, running, completed, failed
    trigger_reason: Mapped[str] = mapped_column(
        String(100), default="initial"
    )  # initial, scheduled_check, manual, lightweight_change_detected

    # Progress tracking
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0)
    pages_changed: Mapped[int] = mapped_column(Integer, default=0)

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Celery task ID for status tracking
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="crawl_jobs")

    def start(self) -> None:
        """Mark the job as started."""
        self.status = "running"
        self.started_at = datetime.now(timezone.utc)

    def complete(self, pages_crawled: int = 0, pages_changed: int = 0) -> None:
        """Mark the job as completed."""
        self.status = "completed"
        self.completed_at = datetime.now(timezone.utc)
        self.pages_crawled = pages_crawled
        self.pages_changed = pages_changed

    def fail(self, error_message: str) -> None:
        """Mark the job as failed."""
        self.status = "failed"
        self.completed_at = datetime.now(timezone.utc)
        self.error_message = error_message


# Forward reference
from app.models.project import Project  # noqa: E402

