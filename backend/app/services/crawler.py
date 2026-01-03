"""Web crawler service for extracting website content."""

import hashlib
import html
import logging
import time
from collections import deque
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import Settings
from app.services.browser import BrowserService
from app.services.page_classifier import get_classifier
from app.services.sitemap import SitemapParser

logger = logging.getLogger(__name__)


# Relevance thresholds for inclusion in llms.txt
# We use low thresholds since the LLM will curate the final selection
NAV_RELEVANCE_THRESHOLD = 30
NON_NAV_RELEVANCE_THRESHOLD = 40


class CrawlerService:
    """Service for crawling websites and extracting metadata."""

    # Navigation selectors to find important links
    NAV_SELECTORS = [
        "nav",
        "header nav",
        "[role='navigation']",
        ".navigation",
        ".nav",
        ".main-nav",
        ".site-nav",
        ".navbar",
        "header a",
        "footer a",
    ]

    def __init__(self, settings: Settings, on_progress: callable = None):
        self.settings = settings
        self.max_pages = settings.max_pages_per_crawl
        self.max_depth = getattr(settings, 'max_crawl_depth', 1)  # Default to 1
        self.timeout = settings.crawl_timeout_seconds
        self.delay = settings.crawl_delay_seconds
        self.user_agent = settings.user_agent
        self.on_progress = on_progress  # Callback for progress updates
        self.classifier = get_classifier()

    def _report_progress(self, crawled: int, queued: int, url: str):
        """Report crawl progress if callback is set."""
        if self.on_progress:
            self.on_progress(crawled, queued, url)

    def _needs_javascript_rendering(self, soup: BeautifulSoup) -> bool:
        """Detect if page needs JavaScript to render content.
        
        Checks for signals that indicate a JavaScript-heavy SPA:
        - Empty or minimal body text content
        - SPA framework markers (React, Vue, Next.js, Nuxt) with empty content
        - Loading/skeleton placeholders dominating content
        
        
        Args:
            soup: Parsed HTML from initial httpx fetch
            
        Returns:
            True if page likely needs JS rendering, False otherwise
        """
        body = soup.find("body")
        if not body:
            return True
        
        # Get body text length for reference
        body_text = body.get_text(strip=True)
        body_text_len = len(body_text)
        
        # Definite trigger: Very minimal text content (< 100 chars)
        if body_text_len < 100:
            logger.info("Page has minimal text content, needs JS rendering")
            return True
        
        # Check for SPA framework markers with empty content
        spa_markers = [
            ("div", {"id": "root"}),       # React
            ("div", {"id": "app"}),         # Vue
            ("div", {"id": "__next"}),      # Next.js
            ("div", {"id": "__nuxt"}),      # Nuxt
            ("div", {"id": "___gatsby"}),   # Gatsby
            ("div", {"id": "svelte"}),      # SvelteKit
        ]
        
        for tag, attrs in spa_markers:
            element = soup.find(tag, attrs)
            if element:
                element_text = element.get_text(strip=True)
                # If the SPA container exists but has minimal content, JS is needed
                if len(element_text) < 50:
                    logger.info(f"Found empty SPA marker {attrs}, needs JS rendering")
                    return True
        
        # Check for loading/skeleton placeholders dominating the content
        loading_selectors = [
            "[class*='skeleton']",
            "[class*='loading']",
            "[class*='spinner']",
            "[class*='placeholder']",
        ]
        for selector in loading_selectors:
            try:
                loading_elements = soup.select(selector)
                if len(loading_elements) > 3:  # Multiple loading indicators
                    logger.info(f"Found multiple loading elements ({selector}), needs JS rendering")
                    return True
            except Exception:
                continue
        
        # Only check noscript if there's also low content (< 500 chars)
        # Many sites have noscript warnings but render fine without JS
        if body_text_len < 500:
            noscript = soup.find("noscript")
            if noscript:
                ns_text = noscript.get_text().lower()
                # Only trigger on strong indicators that JS is REQUIRED
                strong_js_required = [
                    "requires javascript",
                    "javascript is required",
                    "you need to enable javascript",
                    "this app requires javascript",
                ]
                if any(phrase in ns_text for phrase in strong_js_required):
                    logger.info("Found strong noscript warning with low content, needs JS rendering")
                    return True
        
        return False

    def _extract_navigation_links(self, soup: BeautifulSoup, base_url: str) -> set[str]:
        """Extract links from navigation elements (high priority pages).
        
        These links typically represent the site's core pages that should
        be prioritized for llms.txt inclusion.
        
        Args:
            soup: Parsed HTML of the page
            base_url: Base URL for resolving relative links
            
        Returns:
            Set of normalized URLs found in navigation
        """
        nav_links: set[str] = set()
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc

        for selector in self.NAV_SELECTORS:
            try:
                for element in soup.select(selector):
                    # If selector directly selected <a> elements, use them directly
                    # Otherwise, find all <a> elements within the container
                    if element.name == "a" and element.get("href"):
                        links = [element]
                    else:
                        links = element.find_all("a", href=True)
                    
                    for link in links:
                        href = link["href"]
                        
                        # Skip non-HTTP links
                        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                            continue
                        
                        abs_url = urljoin(base_url, href)
                        parsed = urlparse(abs_url)
                        
                        # Only include internal links
                        if parsed.netloc == base_domain:
                            normalized = self._normalize_url(abs_url)
                            nav_links.add(normalized)
            except Exception:
                continue

        return nav_links

    def crawl_website(self, start_url: str) -> list[dict[str, Any]]:
        """Crawl a website starting from the given URL.

        Uses breadth-first search to discover pages.
        Prioritizes navigation links and filters by relevance score.
        Respects robots.txt and implements polite crawling.

        Returns:
            List of page data dictionaries (filtered by relevance).
        """
        parsed_start = urlparse(start_url)
        base_domain = parsed_start.netloc

        # Track visited URLs (normalized) and pages to crawl
        visited: set[str] = set()
        queued: set[str] = set()  # Track URLs already in queue
        to_visit: deque[tuple[str, int, bool]] = deque()  # (url, depth, is_priority)
        pages: list[dict[str, Any]] = []
        nav_links: set[str] = set()  # Navigation links (high priority)

        # Helper to add URL to queue with deduplication
        def enqueue(url: str, depth: int, priority: bool = False) -> None:
            normalized = self._normalize_url(url)
            # Skip external URLs
            parsed = urlparse(normalized)
            if parsed.netloc != base_domain:
                return
            # Skip low-value URLs
            if self._should_skip_url(normalized):
                return
            if normalized not in visited and normalized not in queued:
                queued.add(normalized)
                if priority:
                    # Add priority URLs to the front
                    to_visit.appendleft((normalized, depth, True))
                else:
                    to_visit.append((normalized, depth, False))

        # Add start URL
        enqueue(start_url, 0, priority=True)

        # Try to get sitemap URLs
        sitemap_urls = self._get_sitemap_urls(start_url)
        for url in sitemap_urls[:self.max_pages]:
            enqueue(url, 1)

        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent},
        ) as client:
            first_page = True
            
            while to_visit and len(pages) < self.max_pages:
                url, depth, is_priority = to_visit.popleft()

                # Skip if already visited (shouldn't happen but safety check)
                if url in visited:
                    continue

                visited.add(url)

                # Crawl the page and get soup for classification
                page_data, soup = self._crawl_single_page_with_soup(client, url, depth)
                
                if page_data and soup:
                    # On first page (homepage), extract navigation links
                    if first_page:
                        nav_links = self._extract_navigation_links(soup, url)
                        first_page = False
                        
                        # Prioritize navigation links
                        for nav_url in nav_links:
                            enqueue(nav_url, depth=1, priority=True)
                    
                    # Calculate relevance score
                    is_nav = url in nav_links
                    relevance_score = self.classifier.calculate_relevance_score(
                        url=url,
                        soup=soup,
                        is_nav_link=is_nav,
                        depth=depth,
                    )
                    
                    # Determine threshold based on whether page is in navigation
                    # Nav pages are curated by site owner, so we trust them more
                    threshold = NAV_RELEVANCE_THRESHOLD if is_nav else NON_NAV_RELEVANCE_THRESHOLD
                    
                    # Also check if it's a listing page (stricter for non-nav)
                    is_listing = self.classifier.is_listing_page(soup)
                    
                    # Check if this is the homepage (used for filtering in llms.txt output)
                    is_homepage = (depth == 0) or (self._normalize_url(url) == self._normalize_url(start_url))
                    
                    # Include if: navigation link OR homepage OR (high relevance AND not a listing)
                    # Homepage is included for LLM context but filtered out of llms.txt links later
                    should_include = is_homepage or is_nav or (relevance_score >= threshold and not is_listing)
                    
                    if should_include:
                        page_data["relevance_score"] = relevance_score
                        page_data["is_nav_link"] = is_nav
                        page_data["is_homepage"] = is_homepage
                        pages.append(page_data)
                        
                        # Report progress
                        self._report_progress(
                            crawled=len(pages),
                            queued=len(to_visit),
                            url=url
                        )

                    # Extract links for further crawling (even from filtered pages)
                    if depth < self.max_depth:  # Limit depth
                        for link in page_data.get("links", []):
                            abs_link = urljoin(url, link)
                            # Prioritize links that are also in navigation
                            link_priority = self._normalize_url(abs_link) in nav_links
                            enqueue(abs_link, depth + 1, priority=link_priority)

                # Polite delay between requests
                time.sleep(self.delay)

        # Sort by relevance score (highest first)
        pages.sort(key=lambda p: p.get("relevance_score", 0), reverse=True)
        
        return pages

    def crawl_page(self, url: str) -> dict[str, Any] | None:
        """Crawl a single page and extract metadata.

        Returns:
            Page data dictionary or None if failed.
        """
        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent},
        ) as client:
            page_data, _ = self._crawl_single_page_with_soup(client, url, 0)
            return page_data

    def _crawl_single_page_with_soup(
        self,
        client: httpx.Client,
        url: str,
        depth: int,
    ) -> tuple[dict[str, Any] | None, BeautifulSoup | None]:
        """Crawl a single page and extract metadata, returning soup for classification.
        
        Uses httpx for initial fetch, then falls back to Playwright for JS rendering
        if the page appears to need JavaScript execution.
        
        Returns:
            Tuple of (page_data dict or None, BeautifulSoup or None)
        """
        try:
            response = client.get(url)
            response.raise_for_status()

            # Only process HTML pages
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                return None, None

            html_content = response.text
            soup = BeautifulSoup(html_content, "lxml")
            
            # Check if page needs JavaScript rendering
            if self._needs_javascript_rendering(soup):
                try:
                    logger.info(f"Re-fetching {url} with Playwright for JS rendering")
                    browser = BrowserService(self.settings)
                    html_content = browser.render_page_sync(url)
                    soup = BeautifulSoup(html_content, "lxml")
                except Exception as e:
                    logger.warning(f"Playwright rendering failed for {url}: {e}, using original HTML")
                    # Fall back to original HTML if Playwright fails

            # Extract metadata
            title = self._extract_title(soup)
            description = self._extract_description(soup)
            h1 = self._extract_h1(soup)
            h2s = self._extract_h2s(soup)
            first_paragraph = self._extract_first_paragraph(soup)
            links = self._extract_links(soup, url)

            # Calculate content hash
            content_hash = hashlib.sha256(html_content.encode()).hexdigest()

            # Extract HTTP headers for change detection
            etag = response.headers.get("etag")
            last_modified = response.headers.get("last-modified")

            page_data = {
                "url": url,
                "title": title,
                "description": description,
                "h1": h1,
                "h2s": h2s,
                "first_paragraph": first_paragraph,
                "links": links,
                "content_hash": content_hash,
                "etag": etag,
                "last_modified": self._parse_http_date(last_modified),
                "depth": depth,
            }
            
            return page_data, soup

        except httpx.HTTPError as e:
            # Log error but continue crawling
            logger.error(f"Error crawling {url}: {e}")
            return None, None

    def _extract_title(self, soup: BeautifulSoup) -> str | None:
        """Extract page title, decoding any HTML entities."""
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)[:512]
            return html.unescape(title)

        # Fallback to og:title
        og_title = soup.find("meta", property="og:title")
        if og_title:
            content = og_title.get("content", "")[:512]
            return html.unescape(content)

        return None

    def _extract_description(self, soup: BeautifulSoup) -> str | None:
        """Extract page description, decoding HTML entities."""
        # Try meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            return html.unescape(meta_desc.get("content", ""))

        # Try og:description
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            return html.unescape(og_desc.get("content", ""))

        return None

    def _extract_h1(self, soup: BeautifulSoup) -> str | None:
        """Extract first H1 heading, decoding HTML entities."""
        h1 = soup.find("h1")
        if h1:
            text = h1.get_text(strip=True)[:512]
            return html.unescape(text)
        return None

    def _extract_h2s(self, soup: BeautifulSoup, max_count: int = 6) -> list[str]:
        """Extract H2 headings to show page structure, decoding HTML entities."""
        h2s = []
        for h2 in soup.find_all("h2"):
            text = h2.get_text(strip=True)
            if text and len(text) > 2:  # Skip empty or very short headings
                # Clean up common patterns and decode entities
                text = html.unescape(text.strip("# ").strip())
                if text and text not in h2s:  # Avoid duplicates
                    h2s.append(text[:100])  # Limit individual heading length
                    if len(h2s) >= max_count:
                        break
        return h2s

    def _extract_first_paragraph(self, soup: BeautifulSoup) -> str | None:
        """Extract the first meaningful paragraph from the page content."""
        # Try to find main content area first
        main_content = None
        for selector in ["main", "article", "[role='main']", ".content", "#content"]:
            main_content = soup.select_one(selector)
            if main_content:
                break
        
        # Fallback to body
        search_area = main_content or soup.find("body")
        if not search_area:
            return None

        # Find first paragraph with substantial content
        for p in search_area.find_all("p"):
            text = html.unescape(p.get_text(strip=True))
            # Skip very short paragraphs (likely navigation or boilerplate)
            if text and len(text) > 50:
                # Truncate if too long
                if len(text) > 300:
                    text = text[:297] + "..."
                return text
        
        return None

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Extract all internal links from the page."""
        links = []
        parsed_base = urlparse(base_url)

        for a in soup.find_all("a", href=True):
            href = a["href"]

            # Skip non-HTTP links
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue

            # Convert to absolute URL
            abs_url = urljoin(base_url, href)
            parsed = urlparse(abs_url)

            # Only include internal links
            if parsed.netloc == parsed_base.netloc:
                # Remove fragment
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if parsed.query:
                    clean_url += f"?{parsed.query}"
                links.append(clean_url)

        return list(set(links))  # Deduplicate

    def _should_skip_url(self, url: str) -> bool:
        """Check if URL should be skipped based on technical criteria only.
        
        Content-based filtering (blog vs features, job listing vs overview) is
        handled by LLM-based batch classification after crawling. This method only
        filters out technically non-crawlable or obviously irrelevant URLs.
        """
        parsed = urlparse(url)
        path = parsed.path.lower()
        query = parsed.query.lower()
        
        # Technical skip patterns - these are never useful for llms.txt
        skip_patterns = [
            # Non-HTML file extensions
            '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.ico',
            '.css', '.js', '.xml', '.json', '.zip', '.tar', '.gz', '.rar',
            '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.wav',
            '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
            '.woff', '.woff2', '.ttf', '.eot', '.otf',
            
            # Authentication and user-specific pages
            '/login', '/signin', '/sign-in', '/logout', '/signout', '/sign-out',
            '/register', '/signup', '/sign-up',
            '/auth/', '/oauth/', '/sso/',
            '/account', '/my-account', '/myaccount',
            '/profile', '/my-profile', '/myprofile',
            '/dashboard', '/my-dashboard',
            '/settings', '/preferences',
            '/cart', '/checkout', '/basket', '/order',
            
            # Technical/system paths
            '/feed', '/rss', '/atom',
            '/sitemap', '/robots',
            '/wp-content/', '/wp-admin/', '/wp-includes/',
            '/cdn-cgi/', '/_next/', '/_nuxt/',
            '/static/', '/assets/', '/dist/',
            '/api/', '/.well-known/',
            
            # Search and filter result pages
            '/search',
            
            # Path-based pagination
            '/page/',
            
            # Content aggregation patterns (individual items in collections)
            '/author/', '/authors/',
            '/tag/', '/tags/', '/category/', '/categories/',
            '/topic/', '/topics/',
            '/archive/', '/archives/',
        ]
        
        for pattern in skip_patterns:
            if pattern in path:
                return True
        
        # Skip pagination query params
        if 'page=' in query or 'paged=' in query or 'p=' in query:
            return True
        
        return False

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication.
        
        - Strips fragments (#section)
        - Normalizes index files to directory root
        - Removes trailing slashes (except for root)
        """
        parsed = urlparse(url)
        path = parsed.path or "/"
        
        # Normalize index files to directory root
        # /index.html, /index.htm, /index.php, /default.html etc.
        index_patterns = [
            "/index.html", "/index.htm", "/index.php",
            "/default.html", "/default.htm", "/default.aspx",
        ]
        for pattern in index_patterns:
            if path.endswith(pattern):
                path = path[:-len(pattern)] or "/"
                break
        
        # Remove trailing slash (except for root)
        if len(path) > 1:
            path = path.rstrip("/")
        
        # Build normalized URL WITHOUT fragment (anchor links are same page)
        normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
        if parsed.query:
            normalized += f"?{parsed.query}"
        # Note: We intentionally do NOT include parsed.fragment
        return normalized

    def _get_sitemap_urls(self, start_url: str) -> list[str]:
        """Try to fetch sitemap URLs."""
        parsed = urlparse(start_url)
        sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

        parser = SitemapParser(self.user_agent)
        return parser.get_urls(sitemap_url)

    def _parse_http_date(self, date_str: str | None) -> datetime | None:
        """Parse HTTP date header."""
        if not date_str:
            return None
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            return None

