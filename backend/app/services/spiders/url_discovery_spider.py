"""Lightweight Scrapy spider for URL discovery (no content extraction)."""

import logging
from typing import Generator
from urllib.parse import urljoin, urlparse

import scrapy
from scrapy.http import Response

logger = logging.getLogger(__name__)


class UrlDiscoverySpider(scrapy.Spider):
    """Spider that discovers all URLs on a website without extracting content.
    
    This is much faster than a full crawl since it:
    - Only extracts links, no content/markdown processing
    - Uses HEAD requests where possible
    - Optimized for speed over content quality
    """

    name = "url_discovery_spider"
    
    custom_settings = {
        'CONCURRENT_REQUESTS': 16,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 16,
        'DOWNLOAD_DELAY': 0.25,  # Faster than content crawl
        'AUTOTHROTTLE_ENABLED': True,
        'AUTOTHROTTLE_START_DELAY': 0.25,
        'AUTOTHROTTLE_MAX_DELAY': 5,
        'ROBOTSTXT_OBEY': True,
        'LOG_LEVEL': 'INFO',
        # No Playwright - we just need to discover links
        'DOWNLOAD_HANDLERS': {},  # Use default handlers (no Playwright)
    }

    def __init__(
        self,
        start_url: str,
        max_urls: int = 500,
        collected_urls: list | None = None,
        *args,
        **kwargs
    ):
        """Initialize spider.
        
        Args:
            start_url: The URL to start discovering from
            max_urls: Maximum number of URLs to discover
            collected_urls: Shared list to collect discovered URLs
        """
        super().__init__(*args, **kwargs)
        self.start_url = start_url
        self.max_urls = max_urls
        self.collected_urls = collected_urls if collected_urls is not None else []
        self.visited_urls: set[str] = set()
        self.discovered_count = 0
        
        # Parse domain for same-domain filtering
        parsed = urlparse(start_url)
        self.allowed_domains = [parsed.netloc]
        self.base_domain = parsed.netloc
        self.base_scheme = parsed.scheme

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        """Generate initial request to start URL."""
        yield scrapy.Request(
            url=self.start_url,
            callback=self.parse,
            meta={'depth': 0},
            errback=self.handle_error,
        )

    def parse(self, response: Response) -> Generator[scrapy.Request, None, None]:
        """Parse a page response to extract links."""
        # Stop if we've discovered enough URLs
        if self.discovered_count >= self.max_urls:
            from scrapy.exceptions import CloseSpider
            raise CloseSpider(f'Reached max URLs limit: {self.max_urls}')
        
        url = response.url
        normalized_url = self._normalize_url(url)
        
        # Skip if already visited
        if normalized_url in self.visited_urls:
            return
        
        # Mark as visited and record this URL
        self.visited_urls.add(normalized_url)
        self.discovered_count += 1
        self.collected_urls.append(normalized_url)
        
        if self.discovered_count % 50 == 0:
            logger.info(f"URL discovery progress: {self.discovered_count} URLs found")
        
        # Stop following if we've hit the limit
        if self.discovered_count >= self.max_urls:
            logger.info(f"Reached max URLs limit: {self.max_urls}")
            return
        
        # Follow links to discover more URLs
        depth = response.meta.get('depth', 0)
        for link in self._extract_links(response):
            normalized_link = self._normalize_url(link)
            if normalized_link not in self.visited_urls:
                # Don't mark as visited here - let parse() do it after recording
                # Scrapy's built-in request fingerprinting will deduplicate
                yield scrapy.Request(
                    url=normalized_link,
                    callback=self.parse,
                    meta={'depth': depth + 1},
                    errback=self.handle_error,
                )

    def _extract_links(self, response: Response) -> Generator[str, None, None]:
        """Extract valid same-domain links from page."""
        for href in response.css('a::attr(href)').getall():
            # Skip empty, javascript, and anchor-only links
            if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                continue
            
            # Build absolute URL
            absolute_url = urljoin(response.url, href)
            parsed = urlparse(absolute_url)
            
            # Only follow same-domain links
            if parsed.netloc != self.base_domain:
                continue
            
            # Skip common non-content paths
            path_lower = parsed.path.lower()
            skip_patterns = [
                '/wp-admin', '/wp-content', '/wp-includes',
                '/cdn-cgi/', '/api/', '/_next/',
                '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg',
                '.css', '.js', '.xml', '.json', '.ico', '.woff', '.woff2',
            ]
            if any(pattern in path_lower for pattern in skip_patterns):
                continue
            
            yield absolute_url

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)
        # Remove fragment and normalize
        path = parsed.path.rstrip('/') or '/'
        return f"{parsed.scheme}://{parsed.netloc}{path}".lower()

    def handle_error(self, failure):
        """Handle request errors."""
        logger.debug(f"Request failed during URL discovery: {failure.request.url}")

