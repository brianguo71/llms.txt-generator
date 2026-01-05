"""Celery application configuration."""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "llmstxt",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
    # Result backend
    result_expires=3600,  # 1 hour
    # Beat schedule for periodic change detection
    beat_schedule={
        # Full rescrape check (every hour, dispatches due projects)
        "check-projects-for-changes": {
            "task": "app.workers.tasks.check_projects_for_changes",
            "schedule": crontab(minute=0),  # Run every hour, on the hour
        },
        # Lightweight check dispatcher (every minute, dispatches due projects)
        "dispatch-lightweight-checks": {
            "task": "app.workers.tasks.dispatch_lightweight_checks",
            "schedule": crontab(),  # Every minute
        },
    },
)

