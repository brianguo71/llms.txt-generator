"""Project model for tracked websites."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Project(Base):
    """A website being tracked for llms.txt generation.
    
    Note: Scheduling (check intervals, next check times, cooldowns) is now
    managed via Redis sorted sets in app.services.scheduler.
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    name: Mapped[str] = mapped_column(String(255))

    # Status
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    pages: Mapped[list["Page"]] = relationship(
        "Page", back_populates="project", cascade="all, delete-orphan"
    )
    crawl_jobs: Mapped[list["CrawlJob"]] = relationship(
        "CrawlJob", back_populates="project", cascade="all, delete-orphan"
    )
    generated_file: Mapped["GeneratedFile | None"] = relationship(
        "GeneratedFile", back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    generated_file_versions: Mapped[list["GeneratedFileVersion"]] = relationship(
        "GeneratedFileVersion", back_populates="project", cascade="all, delete-orphan",
        order_by="desc(GeneratedFileVersion.version)"
    )
    curated_pages: Mapped[list["CuratedPage"]] = relationship(
        "CuratedPage", back_populates="project", cascade="all, delete-orphan"
    )
    site_overview: Mapped["SiteOverview | None"] = relationship(
        "SiteOverview", back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    curated_sections: Mapped[list["CuratedSection"]] = relationship(
        "CuratedSection", back_populates="project", cascade="all, delete-orphan"
    )
    url_inventory: Mapped[list["SiteUrlInventory"]] = relationship(
        "SiteUrlInventory", back_populates="project", cascade="all, delete-orphan"
    )


# Forward references
from app.models.crawl_job import CrawlJob  # noqa: E402
from app.models.curated_page import CuratedPage  # noqa: E402
from app.models.curated_section import CuratedSection  # noqa: E402
from app.models.generated_file import GeneratedFile  # noqa: E402
from app.models.generated_file_version import GeneratedFileVersion  # noqa: E402
from app.models.page import Page  # noqa: E402
from app.models.site_overview import SiteOverview  # noqa: E402
from app.models.site_url_inventory import SiteUrlInventory  # noqa: E402
