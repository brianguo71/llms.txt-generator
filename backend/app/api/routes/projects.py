"""Project management routes."""

import logging
import random
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, HttpUrl
from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.config import get_settings
from app.models import CrawlJob, GeneratedFileVersion, Project
from app.repositories import (
    PostgresCrawlJobRepository,
    PostgresProjectRepository,
)
from app.services.url_validator import URLValidator
from app.workers.tasks import initial_crawl

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


class CreateProjectRequest(BaseModel):
    """Request to create a new project."""

    url: HttpUrl
    name: str | None = None


class ProjectResponse(BaseModel):
    """Project information response."""

    id: str
    url: str
    name: str
    status: str
    created_at: str
    last_updated_at: str | None = None  # When llms.txt was last regenerated

    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    """List of projects response."""

    projects: list[ProjectResponse]
    total: int


class CrawlJobResponse(BaseModel):
    """Crawl job information response."""

    id: str
    status: str
    trigger_reason: str
    pages_crawled: int
    pages_changed: int
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None


class CrawlProgressResponse(BaseModel):
    """Real-time crawl progress response."""

    stage: str  # CRAWL, SUMMARIZE, GENERATE, COMPLETE
    current: int
    total: int
    percent: float
    elapsed_seconds: float
    eta_seconds: float | None = None
    current_url: str | None = None
    extra: str | None = None
    updated_at: str | None = None


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: CreateProjectRequest,
    db: DbSession,
) -> ProjectResponse:
    """Create a new project and start initial crawl."""
    project_repo = PostgresProjectRepository(db)
    job_repo = PostgresCrawlJobRepository(db)

    # Validate URL is reachable and has HTML content
    url_str = str(request.url).rstrip("/")
    validator = URLValidator()
    validation = await validator.validate(url_str)
    
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation.error_message,
        )

    # Use final URL after redirects (e.g., http → https)
    url_str = validation.final_url or url_str

    # Check for duplicates
    existing_project = await project_repo.get_by_url(url_str)
    if existing_project:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A project with this URL already exists",
        )

    # Create project with native change detection
    project_name = request.name or validation.title or url_str
    
    # Stagger lightweight checks: random offset within interval to spread load
    lightweight_interval = settings.lightweight_check_interval_minutes
    random_offset_seconds = random.randint(0, lightweight_interval * 60)
    
    project = Project(
        url=url_str,
        name=project_name,
        check_interval_hours=24,  # Start with daily checks
        next_check_at=datetime.now(timezone.utc) + timedelta(hours=24),
        next_lightweight_check_at=datetime.now(timezone.utc) + timedelta(seconds=random_offset_seconds),
    )
    await project_repo.save(project)

    # Create crawl job
    crawl_job = CrawlJob(
        project_id=project.id,
        trigger_reason="initial",
    )
    await job_repo.save(crawl_job)

    # IMPORTANT: Commit before dispatching Celery task to avoid race condition
    # The task might run before the implicit commit at end of request
    await db.commit()

    # Trigger async crawl
    task = initial_crawl.delay(project.id, crawl_job.id)
    crawl_job.celery_task_id = task.id
    await job_repo.save(crawl_job)

    return ProjectResponse(
        id=project.id,
        url=project.url,
        name=project.name,
        status=project.status,
        created_at=project.created_at.isoformat(),
        last_updated_at=None,  # No versions yet for new project
    )


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    db: DbSession,
) -> ProjectListResponse:
    """List all projects."""
    from sqlalchemy import desc, select
    
    project_repo = PostgresProjectRepository(db)
    projects = await project_repo.get_all()

    project_responses = []
    for project in projects:
        # Get the latest version's generated_at
        latest_version_query = (
            select(GeneratedFileVersion.generated_at)
            .where(GeneratedFileVersion.project_id == project.id)
            .order_by(desc(GeneratedFileVersion.version))
            .limit(1)
        )
        result = await db.execute(latest_version_query)
        latest_generated_at = result.scalar_one_or_none()

        project_responses.append(
            ProjectResponse(
                id=project.id,
                url=project.url,
                name=project.name,
                status=project.status,
                created_at=project.created_at.isoformat(),
                last_updated_at=latest_generated_at.isoformat() if latest_generated_at else None,
            )
        )

    return ProjectListResponse(projects=project_responses, total=len(project_responses))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: DbSession,
) -> ProjectResponse:
    """Get a specific project."""
    from sqlalchemy import desc, select
    
    project_repo = PostgresProjectRepository(db)
    project = await project_repo.get_by_id(project_id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Get the latest version's generated_at
    latest_version_query = (
        select(GeneratedFileVersion.generated_at)
        .where(GeneratedFileVersion.project_id == project.id)
        .order_by(desc(GeneratedFileVersion.version))
        .limit(1)
    )
    result = await db.execute(latest_version_query)
    latest_generated_at = result.scalar_one_or_none()

    return ProjectResponse(
        id=project.id,
        url=project.url,
        name=project.name,
        status=project.status,
        created_at=project.created_at.isoformat(),
        last_updated_at=latest_generated_at.isoformat() if latest_generated_at else None,
    )


@router.post("/{project_id}/recrawl", response_model=CrawlJobResponse)
async def recrawl_project(
    project_id: str,
    db: DbSession,
) -> CrawlJobResponse:
    """Trigger a re-crawl of the project's website."""
    project_repo = PostgresProjectRepository(db)
    job_repo = PostgresCrawlJobRepository(db)

    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Check if there's already a crawl in progress
    if project.status in ("pending", "crawling"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A crawl is already in progress for this project",
        )

    # Update project status
    project.status = "pending"
    await project_repo.save(project)

    # Create new crawl job
    crawl_job = CrawlJob(
        project_id=project.id,
        trigger_reason="manual",
    )
    await job_repo.save(crawl_job)

    # Trigger async crawl
    task = initial_crawl.delay(project.id, crawl_job.id)
    crawl_job.celery_task_id = task.id
    await job_repo.save(crawl_job)

    return CrawlJobResponse(
        id=crawl_job.id,
        status=crawl_job.status,
        trigger_reason=crawl_job.trigger_reason,
        pages_crawled=crawl_job.pages_crawled,
        pages_changed=crawl_job.pages_changed,
        started_at=crawl_job.started_at.isoformat() if crawl_job.started_at else None,
        completed_at=crawl_job.completed_at.isoformat() if crawl_job.completed_at else None,
        error_message=crawl_job.error_message,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    db: DbSession,
) -> None:
    """Delete a project."""
    project_repo = PostgresProjectRepository(db)
    project = await project_repo.get_by_id(project_id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    await project_repo.delete(project_id)


@router.get("/{project_id}/jobs", response_model=list[CrawlJobResponse])
async def list_crawl_jobs(
    project_id: str,
    db: DbSession,
) -> list[CrawlJobResponse]:
    """List crawl jobs for a project."""
    project_repo = PostgresProjectRepository(db)
    job_repo = PostgresCrawlJobRepository(db)

    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    jobs = await job_repo.get_by_project(project_id)

    return [
        CrawlJobResponse(
            id=job.id,
            status=job.status,
            trigger_reason=job.trigger_reason,
            pages_crawled=job.pages_crawled,
            pages_changed=job.pages_changed,
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            error_message=job.error_message,
        )
        for job in jobs
    ]


@router.get("/{project_id}/progress", response_model=CrawlProgressResponse | None)
async def get_crawl_progress(
    project_id: str,
    db: DbSession,
) -> CrawlProgressResponse | None:
    """Get real-time crawl progress for a project.
    
    Returns current progress if a crawl is in progress, or None if no active crawl.
    Frontend should poll this endpoint every 1-2 seconds while crawling.
    """
    from app.services.progress import get_progress_service
    
    project_repo = PostgresProjectRepository(db)
    project = await project_repo.get_by_id(project_id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    progress_service = get_progress_service()
    progress = progress_service.get(project_id)
    
    if not progress:
        return None
    
    return CrawlProgressResponse(
        stage=progress["stage"],
        current=progress["current"],
        total=progress["total"],
        percent=progress["percent"],
        elapsed_seconds=progress["elapsed_seconds"],
        eta_seconds=progress.get("eta_seconds"),
        current_url=progress.get("current_url"),
        extra=progress.get("extra"),
        updated_at=progress.get("updated_at"),
    )
