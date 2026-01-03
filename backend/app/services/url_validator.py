"""URL validation service.

Validates that a URL is well-formed, reachable, and contains HTML content.
"""

import html
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


@dataclass
class ValidationResult:
    """Result of URL validation."""
    is_valid: bool
    error_message: str | None = None
    final_url: str | None = None  # After redirects
    title: str | None = None


class URLValidator:
    """Service for validating URLs before creating projects."""

    def __init__(self, timeout: float = 10.0, user_agent: str = "llmstxt-generator/1.0"):
        self.timeout = timeout
        self.user_agent = user_agent

    async def validate(self, url: str) -> ValidationResult:
        """Validate a URL for use as a project.
        
        Checks:
        1. URL format is valid
        2. Uses HTTP or HTTPS scheme
        3. Has a valid domain
        4. Site is reachable
        5. Response contains HTML content
        
        Returns:
            ValidationResult with status and any error message
        """
        # Step 1: Validate URL format
        format_error = self._validate_format(url)
        if format_error:
            return ValidationResult(is_valid=False, error_message=format_error)

        # Step 2: Check site is reachable and has HTML content
        return await self._check_site(url)

    def _validate_format(self, url: str) -> str | None:
        """Validate URL format. Returns error message or None if valid."""
        try:
            parsed = urlparse(url)
        except Exception:
            return "Invalid URL format"

        # Check scheme
        if parsed.scheme not in ("http", "https"):
            return "URL must use http:// or https://"

        # Check netloc (domain)
        if not parsed.netloc:
            return "URL must include a domain name"

        # Basic domain validation
        domain = parsed.netloc.lower()
        
        # Remove port if present
        if ":" in domain:
            domain = domain.split(":")[0]

        # Check for valid domain pattern
        domain_pattern = r'^([a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
        if not re.match(domain_pattern, domain) and domain != "localhost":
            return "Invalid domain name"

        return None

    async def _check_site(self, url: str) -> ValidationResult:
        """Check that the site is reachable and has HTML content."""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": self.user_agent},
            ) as client:
                response = await client.get(url)

                # Check status code
                if response.status_code >= 400:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Site returned error: HTTP {response.status_code}",
                    )

                # Check content type
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type.lower():
                    return ValidationResult(
                        is_valid=False,
                        error_message="URL does not point to an HTML page",
                    )

                # Check there's actual content
                html = response.text
                if len(html.strip()) < 10:
                    return ValidationResult(
                        is_valid=False,
                        error_message="Page appears to be empty or has minimal content",
                    )

                # Try to extract title for confirmation
                title = self._extract_title(html)

                # Get final URL after redirects
                final_url = str(response.url).rstrip("/")

                return ValidationResult(
                    is_valid=True,
                    final_url=final_url,
                    title=title,
                )

        except httpx.TimeoutException:
            return ValidationResult(
                is_valid=False,
                error_message="Site took too long to respond (timeout)",
            )
        except httpx.ConnectError:
            return ValidationResult(
                is_valid=False,
                error_message="Could not connect to site. Check the URL and try again.",
            )
        except httpx.TooManyRedirects:
            return ValidationResult(
                is_valid=False,
                error_message="Too many redirects. The URL may be misconfigured.",
            )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_message=f"Could not access site: {str(e)}",
            )

    def _extract_title(self, html_content: str) -> str | None:
        """Extract page title from HTML, decoding HTML entities."""
        # Simple regex extraction to avoid BeautifulSoup overhead
        match = re.search(r'<title[^>]*>([^<]+)</title>', html_content, re.IGNORECASE)
        if match:
            title = match.group(1).strip()[:200]
            return html.unescape(title)
        return None

