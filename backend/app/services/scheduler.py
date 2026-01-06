"""Redis-based scheduler using sorted sets for O(log N) scheduling.

Keys:
- schedule:full_check - Projects due for full rescrape (24h+ interval, adaptive)
- schedule:lightweight_check - Projects due for lightweight HEAD checks (5 min interval)
- schedule:cooldowns - Projects in cooldown period (can't trigger rescrape)
- schedule:intervals - Hash storing per-project check intervals for adaptive backoff
"""

import logging
from datetime import datetime, timedelta, timezone

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)

# Redis keys
FULL_CHECK_KEY = "schedule:full_check"
LIGHTWEIGHT_CHECK_KEY = "schedule:lightweight_check"
COOLDOWN_KEY = "schedule:cooldowns"
INTERVALS_KEY = "schedule:intervals"

# Default intervals
DEFAULT_CHECK_INTERVAL_HOURS = 24
MIN_CHECK_INTERVAL_HOURS = 6
MAX_CHECK_INTERVAL_HOURS = 168  # 7 days


class SchedulerService:
    """Redis-based scheduler using sorted sets for efficient scheduling."""

    def __init__(self):
        settings = get_settings()
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)
        self.lightweight_interval_minutes = settings.lightweight_check_interval_minutes
        self.cooldown_hours = settings.full_rescrape_cooldown_hours

    # =========================================================================
    # Full Check Scheduling (Adaptive Backoff)
    # =========================================================================

    def schedule_full_check(
        self,
        project_id: str,
        interval_hours: int | None = None,
        run_at: datetime | None = None,
    ) -> datetime:
        """Schedule a project for full rescrape check.

        Args:
            project_id: The project to schedule
            interval_hours: Hours until next check (uses stored interval if None)
            run_at: Explicit run time (overrides interval_hours)

        Returns:
            The scheduled datetime
        """
        if run_at is None:
            if interval_hours is None:
                interval_hours = self.get_check_interval(project_id)
            run_at = datetime.now(timezone.utc) + timedelta(hours=interval_hours)

        score = run_at.timestamp()
        self.redis.zadd(FULL_CHECK_KEY, {project_id: score})
        logger.debug(f"Scheduled full check for {project_id} at {run_at}")
        return run_at

    def get_due_full_checks(self, limit: int = 100) -> list[str]:
        """Get project IDs due for full check, removing them atomically.

        Uses ZPOPMIN for atomic removal to prevent duplicate dispatches.

        Args:
            limit: Maximum number of projects to return

        Returns:
            List of project IDs due for checking
        """
        now = datetime.now(timezone.utc).timestamp()

        # Get all due projects (score <= now)
        due = self.redis.zrangebyscore(FULL_CHECK_KEY, 0, now, start=0, num=limit)

        if not due:
            return []

        # Atomically remove them using pipeline
        pipe = self.redis.pipeline()
        for project_id in due:
            pipe.zrem(FULL_CHECK_KEY, project_id)
        pipe.execute()

        return due

    def cancel_full_check(self, project_id: str) -> bool:
        """Cancel a scheduled full check.

        Returns:
            True if the project was scheduled and is now cancelled
        """
        removed = self.redis.zrem(FULL_CHECK_KEY, project_id)
        return removed > 0

    # =========================================================================
    # Lightweight Check Scheduling (Fixed Interval)
    # =========================================================================

    def schedule_lightweight_check(
        self,
        project_id: str,
        interval_minutes: int | None = None,
    ) -> datetime:
        """Schedule a project for lightweight HEAD check.

        Args:
            project_id: The project to schedule
            interval_minutes: Minutes until next check (uses default if None)

        Returns:
            The scheduled datetime
        """
        if interval_minutes is None:
            interval_minutes = self.lightweight_interval_minutes

        run_at = datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)
        score = run_at.timestamp()
        self.redis.zadd(LIGHTWEIGHT_CHECK_KEY, {project_id: score})
        logger.info(f"Scheduled lightweight check for {project_id} at {run_at}")
        return run_at

    def get_due_lightweight_checks(self, limit: int = 500) -> list[str]:
        """Get project IDs due for lightweight check, removing them atomically.

        Args:
            limit: Maximum number of projects to return

        Returns:
            List of project IDs due for checking
        """
        now = datetime.now(timezone.utc).timestamp()

        # Get all due projects
        due = self.redis.zrangebyscore(LIGHTWEIGHT_CHECK_KEY, 0, now, start=0, num=limit)

        if not due:
            return []

        # Atomically remove them
        pipe = self.redis.pipeline()
        for project_id in due:
            pipe.zrem(LIGHTWEIGHT_CHECK_KEY, project_id)
        pipe.execute()

        return due

    def cancel_lightweight_check(self, project_id: str) -> bool:
        """Cancel a scheduled lightweight check."""
        removed = self.redis.zrem(LIGHTWEIGHT_CHECK_KEY, project_id)
        return removed > 0

    # =========================================================================
    # Adaptive Backoff (Check Intervals)
    # =========================================================================

    def get_check_interval(self, project_id: str) -> int:
        """Get the current check interval for a project.

        Returns:
            Interval in hours (default 24)
        """
        interval = self.redis.hget(INTERVALS_KEY, project_id)
        if interval:
            return int(interval)
        return DEFAULT_CHECK_INTERVAL_HOURS

    def set_check_interval(self, project_id: str, hours: int) -> None:
        """Set the check interval for a project."""
        # Clamp to valid range
        hours = max(MIN_CHECK_INTERVAL_HOURS, min(hours, MAX_CHECK_INTERVAL_HOURS))
        self.redis.hset(INTERVALS_KEY, project_id, hours)

    def apply_backoff(self, project_id: str, changed: bool) -> int:
        """Apply adaptive backoff based on whether content changed.

        Args:
            project_id: The project to update
            changed: Whether significant changes were detected

        Returns:
            New interval in hours
        """
        current = self.get_check_interval(project_id)

        if changed:
            # Reset to minimum (more frequent checks)
            new_interval = MIN_CHECK_INTERVAL_HOURS
        else:
            # Double interval, cap at max (less frequent checks)
            new_interval = min(current * 2, MAX_CHECK_INTERVAL_HOURS)

        self.set_check_interval(project_id, new_interval)
        logger.info(
            f"Backoff for {project_id}: {current}h -> {new_interval}h (changed={changed})"
        )
        return new_interval

    # =========================================================================
    # Cooldown Management
    # =========================================================================

    def set_cooldown(self, project_id: str, hours: int | None = None) -> datetime:
        """Set a cooldown period for a project (prevents rescrape triggers).

        Args:
            project_id: The project to set cooldown for
            hours: Cooldown duration (uses config default if None)

        Returns:
            When the cooldown expires
        """
        if hours is None:
            hours = self.cooldown_hours

        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        score = expires_at.timestamp()
        self.redis.zadd(COOLDOWN_KEY, {project_id: score})
        return expires_at

    def is_in_cooldown(self, project_id: str) -> bool:
        """Check if a project is in cooldown period.

        Returns:
            True if project cannot trigger a rescrape
        """
        score = self.redis.zscore(COOLDOWN_KEY, project_id)
        if score is None:
            return False

        # Check if cooldown has expired
        now = datetime.now(timezone.utc).timestamp()
        if score <= now:
            # Cooldown expired, remove it
            self.redis.zrem(COOLDOWN_KEY, project_id)
            return False

        return True

    def get_cooldown_remaining(self, project_id: str) -> float | None:
        """Get remaining cooldown time in hours.

        Returns:
            Hours remaining, or None if not in cooldown
        """
        score = self.redis.zscore(COOLDOWN_KEY, project_id)
        if score is None:
            return None

        now = datetime.now(timezone.utc).timestamp()
        remaining = score - now
        if remaining <= 0:
            self.redis.zrem(COOLDOWN_KEY, project_id)
            return None

        return remaining / 3600  # Convert to hours

    def clear_cooldown(self, project_id: str) -> None:
        """Clear cooldown for a project."""
        self.redis.zrem(COOLDOWN_KEY, project_id)

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def schedule_project(self, project_id: str) -> dict:
        """Schedule a project for both full and lightweight checks.

        Call this when a project completes initial crawl or is re-enabled.

        Returns:
            Dict with scheduled times
        """
        full_at = self.schedule_full_check(project_id)
        lightweight_at = self.schedule_lightweight_check(project_id)

        return {
            "project_id": project_id,
            "full_check_at": full_at.isoformat(),
            "lightweight_check_at": lightweight_at.isoformat(),
        }

    def unschedule_project(self, project_id: str) -> None:
        """Remove a project from all schedules.

        Call this when a project is deleted or disabled.
        """
        pipe = self.redis.pipeline()
        pipe.zrem(FULL_CHECK_KEY, project_id)
        pipe.zrem(LIGHTWEIGHT_CHECK_KEY, project_id)
        pipe.zrem(COOLDOWN_KEY, project_id)
        pipe.hdel(INTERVALS_KEY, project_id)
        pipe.execute()
        logger.info(f"Unscheduled project {project_id}")

    def get_schedule_stats(self) -> dict:
        """Get statistics about current schedules.

        Returns:
            Dict with counts and queue depths
        """
        now = datetime.now(timezone.utc).timestamp()

        # Count due items
        full_due = self.redis.zcount(FULL_CHECK_KEY, 0, now)
        full_total = self.redis.zcard(FULL_CHECK_KEY)

        lightweight_due = self.redis.zcount(LIGHTWEIGHT_CHECK_KEY, 0, now)
        lightweight_total = self.redis.zcard(LIGHTWEIGHT_CHECK_KEY)

        cooldowns_active = self.redis.zcount(COOLDOWN_KEY, now, "+inf")
        intervals_stored = self.redis.hlen(INTERVALS_KEY)

        return {
            "full_check": {"due": full_due, "scheduled": full_total},
            "lightweight_check": {"due": lightweight_due, "scheduled": lightweight_total},
            "cooldowns_active": cooldowns_active,
            "intervals_stored": intervals_stored,
        }

    # =========================================================================
    # Migration Helpers
    # =========================================================================

    def migrate_from_db(
        self,
        projects: list[dict],
    ) -> int:
        """Migrate scheduling data from database to Redis.

        Args:
            projects: List of dicts with project_id, next_check_at,
                     check_interval_hours, next_lightweight_check_at

        Returns:
            Number of projects migrated
        """
        pipe = self.redis.pipeline()
        count = 0

        for p in projects:
            project_id = p["project_id"]

            # Full check schedule
            if p.get("next_check_at"):
                score = p["next_check_at"].timestamp()
                pipe.zadd(FULL_CHECK_KEY, {project_id: score})

            # Check interval
            if p.get("check_interval_hours"):
                pipe.hset(INTERVALS_KEY, project_id, p["check_interval_hours"])

            # Lightweight check schedule
            if p.get("next_lightweight_check_at"):
                score = p["next_lightweight_check_at"].timestamp()
                pipe.zadd(LIGHTWEIGHT_CHECK_KEY, {project_id: score})

            count += 1

        pipe.execute()
        logger.info(f"Migrated {count} projects to Redis scheduler")
        return count


# Singleton instance
_scheduler: SchedulerService | None = None


def get_scheduler() -> SchedulerService:
    """Get or create scheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulerService()
    return _scheduler

