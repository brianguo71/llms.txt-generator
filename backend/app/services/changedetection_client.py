"""Client for interacting with changedetection.io API."""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class WatchConfig:
    """Configuration for a changedetection.io watch."""
    url: str
    tag: str | None = None
    title: str | None = None
    notification_urls: list[str] | None = None
    check_interval_minutes: int = 5
    proxy_url: str | None = None


class ChangeDetectionClient:
    """Client for changedetection.io REST API.
    
    API Documentation: https://github.com/dgtlmoon/changedetection.io/wiki/API-Reference
    """

    def __init__(self, settings: Settings):
        self.base_url = settings.changedetection_url.rstrip("/")
        self.api_key = settings.changedetection_api_key
        self.proxy_url = settings.webshare_proxy_url
        self.webhook_base_url = settings.webhook_base_url

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with optional API key."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: dict | None = None,
        timeout: float = 30.0,
    ) -> dict | list | None:
        """Make HTTP request to changedetection.io API."""
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=self._get_headers(),
                    json=json_data,
                )
                response.raise_for_status()
                
                if response.content:
                    return response.json()
                return None
                
        except httpx.HTTPStatusError as e:
            logger.error(f"ChangeDetection API error: {e.response.status_code} - {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"ChangeDetection API request failed: {e}")
            raise

    def create_watch(self, config: WatchConfig, project_id: str) -> str:
        """Create a new watch for a URL.
        
        Args:
            config: Watch configuration
            project_id: Our project ID (used in tag and webhook)
            
        Returns:
            The watch UUID from changedetection.io
        """
        # Build webhook URL that includes our project ID
        webhook_url = f"{self.webhook_base_url}/api/webhooks/change-detected?project_id={project_id}"
        
        watch_data = {
            "url": config.url,
            "tag": config.tag or f"project:{project_id}",
            "title": config.title,
            "time_between_check": {"minutes": config.check_interval_minutes},
            "notification_urls": [webhook_url],
            # Use Playwright for JavaScript rendering support
            "fetch_backend": "html_webdriver",
        }
        
        # Add proxy if configured
        if config.proxy_url or self.proxy_url:
            watch_data["proxy"] = config.proxy_url or self.proxy_url
        
        logger.info(f"Creating watch for {config.url} with project_id={project_id}")
        
        result = self._make_request("POST", "watch", json_data=watch_data)
        
        if result and "uuid" in result:
            watch_id = result["uuid"]
            logger.info(f"Created watch {watch_id} for {config.url}")
            return watch_id
        
        raise ValueError(f"Failed to create watch: {result}")

    def delete_watch(self, watch_id: str) -> None:
        """Delete a watch by UUID."""
        logger.info(f"Deleting watch {watch_id}")
        self._make_request("DELETE", f"watch/{watch_id}")
        logger.info(f"Deleted watch {watch_id}")

    def get_watch(self, watch_id: str) -> dict[str, Any]:
        """Get watch details by UUID."""
        result = self._make_request("GET", f"watch/{watch_id}")
        return result or {}

    def list_watches(self, tag: str | None = None) -> list[dict[str, Any]]:
        """List all watches, optionally filtered by tag."""
        result = self._make_request("GET", "watch")
        
        if not result:
            return []
        
        # API returns {uuid: watch_data, ...} so we need to include the uuid in each watch
        if isinstance(result, dict):
            watches = []
            for uuid, watch_data in result.items():
                watch_data["uuid"] = uuid
                watches.append(watch_data)
        else:
            watches = result
        
        if tag:
            watches = [w for w in watches if w.get("tag") == tag]
        
        return watches

    def get_watches_by_project(self, project_id: str) -> list[dict[str, Any]]:
        """Get all watches for a specific project."""
        tag = f"project:{project_id}"
        return self.list_watches(tag=tag)

    def delete_watches_by_project(self, project_id: str) -> int:
        """Delete all watches for a project.
        
        Returns:
            Number of watches deleted
        """
        watches = self.get_watches_by_project(project_id)
        
        for watch in watches:
            watch_id = watch.get("uuid")
            if watch_id:
                self.delete_watch(watch_id)
        
        logger.info(f"Deleted {len(watches)} watches for project {project_id}")
        return len(watches)

    def update_watch_proxy(self, watch_id: str, proxy_url: str) -> None:
        """Update the proxy for a watch."""
        self._make_request("PUT", f"watch/{watch_id}", json_data={"proxy": proxy_url})
        logger.info(f"Updated proxy for watch {watch_id}")

    def trigger_check(self, watch_id: str) -> None:
        """Trigger an immediate check for a watch."""
        self._make_request("POST", f"watch/{watch_id}/trigger-check")
        logger.info(f"Triggered check for watch {watch_id}")

    def is_healthy(self) -> bool:
        """Check if changedetection.io is reachable and API key is valid."""
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(
                    f"{self.base_url}/api/v1/systeminfo",
                    headers=self._get_headers(),
                )
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"ChangeDetection health check failed: {e}")
            return False


def get_changedetection_client(settings: Settings) -> ChangeDetectionClient:
    """Factory function to get ChangeDetectionClient instance."""
    return ChangeDetectionClient(settings)

