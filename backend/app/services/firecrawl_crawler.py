"""Web crawler service using Firecrawl API."""

import hashlib
import logging
from typing import Any, Callable

from firecrawl import Firecrawl
from firecrawl.v2.types import ScrapeOptions

from app.config import Settings

logger = logging.getLogger(__name__)


class FirecrawlCrawler:
    """Crawl websites using Firecrawl API for content extraction."""

    def __init__(
        self,
        settings: Settings,
        on_progress: Callable[[int, int, str], None] | None = None,
    ):
        """Initialize crawler with settings.
        
        Args:
            settings: Application settings containing Firecrawl API key
            on_progress: Optional callback for progress reporting (crawled, total, url)
        """
        if not settings.firecrawl_api_key:
            raise ValueError("FIRECRAWL_API_KEY is required")
        
        self.client = Firecrawl(api_key=settings.firecrawl_api_key)
        self.max_pages = settings.max_pages_per_crawl
        self.wait_for_ms = settings.firecrawl_wait_for_ms
        self.on_progress = on_progress

    def _report_progress(self, crawled: int, total: int, url: str) -> None:
        """Report crawl progress if callback is set."""
        if self.on_progress:
            self.on_progress(crawled, total, url)

    def crawl_website(self, start_url: str) -> list[dict[str, Any]]:
        """Crawl entire website using Firecrawl API.
        
        Uses Firecrawl's crawl() method which blocks until completion.
        Progress updates happen when processing results.
        
        Args:
            start_url: The URL to start crawling from
            
        Returns:
            List of page data dictionaries with markdown content
        """
        logger.info(f"Starting Firecrawl crawl of {start_url} (max {self.max_pages} pages)")
        
        self._report_progress(0, self.max_pages, start_url)
        
        try:
            # Blocking crawl - waits until complete
            result = self.client.crawl(
                url=start_url,
                limit=self.max_pages,
                scrape_options=ScrapeOptions(
                    formats=["markdown"],
                    only_main_content=True,
                    # Wait for JavaScript to render before capturing content
                    # Essential for JS-heavy pages like SPAs
                    wait_for=self.wait_for_ms,
                    # Bypass Firecrawl's cache to get fresh content
                    max_age=0,
                ),
                poll_interval=5,  # Check status every 5 seconds internally
            )
            
            pages = []
            # result is a CrawlJob, access .data for the list of Document objects
            data = result.data if hasattr(result, 'data') and result.data else []
            
            for i, doc in enumerate(data):
                # doc is a Document object with markdown, metadata, etc.
                meta = doc.metadata
                url = getattr(meta, 'url', '') or getattr(meta, 'source_url', '') or ''
                title = getattr(meta, 'title', '') or ''
                description = getattr(meta, 'description', '') or ''
                markdown = doc.markdown or ""
                
                # Normalize start_url for comparison
                is_homepage = self._is_homepage(url, start_url)
                
                # Calculate content hash from markdown
                content_hash = hashlib.sha256(markdown.encode()).hexdigest() if markdown else ""
                
                page_data = {
                    "url": url,
                    "title": title,
                    "description": description,
                    "markdown": markdown,
                    "content_hash": content_hash,
                    "is_homepage": is_homepage,
                    "depth": 0 if is_homepage else 1,
                }
                pages.append(page_data)
                
                # Report progress as we process results
                self._report_progress(i + 1, len(data), url)
            
            logger.info(f"Firecrawl completed: {len(pages)} pages crawled")
            return pages
            
        except Exception as e:
            logger.error(f"Firecrawl error: {e}")
            raise

    def crawl_page(self, url: str) -> dict[str, Any] | None:
        """Scrape a single page using Firecrawl API.
        
        Used for targeted re-crawls when a specific page changes.
        
        Args:
            url: The URL to scrape
            
        Returns:
            Page data dictionary or None if failed
        """
        logger.info(f"Scraping single page: {url}")
        
        try:
            # scrape returns a Document object
            doc = self.client.scrape(
                url=url,
                formats=["markdown"],
                only_main_content=True,
                # Wait for JavaScript to render before capturing content
                wait_for=self.wait_for_ms,
            )
            
            markdown = doc.markdown or ""
            meta = doc.metadata
            title = getattr(meta, 'title', '') or ''
            description = getattr(meta, 'description', '') or ''
            content_hash = hashlib.sha256(markdown.encode()).hexdigest() if markdown else ""
            
            return {
                "url": url,
                "title": title,
                "description": description,
                "markdown": markdown,
                "content_hash": content_hash,
            }
            
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return None

    def map_website(self, url: str) -> list[str]:
        """Get all URLs on a website using Firecrawl /map endpoint.
        
        This is much faster than a full crawl and returns all discoverable
        URLs on the site. Used for URL inventory tracking.
        
        Args:
            url: The website URL to map
            
        Returns:
            List of all discovered URLs on the site
        """
        logger.info(f"Mapping website URLs: {url}")
        
        try:
            result = self.client.map(url=url)
            # result has a 'links' attribute with the list of URLs or LinkResult objects
            raw_links = result.links if hasattr(result, 'links') else []
            # Convert LinkResult objects to strings if needed
            urls = []
            for link in raw_links:
                if isinstance(link, str):
                    urls.append(link)
                elif hasattr(link, 'url'):
                    urls.append(link.url)
                else:
                    # Try to convert to string
                    urls.append(str(link))
            logger.info(f"Map completed: {len(urls)} URLs discovered")
            return urls
        except Exception as e:
            logger.error(f"Error mapping {url}: {e}")
            raise

    def batch_scrape(self, urls: list[str], start_url: str = "") -> list[dict[str, Any]]:
        """Scrape multiple specific pages using Firecrawl batch API.
        
        More efficient than individual scrapes when you need content
        from a specific set of URLs.
        
        Args:
            urls: List of URLs to scrape
            start_url: The site's root URL (for homepage detection)
            
        Returns:
            List of page data dictionaries with markdown content
        """
        if not urls:
            return []
        
        logger.info(f"Batch scraping {len(urls)} URLs")
        
        try:
            # Use batch_scrape for multiple URLs
            result = self.client.batch_scrape(
                urls=urls,
                formats=["markdown"],
                only_main_content=True,
                wait_for=self.wait_for_ms,
                # Bypass Firecrawl's cache to get fresh content
                max_age=0,
            )
            
            pages = []
            # result.data contains the list of Document objects
            data = result.data if hasattr(result, 'data') and result.data else []
            
            for i, doc in enumerate(data):
                meta = doc.metadata
                url = getattr(meta, 'url', '') or getattr(meta, 'source_url', '') or ''
                title = getattr(meta, 'title', '') or ''
                description = getattr(meta, 'description', '') or ''
                markdown = doc.markdown or ""
                
                is_homepage = self._is_homepage(url, start_url) if start_url else False
                content_hash = hashlib.sha256(markdown.encode()).hexdigest() if markdown else ""
                
                page_data = {
                    "url": url,
                    "title": title,
                    "description": description,
                    "markdown": markdown,
                    "content_hash": content_hash,
                    "is_homepage": is_homepage,
                    "depth": 0 if is_homepage else 1,
                }
                pages.append(page_data)
                
                self._report_progress(i + 1, len(data), url)
            
            logger.info(f"Batch scrape completed: {len(pages)} pages")
            return pages
            
        except Exception as e:
            logger.error(f"Error in batch scrape: {e}")
            raise

    def _is_homepage(self, url: str, start_url: str) -> bool:
        """Check if a URL is the homepage of the start URL."""
        from urllib.parse import urlparse
        
        def normalize(u: str) -> str:
            parsed = urlparse(u)
            # Normalize to scheme://host/path without trailing slash
            path = parsed.path.rstrip('/') or '/'
            return f"{parsed.scheme}://{parsed.netloc}{path}".lower()
        
        return normalize(url) == normalize(start_url)

