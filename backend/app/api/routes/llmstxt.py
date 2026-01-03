"""llms.txt generation and retrieval routes."""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.api.deps import DbSession
from app.repositories import (
    PostgresGeneratedFileRepository,
    PostgresGeneratedFileVersionRepository,
    PostgresProjectRepository,
)

router = APIRouter()


class LlmsTxtResponse(BaseModel):
    """llms.txt content response."""

    content: str
    generated_at: str
    content_hash: str


class LlmsTxtVersionSummary(BaseModel):
    """Summary of a llms.txt version (without content)."""

    version: int
    generated_at: str
    content_hash: str
    trigger_reason: str | None = None


class LlmsTxtVersionResponse(BaseModel):
    """Full llms.txt version with content."""

    version: int
    content: str
    generated_at: str
    content_hash: str
    trigger_reason: str | None = None


class LlmsTxtVersionListResponse(BaseModel):
    """List of llms.txt versions."""

    versions: list[LlmsTxtVersionSummary]
    total: int


@router.get("/projects/{project_id}/llmstxt", response_model=LlmsTxtResponse)
async def get_llmstxt(
    project_id: str,
    db: DbSession,
) -> LlmsTxtResponse:
    """Get the generated llms.txt content for a project."""
    project_repo = PostgresProjectRepository(db)
    file_repo = PostgresGeneratedFileRepository(db)

    # Verify project exists
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Get generated file
    generated_file = await file_repo.get_by_project(project_id)
    if not generated_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="llms.txt not yet generated. Please wait for crawl to complete.",
        )

    return LlmsTxtResponse(
        content=generated_file.content,
        generated_at=generated_file.generated_at.isoformat(),
        content_hash=generated_file.content_hash,
    )


@router.get("/projects/{project_id}/llmstxt/download")
async def download_llmstxt(
    project_id: str,
    db: DbSession,
) -> PlainTextResponse:
    """Download the llms.txt file."""
    project_repo = PostgresProjectRepository(db)
    file_repo = PostgresGeneratedFileRepository(db)

    # Verify project exists
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Get generated file
    generated_file = await file_repo.get_by_project(project_id)
    if not generated_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="llms.txt not yet generated",
        )

    return PlainTextResponse(
        content=generated_file.content,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="llms.txt"',
        },
    )


@router.get("/projects/{project_id}/llmstxt/versions", response_model=LlmsTxtVersionListResponse)
async def list_llmstxt_versions(
    project_id: str,
    db: DbSession,
) -> LlmsTxtVersionListResponse:
    """List all versions of the llms.txt file for a project."""
    project_repo = PostgresProjectRepository(db)
    version_repo = PostgresGeneratedFileVersionRepository(db)

    # Verify project exists
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Get all versions
    versions = await version_repo.get_versions(project_id)

    return LlmsTxtVersionListResponse(
        versions=[
            LlmsTxtVersionSummary(
                version=v.version,
                generated_at=v.generated_at.isoformat(),
                content_hash=v.content_hash,
                trigger_reason=v.trigger_reason,
            )
            for v in versions
        ],
        total=len(versions),
    )


@router.get("/projects/{project_id}/llmstxt/versions/{version}", response_model=LlmsTxtVersionResponse)
async def get_llmstxt_version(
    project_id: str,
    version: int,
    db: DbSession,
) -> LlmsTxtVersionResponse:
    """Get a specific version of the llms.txt file."""
    project_repo = PostgresProjectRepository(db)
    version_repo = PostgresGeneratedFileVersionRepository(db)

    # Verify project exists
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Get specific version
    file_version = await version_repo.get_by_version(project_id, version)
    if not file_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version} not found",
        )

    return LlmsTxtVersionResponse(
        version=file_version.version,
        content=file_version.content,
        generated_at=file_version.generated_at.isoformat(),
        content_hash=file_version.content_hash,
        trigger_reason=file_version.trigger_reason,
    )
