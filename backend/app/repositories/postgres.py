"""PostgreSQL repository implementations.

These implement the repository protocols for PostgreSQL.
For future scaling, add ShardedRepository implementations.
"""

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CrawlJob, GeneratedFile, GeneratedFileVersion, Page, Project


class PostgresProjectRepository:
    """PostgreSQL implementation of project repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, project_id: str) -> Project | None:
        """Get a project by ID."""
        result = await self.session.execute(
            select(Project).where(Project.id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_all(self) -> list[Project]:
        """Get all projects."""
        result = await self.session.execute(
            select(Project).order_by(Project.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_url(self, url: str) -> Project | None:
        """Get a project by URL (globally unique)."""
        result = await self.session.execute(
            select(Project).where(Project.url == url)
        )
        return result.scalar_one_or_none()

    async def save(self, project: Project) -> Project:
        """Save a project (insert or update)."""
        self.session.add(project)
        await self.session.flush()
        return project

    async def delete(self, project_id: str) -> bool:
        """Delete a project by ID."""
        result = await self.session.execute(
            delete(Project).where(Project.id == project_id)
        )
        return result.rowcount > 0


class PostgresPageRepository:
    """PostgreSQL implementation of page repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_max_version(self, project_id: str) -> int:
        """Get the maximum version number for a project."""
        result = await self.session.execute(
            select(func.max(Page.version)).where(Page.project_id == project_id)
        )
        return result.scalar_one() or 0

    async def get_by_project(self, project_id: str, version: int | None = None) -> list[Page]:
        """Get pages for a project.
        
        Args:
            project_id: The project ID
            version: Specific version to get. If None, gets latest version.
        """
        if version is None:
            version = await self.get_max_version(project_id)
        
        if version == 0:
            return []
        
        result = await self.session.execute(
            select(Page)
            .where(Page.project_id == project_id, Page.version == version)
            .order_by(Page.depth.asc(), Page.url.asc())
        )
        return list(result.scalars().all())

    async def get_fingerprints(self, project_id: str) -> dict[str, dict]:
        """Get fingerprint data for latest version pages in a project."""
        pages = await self.get_by_project(project_id)
        return {page.url: page.to_fingerprint_dict() for page in pages}

    async def save(self, page: Page) -> Page:
        """Save a single page."""
        self.session.add(page)
        await self.session.flush()
        return page

    async def save_many(self, pages: list[Page]) -> None:
        """Save multiple pages."""
        self.session.add_all(pages)
        await self.session.flush()

    async def delete_by_project(self, project_id: str) -> int:
        """Delete all pages for a project (all versions)."""
        result = await self.session.execute(
            delete(Page).where(Page.project_id == project_id)
        )
        return result.rowcount

    async def get_by_url(self, project_id: str, url: str, version: int | None = None) -> Page | None:
        """Get a page by URL within a project.
        
        Args:
            project_id: The project ID
            url: The page URL
            version: Specific version. If None, gets latest version.
        """
        if version is None:
            version = await self.get_max_version(project_id)
        
        if version == 0:
            return None
        
        result = await self.session.execute(
            select(Page).where(
                Page.project_id == project_id,
                Page.url == url,
                Page.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def count_by_project(self, project_id: str, version: int | None = None) -> int:
        """Count pages for a project version.
        
        Args:
            project_id: The project ID  
            version: Specific version. If None, counts latest version.
        """
        if version is None:
            version = await self.get_max_version(project_id)
        
        if version == 0:
            return 0
        
        result = await self.session.execute(
            select(func.count()).select_from(Page).where(
                Page.project_id == project_id,
                Page.version == version,
            )
        )
        return result.scalar_one()


class PostgresCrawlJobRepository:
    """PostgreSQL implementation of crawl job repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, job_id: str) -> CrawlJob | None:
        """Get a crawl job by ID."""
        result = await self.session.execute(
            select(CrawlJob).where(CrawlJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def get_by_project(self, project_id: str) -> list[CrawlJob]:
        """Get all crawl jobs for a project."""
        result = await self.session.execute(
            select(CrawlJob)
            .where(CrawlJob.project_id == project_id)
            .order_by(CrawlJob.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_latest_by_project(self, project_id: str) -> CrawlJob | None:
        """Get the latest crawl job for a project."""
        result = await self.session.execute(
            select(CrawlJob)
            .where(CrawlJob.project_id == project_id)
            .order_by(CrawlJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def save(self, job: CrawlJob) -> CrawlJob:
        """Save a crawl job."""
        self.session.add(job)
        await self.session.flush()
        return job


class PostgresGeneratedFileRepository:
    """PostgreSQL implementation of generated file repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_project(self, project_id: str) -> GeneratedFile | None:
        """Get the generated file for a project."""
        result = await self.session.execute(
            select(GeneratedFile).where(GeneratedFile.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def save(self, file: GeneratedFile) -> GeneratedFile:
        """Save a generated file."""
        # Check if one already exists
        existing = await self.get_by_project(file.project_id)
        if existing:
            existing.content = file.content
            existing.content_hash = file.content_hash
            existing.generated_at = datetime.now(timezone.utc)
            return existing
        self.session.add(file)
        await self.session.flush()
        return file

    async def delete_by_project(self, project_id: str) -> bool:
        """Delete the generated file for a project."""
        result = await self.session.execute(
            delete(GeneratedFile).where(GeneratedFile.project_id == project_id)
        )
        return result.rowcount > 0


class PostgresGeneratedFileVersionRepository:
    """PostgreSQL implementation of generated file version repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_versions(self, project_id: str) -> list[GeneratedFileVersion]:
        """Get all versions for a project, ordered by version desc."""
        result = await self.session.execute(
            select(GeneratedFileVersion)
            .where(GeneratedFileVersion.project_id == project_id)
            .order_by(GeneratedFileVersion.version.desc())
        )
        return list(result.scalars().all())

    async def get_by_version(self, project_id: str, version: int) -> GeneratedFileVersion | None:
        """Get a specific version for a project."""
        result = await self.session.execute(
            select(GeneratedFileVersion).where(
                GeneratedFileVersion.project_id == project_id,
                GeneratedFileVersion.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def get_latest(self, project_id: str) -> GeneratedFileVersion | None:
        """Get the latest version for a project."""
        result = await self.session.execute(
            select(GeneratedFileVersion)
            .where(GeneratedFileVersion.project_id == project_id)
            .order_by(GeneratedFileVersion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def save(self, version: GeneratedFileVersion) -> GeneratedFileVersion:
        """Save a version."""
        self.session.add(version)
        await self.session.flush()
        return version
