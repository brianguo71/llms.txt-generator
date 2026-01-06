"""Celery application configuration."""

import json
import logging
import sys
from datetime import datetime, timezone

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging

from app.config import get_settings

settings = get_settings()


class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging.
    
    Outputs logs in JSON format which Railway and other platforms
    can parse to correctly identify log levels.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields if any
        if hasattr(record, "extra"):
            log_data["extra"] = record.extra
            
        return json.dumps(log_data)


@setup_logging.connect
def configure_logging(**kwargs):
    # Create handler that writes to stdout with JSON format
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # Remove default stderr handlers
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    
    # Configure Celery logger
    celery_logger = logging.getLogger("celery")
    celery_logger.handlers.clear()
    celery_logger.addHandler(handler)
    celery_logger.setLevel(logging.INFO)
    celery_logger.propagate = False
    
    # Configure app logger
    app_logger = logging.getLogger("app")
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False


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
    worker_hijack_root_logger=False,  # Don't hijack root logger (we configure it ourselves)
    worker_redirect_stdouts=True,  # Redirect stdout/stderr to our logger
    worker_redirect_stdouts_level="INFO",  # Level for redirected output
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

