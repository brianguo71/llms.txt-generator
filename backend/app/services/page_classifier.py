"""Page classification service for detecting listing pages and scoring relevance."""

from urllib.parse import urlparse

from bs4 import BeautifulSoup


class PageClassifier:
    """Classify pages to detect listing/collection pages and score relevance."""

    # URL patterns that indicate important/core pages
    IMPORTANT_URL_PATTERNS = [
        "/about", "/pricing", "/features", "/product",
        "/platform", "/solutions", "/services", "/docs",
        "/documentation", "/api", "/contact", "/team",
        "/integrations", "/enterprise", "/security",
        "/demo", "/trial", "/get-started", "/overview",
    ]

    # Card/listing selectors to detect collection pages
    CARD_SELECTORS = [
        "article",
        ".card",
        ".item",
        ".post",
        ".listing",
        ".job",
        ".vacancy",
        ".position",
        "[class*='card']",
        "[class*='item']",
        "[class*='tile']",
        "[class*='grid-item']",
        "[class*='list-item']",
    ]

    # Pagination selectors
    PAGINATION_SELECTORS = [
        ".pagination",
        ".pager",
        "[class*='pagination']",
        "nav[aria-label*='pagination']",
        ".page-numbers",
        "[class*='paging']",
        ".load-more",
    ]

    def is_listing_page(self, soup: BeautifulSoup) -> bool:
        """Detect if page is a listing/collection page.
        
        Listing pages include:
        - Job boards with multiple job cards
        - Blog indexes with post cards
        - Product catalogs with item grids
        - Category pages with many linked items
        
        Args:
            soup: Parsed HTML of the page
            
        Returns:
            True if this appears to be a listing/collection page
        """
        signals = []

        # Signal 1: Repetitive card-like structures (5+ similar items)
        for selector in self.CARD_SELECTORS:
            try:
                elements = soup.select(selector)
                if len(elements) >= 5:
                    signals.append("cards")
                    break
            except Exception:
                continue

        # Signal 2: Pagination present
        for selector in self.PAGINATION_SELECTORS:
            try:
                if soup.select_one(selector):
                    signals.append("pagination")
                    break
            except Exception:
                continue

        # Signal 3: High link density in main content area
        main_content = soup.select_one("main, [role='main'], .content, #content, .main-content")
        if main_content:
            # Count links vs text in main content
            links = main_content.find_all("a")
            text = main_content.get_text(strip=True)
            words = len(text.split())
            
            # If there are many links relative to content, it's likely a listing
            if len(links) > 10 and words > 0:
                link_ratio = len(links) / (words / 100)  # Links per 100 words
                if link_ratio > 5:  # More than 5 links per 100 words
                    signals.append("link_density")

        # Signal 4: Many list items with links in main content
        if main_content:
            list_items_with_links = main_content.select("ul li a, ol li a")
            if len(list_items_with_links) > 15:
                signals.append("list_links")

        # A page is a listing if it has at least one strong signal
        return len(signals) >= 1

    def has_substantial_content(self, soup: BeautifulSoup) -> bool:
        """Check if page has substantial prose content.
        
        Args:
            soup: Parsed HTML of the page
            
        Returns:
            True if the page has meaningful text content
        """
        # Look for paragraphs in main content area
        main_content = soup.select_one("main, [role='main'], .content, #content, article")
        if main_content:
            paragraphs = main_content.find_all("p")
        else:
            paragraphs = soup.find_all("p")

        # Count words in paragraphs
        word_count = 0
        for p in paragraphs:
            text = p.get_text(strip=True)
            # Skip very short paragraphs (likely UI text)
            if len(text) > 20:
                word_count += len(text.split())

        return word_count > 100

    def calculate_relevance_score(
        self,
        url: str,
        soup: BeautifulSoup,
        is_nav_link: bool,
        depth: int,
    ) -> float:
        """Calculate page relevance score for llms.txt inclusion.
        
        Higher scores = more relevant for llms.txt.
        
        Scoring factors:
        - Navigation links get priority (+30)
        - Shallow depth gets priority (+10 per level)
        - Important URL patterns get boost (+15)
        - Listing pages get penalty (-50)
        - Substantial content gets boost (+10)
        
        Args:
            url: The page URL
            soup: Parsed HTML of the page
            is_nav_link: Whether this URL was found in site navigation
            depth: Crawl depth (0 = homepage)
            
        Returns:
            Relevance score from 0-100
        """
        score = 50  # Base score

        # Boost: Navigation link (+30)
        if is_nav_link:
            score += 30

        # Boost: Shallow depth (+10 per level closer to root, max 30)
        depth_boost = max(0, (3 - depth) * 10)
        score += depth_boost

        # Boost: Important URL patterns (+15)
        path = urlparse(url).path.lower()
        if any(pattern in path for pattern in self.IMPORTANT_URL_PATTERNS):
            score += 15

        # Penalty: Listing page detected (-50)
        if self.is_listing_page(soup):
            score -= 50

        # Boost: Has substantial prose content (+10)
        if self.has_substantial_content(soup):
            score += 10

        # Clamp to 0-100 range
        return min(100, max(0, score))


# Singleton instance
_classifier: PageClassifier | None = None


def get_classifier() -> PageClassifier:
    """Get or create classifier singleton."""
    global _classifier
    if _classifier is None:
        _classifier = PageClassifier()
    return _classifier

