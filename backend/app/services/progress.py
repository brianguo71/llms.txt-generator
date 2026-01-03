"""Service for tracking crawl progress in Redis."""

import json
from datetime import datetime, timezone
from typing import Any

import redis

from app.config import get_settings


class ProgressService:
    """Manages crawl progress storage in Redis."""

    def __init__(self):
        settings = get_settings()
        self.redis = redis.from_url(settings.redis_url)
        self.ttl = 3600  # Progress expires after 1 hour

    def _key(self, project_id: str) -> str:
        """Generate Redis key for project progress."""
        return f"crawl_progress:{project_id}"

    def update(
        self,
        project_id: str,
        stage: str,
        current: int,
        total: int,
        elapsed_seconds: float,
        eta_seconds: float | None = None,
        current_url: str | None = None,
        extra: str | None = None,
    ) -> None:
        """Update progress for a project.
        
        Args:
            project_id: The project being crawled
            stage: Current stage (CRAWL, SUMMARIZE, GENERATE)
            current: Current item number
            total: Total items to process
            elapsed_seconds: Time elapsed in this stage
            eta_seconds: Estimated time remaining
            current_url: URL currently being processed
            extra: Additional info
        """
        progress = {
            "stage": stage,
            "current": current,
            "total": total,
            "percent": round((current / total * 100), 1) if total > 0 else 0,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "eta_seconds": round(eta_seconds, 1) if eta_seconds else None,
            "current_url": current_url,
            "extra": extra,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.redis.setex(
            self._key(project_id),
            self.ttl,
            json.dumps(progress),
        )

    def get(self, project_id: str) -> dict[str, Any] | None:
        """Get current progress for a project.
        
        Returns:
            Progress dict or None if no progress stored.
        """
        data = self.redis.get(self._key(project_id))
        if data:
            return json.loads(data)
        return None

    def clear(self, project_id: str) -> None:
        """Clear progress for a project."""
        self.redis.delete(self._key(project_id))


# Singleton instance
_progress_service: ProgressService | None = None


def get_progress_service() -> ProgressService:
    """Get or create progress service singleton."""
    global _progress_service
    if _progress_service is None:
        _progress_service = ProgressService()
    return _progress_service

