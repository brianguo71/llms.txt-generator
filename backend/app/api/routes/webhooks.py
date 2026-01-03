"""Webhook endpoints for external service callbacks."""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel

from app.config import get_settings
from app.database import async_session_maker
from app.repositories import PostgresProjectRepository
from app.workers.tasks import targeted_recrawl

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

settings = get_settings()


class ChangeDetectionPayload(BaseModel):
    """Payload from changedetection.io webhook.
    
    changedetection.io sends various fields depending on configuration.
    We extract what we need for triggering regeneration.
    """
    watch_url: str | None = None
    watch_uuid: str | None = None
    current_snapshot: str | None = None
    previous_snapshot: str | None = None
    
    class Config:
        extra = "allow"  # Allow extra fields from changedetection.io


@router.post("/change-detected")
async def handle_change_detected(
    payload: ChangeDetectionPayload,
    background_tasks: BackgroundTasks,
    project_id: str = Query(..., description="Project ID from webhook URL"),
) -> dict[str, Any]:
    """Handle change detection webhook from changedetection.io.
    
    This endpoint is called when changedetection.io detects a change
    on a monitored page. We queue a targeted recrawl for the changed URL.
    """
    logger.info(f"Received change webhook for project {project_id}")
    logger.info(f"Changed URL: {payload.watch_url}")
    
    # Validate project exists
    async with async_session_maker() as session:
        project_repo = PostgresProjectRepository(session)
        project = await project_repo.get_by_id(project_id)
        
        if not project:
            logger.warning(f"Webhook received for unknown project: {project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        
        if project.status != "ready":
            logger.info(f"Project {project_id} not ready, skipping regeneration")
            return {
                "status": "skipped",
                "reason": f"Project status is {project.status}",
            }
    
    # Queue targeted recrawl for the changed URL
    if payload.watch_url:
        logger.info(f"Queueing targeted recrawl for {payload.watch_url}")
        targeted_recrawl.delay(project_id, [payload.watch_url])
        
        return {
            "status": "queued",
            "project_id": project_id,
            "changed_url": payload.watch_url,
        }
    
    return {
        "status": "no_action",
        "reason": "No watch_url in payload",
    }


@router.get("/health")
async def webhook_health() -> dict[str, str]:
    """Health check endpoint for webhook receiver."""
    return {"status": "healthy"}
