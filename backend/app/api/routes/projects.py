"""Project management routes."""

import logging

from pydantic import BaseModel, HttpUrl
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.deps import DbSession
from app.config import get_settings
from app.models import CrawlJob, Project
from app.repositories import (
    PostgresCrawlJobRepository,
    PostgresPageRepository,
    PostgresProjectRepository,
)
from app.services.changedetection_client import (
    ChangeDetectionClient,
    WatchConfig,
    get_changedetection_client,
)
from app.services.url_validator import URLValidator
from app.workers.tasks import initial_crawl

logger = logging.getLogger(__name__)
settings = get_settings()


def create_changedetection_watch(project_id: str, url: str, project_name: str) -> None:
    """Background task to create a changedetection.io watch for a project."""
    try:
        client = get_changedetection_client(settings)
        
        if not client.is_healthy():
            logger.warning("ChangeDetection.io not available, skipping watch creation")
            return
        
        config = WatchConfig(
            url=url,
            title=project_name,
            check_interval_minutes=5,
        )
        
        watch_id = client.create_watch(config, project_id)
        logger.info(f"Created changedetection watch {watch_id} for project {project_id}")
        
    except Exception as e:
        logger.error(f"Failed to create changedetection watch for project {project_id}: {e}")


def delete_changedetection_watches(project_id: str) -> None:
    """Background task to delete all changedetection.io watches for a project."""
    try:
        client = get_changedetection_client(settings)
        
        if not client.is_healthy():
            logger.warning("ChangeDetection.io not available, skipping watch deletion")
            return
        
        deleted_count = client.delete_watches_by_project(project_id)
        logger.info(f"Deleted {deleted_count} changedetection watches for project {project_id}")
        
    except Exception as e:
        logger.error(f"Failed to delete changedetection watches for project {project_id}: {e}")

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
    pages_count: int | None = None
    created_at: str

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
    background_tasks: BackgroundTasks,
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

    # Create project (use extracted title as default name if available)
    project_name = request.name or validation.title or url_str
    project = Project(
        url=url_str,
        name=project_name,
        change_detection_method="webhook",  # Uses changedetection.io
    )
    await project_repo.save(project)

    # Create crawl job
    crawl_job = CrawlJob(
        project_id=project.id,
        trigger_reason="initial",
    )
    await job_repo.save(crawl_job)

    # Trigger async crawl
    task = initial_crawl.delay(project.id, crawl_job.id)
    crawl_job.celery_task_id = task.id
    await job_repo.save(crawl_job)

    # Create changedetection.io watch in background
    background_tasks.add_task(
        create_changedetection_watch,
        project.id,
        project.url,
        project.name,
    )

    return ProjectResponse(
        id=project.id,
        url=project.url,
        name=project.name,
        status=project.status,
        created_at=project.created_at.isoformat(),
    )


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    db: DbSession,
) -> ProjectListResponse:
    """List all projects."""
    project_repo = PostgresProjectRepository(db)
    page_repo = PostgresPageRepository(db)
    projects = await project_repo.get_all()

    project_responses = []
    for project in projects:
        pages_count = await page_repo.count_by_project(project.id)

        project_responses.append(
            ProjectResponse(
                id=project.id,
                url=project.url,
                name=project.name,
                status=project.status,
                pages_count=pages_count,
                created_at=project.created_at.isoformat(),
            )
        )

    return ProjectListResponse(projects=project_responses, total=len(project_responses))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: DbSession,
) -> ProjectResponse:
    """Get a specific project."""
    project_repo = PostgresProjectRepository(db)
    page_repo = PostgresPageRepository(db)
    project = await project_repo.get_by_id(project_id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    pages_count = await page_repo.count_by_project(project.id)

    return ProjectResponse(
        id=project.id,
        url=project.url,
        name=project.name,
        status=project.status,
        pages_count=pages_count,
        created_at=project.created_at.isoformat(),
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
    background_tasks: BackgroundTasks,
) -> None:
    """Delete a project."""
    project_repo = PostgresProjectRepository(db)
    project = await project_repo.get_by_id(project_id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Delete changedetection.io watches in background
    background_tasks.add_task(delete_changedetection_watches, project_id)

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
