"""Semantic content extraction for change detection.

Extracts meaningful content from HTML pages while ignoring noisy elements
like scripts, styles, ads, and deployment-specific hashes.
"""

import hashlib
import re
from bs4 import BeautifulSoup


class SemanticExtractor:
    """Extract semantic fingerprint from HTML for change detection."""
    
    # Elements to remove entirely (noisy, dynamic)
    NOISY_TAGS = [
        'script', 'style', 'noscript', 'iframe', 'svg', 'canvas',
        'video', 'audio', 'source', 'track', 'embed', 'object',
    ]
    
    # Classes/IDs that typically contain dynamic content
    NOISY_SELECTORS = [
        '[class*="ad-"]', '[class*="ads-"]', '[id*="ad-"]',
        '[class*="intercom"]', '[class*="hubspot"]', '[class*="drift"]',
        '[class*="cookie"]', '[class*="gdpr"]', '[class*="consent"]',
        '[class*="popup"]', '[class*="modal"]', '[class*="overlay"]',
        '[data-analytics]', '[data-tracking]',
    ]
    
    def extract_fingerprint(self, html: str, max_content_length: int = 10000) -> str:
        """Extract semantic fingerprint from HTML.
        
        Args:
            html: Raw HTML content
            max_content_length: Max chars of body text to include
            
        Returns:
            SHA256 hash of the semantic content
        """
        content = self.extract_content(html, max_content_length)
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def extract_content(self, html: str, max_content_length: int = 10000) -> str:
        """Extract meaningful semantic content from HTML.
        
        Returns a normalized string containing:
        - Title
        - Meta description
        - Main content text (cleaned)
        
        Args:
            html: Raw HTML content
            max_content_length: Max chars of body text to include
            
        Returns:
            Normalized content string for hashing
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove noisy elements
        for tag in self.NOISY_TAGS:
            for element in soup.find_all(tag):
                element.decompose()
        
        # Remove elements matching noisy selectors
        for selector in self.NOISY_SELECTORS:
            try:
                for element in soup.select(selector):
                    element.decompose()
            except Exception:
                pass  # Some selectors might fail, that's ok
        
        parts = []
        
        # 1. Extract title
        title_tag = soup.find('title')
        if title_tag:
            title = self._normalize_text(title_tag.get_text())
            parts.append(f"TITLE:{title}")
        
        # 2. Extract meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self._normalize_text(meta_desc['content'])
            parts.append(f"DESC:{desc}")
        
        # 3. Extract Open Graph title/description as fallback
        og_title = soup.find('meta', attrs={'property': 'og:title'})
        if og_title and og_title.get('content'):
            parts.append(f"OG_TITLE:{self._normalize_text(og_title['content'])}")
        
        og_desc = soup.find('meta', attrs={'property': 'og:description'})
        if og_desc and og_desc.get('content'):
            parts.append(f"OG_DESC:{self._normalize_text(og_desc['content'])}")
        
        # 4. Extract main content from body
        main_content = self._extract_main_content(soup, max_content_length)
        if main_content:
            parts.append(f"CONTENT:{main_content}")
        
        # 5. Extract navigation structure (links in nav/header)
        nav_links = self._extract_nav_links(soup)
        if nav_links:
            parts.append(f"NAV:{','.join(nav_links[:20])}")  # First 20 nav links
        
        return "\n".join(parts)
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for consistent hashing."""
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove leading/trailing whitespace
        text = text.strip()
        # Lowercase for consistency
        text = text.lower()
        return text
    
    def _extract_main_content(self, soup: BeautifulSoup, max_length: int) -> str:
        """Extract main content text from body."""
        # Try to find main content container
        main = (
            soup.find('main') or
            soup.find('article') or
            soup.find('[role="main"]') or
            soup.find(id='content') or
            soup.find(id='main') or
            soup.find(class_='content') or
            soup.find('body')
        )
        
        if not main:
            return ""
        
        # Get text content
        text = main.get_text(separator=' ', strip=True)
        text = self._normalize_text(text)
        
        # Truncate to max length
        if len(text) > max_length:
            text = text[:max_length]
        
        return text
    
    def _extract_nav_links(self, soup: BeautifulSoup) -> list[str]:
        """Extract navigation link hrefs for structural fingerprinting."""
        nav_links = []
        
        # Find nav elements
        nav_containers = soup.find_all(['nav', 'header'])
        
        for container in nav_containers:
            for link in container.find_all('a', href=True):
                href = link['href']
                # Skip anchors and javascript links
                if href.startswith('#') or href.startswith('javascript:'):
                    continue
                # Normalize: remove query params and trailing slashes
                href = re.sub(r'\?.*$', '', href)
                href = href.rstrip('/')
                if href:
                    nav_links.append(href)
        
        return list(dict.fromkeys(nav_links))  # Remove duplicates, preserve order


# Singleton instance for convenience
_extractor = SemanticExtractor()


def extract_semantic_fingerprint(html: str, max_content_length: int = 10000) -> str:
    """Convenience function to extract semantic fingerprint from HTML."""
    return _extractor.extract_fingerprint(html, max_content_length)


def extract_semantic_content(html: str, max_content_length: int = 10000) -> str:
    """Convenience function to extract semantic content from HTML."""
    return _extractor.extract_content(html, max_content_length)

