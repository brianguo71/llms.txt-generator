"""Scrapy spider for scraping a specific list of URLs (batch scrape)."""

import hashlib
import logging
from typing import Any, Generator
from urllib.parse import urlparse

import html2text
import scrapy
from scrapy.http import Response

logger = logging.getLogger(__name__)


class BatchScrapeSpider(scrapy.Spider):
    """Spider that scrapes a specific list of URLs without following links.
    
    Used for selective re-scraping when we know exactly which pages need updating.
    Includes Playwright fallback for JS-heavy pages.
    """

    name = "batch_scrape_spider"
    
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
        urls: list[str],
        start_url: str = "",
        collected_pages: list | None = None,
        *args,
        **kwargs
    ):
        """Initialize spider.
        
        Args:
            urls: List of specific URLs to scrape
            start_url: The site's root URL (for homepage detection)
            collected_pages: Shared list to collect results
        """
        super().__init__(*args, **kwargs)
        self.urls_to_scrape = urls
        self.start_url = start_url or (urls[0] if urls else "")
        self.collected_pages = collected_pages if collected_pages is not None else []
        self.scraped_count = 0
        
        # Parse domain from first URL for consistency
        if urls:
            parsed = urlparse(urls[0])
            self.allowed_domains = [parsed.netloc]
            self.base_domain = parsed.netloc
        else:
            self.allowed_domains = []
            self.base_domain = ""
        
        # Track which URLs we've already processed (for Playwright retries)
        self.processed_urls: set[str] = set()
        
        # HTML to markdown converter
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = True
        self.html_converter.ignore_emphasis = False
        self.html_converter.body_width = 0  # No line wrapping

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        """Generate requests for all URLs in the batch."""
        for url in self.urls_to_scrape:
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                meta={'playwright': False},
                errback=self.handle_error,
            )

    def parse(self, response: Response) -> Generator[Any, None, None]:
        """Parse a page response."""
        url = response.url
        normalized_url = self._normalize_url(url)
        used_playwright = response.meta.get('playwright', False)
        
        # Skip if already processed (unless this is a Playwright retry)
        if normalized_url in self.processed_urls and not used_playwright:
            return
        
        # Check if we need Playwright (and haven't already used it)
        if not used_playwright and self._needs_playwright(response):
            logger.info(f"[PLAYWRIGHT] Retrying with browser rendering: {url}")
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                meta={
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
        
        # Mark as processed
        self.processed_urls.add(normalized_url)
        self.scraped_count += 1
        
        # Extract page data
        page_data = self._extract_page_data(response)
        if page_data:
            self.collected_pages.append(page_data)
            logger.info(f"Batch scraped ({self.scraped_count}/{len(self.urls_to_scrape)}): {url}")

    def _needs_playwright(self, response: Response) -> bool:
        """Detect if page needs JavaScript rendering."""
        # Extract text from visible elements only
        visible_text_parts = response.xpath(
            '//body//*[not(self::script) and not(self::style) and not(self::noscript)]/text()'
        ).getall()
        visible_text = ' '.join(t.strip() for t in visible_text_parts if t.strip())
        text_length = len(visible_text)
        
        # Trigger 1: Very little visible text content
        if text_length < 500:
            logger.info(f"[PLAYWRIGHT TRIGGER] Low visible text ({text_length} chars < 500): {response.url}")
            return True
        
        # Trigger 2: Explicit JS requirement messages
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
        
        return False

    def _extract_page_data(self, response: Response) -> dict[str, Any] | None:
        """Extract page data from response."""
        try:
            url = self._normalize_url(response.url)
            
            # Extract title
            title = response.css('title::text').get() or ''
            title = title.strip()
            
            # Extract meta description
            description = response.css('meta[name="description"]::attr(content)').get() or ''
            description = description.strip()
            
            # Get main content HTML and convert to markdown
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
            
            # Calculate content hash
            content_hash = hashlib.sha256(markdown.encode()).hexdigest() if markdown else ''
            
            # Determine if homepage
            is_homepage = self._is_homepage(response.url)
            
            return {
                'url': url,
                'title': title,
                'description': description,
                'markdown': markdown,
                'content_hash': content_hash,
                'is_homepage': is_homepage,
                'depth': 0,  # Not relevant for batch scrape
            }
            
        except Exception as e:
            logger.error(f"Error extracting data from {response.url}: {e}")
            return None

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)
        path = parsed.path.rstrip('/') or '/'
        return f"{parsed.scheme}://{parsed.netloc}{path}".lower()

    def _is_homepage(self, url: str) -> bool:
        """Check if URL is the homepage."""
        if not self.start_url:
            return False
        normalized = self._normalize_url(url)
        start_normalized = self._normalize_url(self.start_url)
        return normalized == start_normalized

    def handle_error(self, failure):
        """Handle request errors."""
        logger.warning(f"Request failed: {failure.request.url} - {failure.value}")

