"""Sitemap parsing service."""

from datetime import datetime
from typing import Any
from xml.etree import ElementTree

import httpx


class SitemapParser:
    """Service for parsing sitemap.xml files."""

    # XML namespaces used in sitemaps
    NAMESPACES = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    }

    def __init__(self, user_agent: str):
        self.user_agent = user_agent

    def get_urls(self, sitemap_url: str) -> list[str]:
        """Get all URLs from a sitemap.

        Handles both regular sitemaps and sitemap indexes.

        Returns:
            List of URLs found in the sitemap.
        """
        try:
            with httpx.Client(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": self.user_agent},
            ) as client:
                return self._fetch_sitemap(client, sitemap_url)
        except Exception:
            return []

    def get_urls_with_lastmod(self, sitemap_url: str) -> dict[str, datetime | None]:
        """Get all URLs with their lastmod dates.

        Returns:
            Dict mapping URL to lastmod datetime (or None if not specified).
        """
        try:
            with httpx.Client(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": self.user_agent},
            ) as client:
                return self._fetch_sitemap_with_dates(client, sitemap_url)
        except Exception:
            return {}

    def _fetch_sitemap(self, client: httpx.Client, url: str) -> list[str]:
        """Fetch and parse a sitemap, returning URLs."""
        try:
            response = client.get(url)
            response.raise_for_status()

            root = ElementTree.fromstring(response.content)

            # Check if this is a sitemap index
            if root.tag.endswith("sitemapindex"):
                urls = []
                for sitemap in root.findall(".//sm:sitemap/sm:loc", self.NAMESPACES):
                    if sitemap.text:
                        urls.extend(self._fetch_sitemap(client, sitemap.text))
                return urls

            # Regular sitemap
            urls = []
            for url_elem in root.findall(".//sm:url/sm:loc", self.NAMESPACES):
                if url_elem.text:
                    urls.append(url_elem.text)

            return urls

        except Exception:
            return []

    def _fetch_sitemap_with_dates(
        self,
        client: httpx.Client,
        url: str,
    ) -> dict[str, datetime | None]:
        """Fetch sitemap and return URLs with lastmod dates."""
        try:
            response = client.get(url)
            response.raise_for_status()

            root = ElementTree.fromstring(response.content)
            result: dict[str, datetime | None] = {}

            # Check if this is a sitemap index
            if root.tag.endswith("sitemapindex"):
                for sitemap in root.findall(".//sm:sitemap/sm:loc", self.NAMESPACES):
                    if sitemap.text:
                        result.update(self._fetch_sitemap_with_dates(client, sitemap.text))
                return result

            # Regular sitemap
            for url_elem in root.findall(".//sm:url", self.NAMESPACES):
                loc = url_elem.find("sm:loc", self.NAMESPACES)
                lastmod = url_elem.find("sm:lastmod", self.NAMESPACES)

                if loc is not None and loc.text:
                    lastmod_dt = None
                    if lastmod is not None and lastmod.text:
                        lastmod_dt = self._parse_lastmod(lastmod.text)
                    result[loc.text] = lastmod_dt

            return result

        except Exception:
            return {}

    def _parse_lastmod(self, lastmod_str: str) -> datetime | None:
        """Parse lastmod date string."""
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(lastmod_str, fmt)
            except ValueError:
                continue

        return None

