"""Scrapy spider for crawling websites with conditional Playwright fallback."""

import hashlib
import logging
from typing import Any, Generator
from urllib.parse import urljoin, urlparse

import html2text
import scrapy
from scrapy.http import Response

from app.services.semantic_extractor import extract_semantic_fingerprint

logger = logging.getLogger(__name__)


class WebsiteSpider(scrapy.Spider):
    """Spider that crawls websites with automatic Playwright fallback for JS-heavy pages."""

    name = "website_spider"
    
    custom_settings = {
        'CONCURRENT_REQUESTS': 8,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 8,
        'DOWNLOAD_DELAY': 0.5,
        'AUTOTHROTTLE_ENABLED': True,
        'AUTOTHROTTLE_START_DELAY': 0.5,
        'AUTOTHROTTLE_MAX_DELAY': 10,
        'ROBOTSTXT_OBEY': True,
        'LOG_LEVEL': 'INFO',
        # Playwright settings (only used when needed)
        'PLAYWRIGHT_LAUNCH_OPTIONS': {'headless': True},
        'DOWNLOAD_HANDLERS': {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        'TWISTED_REACTOR': "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    }

    def __init__(
        self,
        start_url: str,
        max_pages: int = 100,
        collected_pages: list | None = None,
        *args,
        **kwargs
    ):
        """Initialize spider.
        
        Args:
            start_url: The URL to start crawling from
            max_pages: Maximum number of pages to crawl
            collected_pages: Shared list to collect results (passed from wrapper)
        """
        super().__init__(*args, **kwargs)
        self.start_url = start_url
        self.max_pages = max_pages
        self.collected_pages = collected_pages if collected_pages is not None else []
        self.visited_urls: set[str] = set()
        self.pages_crawled = 0
        
        # Parse domain for same-domain filtering
        parsed = urlparse(start_url)
        self.allowed_domains = [parsed.netloc]
        self.base_domain = parsed.netloc
        
        # HTML to markdown converter
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = True
        self.html_converter.ignore_emphasis = False
        self.html_converter.body_width = 0  # No line wrapping

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        """Generate initial request to start URL."""
        yield scrapy.Request(
            url=self.start_url,
            callback=self.parse,
            meta={'depth': 0, 'playwright': False},
            errback=self.handle_error,
        )

    def parse(self, response: Response) -> Generator[Any, None, None]:
        """Parse a page response.
        
        If the page appears to need JavaScript rendering, retry with Playwright.
        """
        # Stop crawling if we've reached the limit
        if self.pages_crawled >= self.max_pages:
            # Close the spider to stop all pending requests
            from scrapy.exceptions import CloseSpider
            raise CloseSpider(f'Reached max pages limit: {self.max_pages}')
        
        url = response.url
        normalized_url = self._normalize_url(url)
        used_playwright = response.meta.get('playwright', False)
        
        # Skip if already processed (extracted data from)
        # Playwright retries are allowed since they're for the same page
        if normalized_url in self.visited_urls and not used_playwright:
            # Already processed this URL - skip to avoid duplicate data
            return
        
        # Check if we need Playwright (and haven't already used it)
        if not used_playwright and self._needs_playwright(response):
            logger.info(f"[PLAYWRIGHT] Retrying with browser rendering: {url}")
            # Don't mark as visited yet - the Playwright request will do that
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                meta={
                    'depth': response.meta.get('depth', 0),
                    'playwright': True,
                    'playwright_include_page': False,
                },
                dont_filter=True,
                errback=self.handle_error,
            )
            return
        
        # Log which rendering method was used
        if used_playwright:
            logger.info(f"[PLAYWRIGHT SUCCESS] Rendered with browser: {url}")
        else:
            logger.debug(f"[SCRAPY] Using standard HTTP response: {url}")
        
        # Mark as visited and increment counter
        self.visited_urls.add(normalized_url)
        self.pages_crawled += 1
        
        # Extract page data
        page_data = self._extract_page_data(response)
        if page_data:
            self.collected_pages.append(page_data)
            logger.info(f"Crawled ({self.pages_crawled}/{self.max_pages}): {url}")
        
        # Check again after incrementing - close if we've reached the limit
        if self.pages_crawled >= self.max_pages:
            logger.info(f"Reached max pages limit: {self.max_pages}")
            return
        
        # Follow links if under limit
        depth = response.meta.get('depth', 0)
        for link in self._extract_links(response):
            normalized_link = self._normalize_url(link)
            if normalized_link not in self.visited_urls:
                # Don't mark as visited here - let parse() do it after extracting data
                # Scrapy's built-in request fingerprinting will deduplicate
                yield scrapy.Request(
                    url=normalized_link,  # Use normalized URL
                    callback=self.parse,
                    meta={'depth': depth + 1, 'playwright': False},
                    errback=self.handle_error,
                )

    def _needs_playwright(self, response: Response) -> bool:
        """Detect if page needs JavaScript rendering.
        
        Checks for visible text content (excluding script/style tags).
        If too little visible content, assumes JS is needed to render.
        """
        # Extract text from visible elements only (exclude script, style, noscript)
        # Use XPath to exclude script/style content
        visible_text_parts = response.xpath(
            '//body//*[not(self::script) and not(self::style) and not(self::noscript)]/text()'
        ).getall()
        visible_text = ' '.join(t.strip() for t in visible_text_parts if t.strip())
        text_length = len(visible_text)
        
        # Trigger 1: Very little visible text content (likely JS-rendered)
        if text_length < 500:
            logger.info(f"[PLAYWRIGHT TRIGGER] Low visible text ({text_length} chars < 500): {response.url}")
            return True
        
        # Trigger 2: Explicit JS requirement messages in body
        body_text = response.css('body').get() or ''
        js_warnings = [
            'requires javascript',
            'javascript is required',
            'enable javascript',
            'please enable javascript',
            'you need to enable javascript',
        ]
        body_lower = body_text.lower()
        for warning in js_warnings:
            if warning in body_lower:
                logger.info(f"[PLAYWRIGHT TRIGGER] JS warning detected ('{warning}'): {response.url}")
                return True
        
        logger.debug(f"[NO PLAYWRIGHT] Page has sufficient visible content ({text_length} chars): {response.url}")
        return False

    def _extract_page_data(self, response: Response) -> dict[str, Any] | None:
        """Extract page data from response."""
        try:
            # Use normalized URL for consistency
            url = self._normalize_url(response.url)
            
            # Extract title
            title = response.css('title::text').get() or ''
            title = title.strip()
            
            # Extract meta description
            description = response.css('meta[name="description"]::attr(content)').get() or ''
            description = description.strip()
            
            # Get full HTML for semantic fingerprinting
            full_html = response.text
            
            # Get main content HTML and convert to markdown
            # Try to find main content area first
            main_content = (
                response.css('main').get() or
                response.css('article').get() or
                response.css('[role="main"]').get() or
                response.css('.content').get() or
                response.css('#content').get() or
                response.css('body').get() or
                ''
            )
            
            markdown = self.html_converter.handle(main_content) if main_content else ''
            markdown = markdown.strip()
            
            # Calculate content hash (for backwards compatibility)
            content_hash = hashlib.sha256(markdown.encode()).hexdigest() if markdown else ''
            
            # Calculate semantic fingerprint for lightweight change detection
            sample_hash = extract_semantic_fingerprint(full_html, max_content_length=10000) if full_html else ''
            
            # Determine if homepage
            is_homepage = self._is_homepage(response.url)
            depth = response.meta.get('depth', 0)
            
            return {
                'url': url,
                'title': title,
                'description': description,
                'markdown': markdown,
                'content_hash': content_hash,
                'sample_hash': sample_hash,
                'is_homepage': is_homepage,
                'depth': depth,
            }
            
        except Exception as e:
            logger.error(f"Error extracting data from {response.url}: {e}")
            return None

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
                '.css', '.js', '.xml', '.json',
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

    def _is_homepage(self, url: str) -> bool:
        """Check if URL is the homepage."""
        normalized = self._normalize_url(url)
        start_normalized = self._normalize_url(self.start_url)
        return normalized == start_normalized

    def handle_error(self, failure):
        """Handle request errors."""
        logger.warning(f"Request failed: {failure.request.url} - {failure.value}")

