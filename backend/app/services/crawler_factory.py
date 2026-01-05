"""Factory for creating crawler service instances based on configuration."""

import logging
from typing import Any, Callable

from app.config import Settings

logger = logging.getLogger(__name__)


def get_crawler_service(
    settings: Settings,
    on_progress: Callable[[int, int, str], None] | None = None,
):
    """Create and return the appropriate crawler service based on settings.
    
    Args:
        settings: Application settings (checks settings.crawler_backend)
        on_progress: Optional callback for progress reporting (crawled, total, url)
        
    Returns:
        A crawler service instance (FirecrawlCrawler or ScrapyCrawler)
        
    Raises:
        ValueError: If required API key is missing for the selected backend
    """
    if settings.crawler_backend == "scrapy":
        logger.info("Using Scrapy crawler backend")
        from app.services.scrapy_crawler import ScrapyCrawler
        return ScrapyCrawler(settings, on_progress)
    else:
        logger.info("Using Firecrawl crawler backend")
        from app.services.firecrawl_crawler import FirecrawlCrawler
        return FirecrawlCrawler(settings, on_progress)

