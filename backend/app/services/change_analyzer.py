"""Heuristic-based change significance analyzer.

Analyzes page changes using heuristics (no LLM calls) to determine
if cumulative drift from baseline is significant enough to trigger
a full rescrape.
"""

import logging
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class ChangeAnalyzer:
    """Analyze page changes using heuristics (no LLM calls)."""

    def __init__(self, significance_threshold: int = 30):
        """Initialize analyzer.
        
        Args:
            significance_threshold: Score threshold (0-100) to consider changes significant
        """
        self.significance_threshold = significance_threshold

    def analyze_batch_significance(
        self,
        changed_pages: list[dict],
        total_pages: int,
        bulk_threshold_percent: int = 20,
    ) -> dict:
        """Analyze cumulative significance of changes against baseline.
        
        Args:
            changed_pages: List of dicts with url, baseline_html, current_html
            total_pages: Total number of pages in the project
            bulk_threshold_percent: % of pages changed to auto-trigger rescrape
            
        Returns:
            Dict with significant (bool), score (float), reason (str), etc.
        """
        if not changed_pages:
            return {"significant": False, "score": 0, "reason": "no_changes"}

        # Fast path: if >N% pages have ETag changes, likely significant
        change_ratio = len(changed_pages) / total_pages if total_pages > 0 else 0
        if change_ratio > bulk_threshold_percent / 100:
            return {
                "significant": True,
                "reason": "bulk_change",
                "score": 100,
                "change_ratio": round(change_ratio * 100, 1),
            }

        # Analyze individual page drift from baseline
        scores = []
        for page in changed_pages:
            score = self._analyze_single_page(
                page.get("baseline_html", ""),
                page.get("current_html", ""),
            )
            scores.append({"url": page["url"], "score": score})

        avg_score = sum(s["score"] for s in scores) / len(scores) if scores else 0
        is_significant = avg_score >= self.significance_threshold

        return {
            "significant": is_significant,
            "score": round(avg_score, 1),
            "reason": "cumulative_drift" if is_significant else "below_threshold",
            "pages_analyzed": len(scores),
            "page_scores": scores,
        }

    def _analyze_single_page(self, baseline_html: str, current_html: str) -> int:
        """Score cumulative drift from baseline (0-100).
        
        Scoring breakdown:
        - Diff percentage: up to 40 points
        - Title changed: 20 points
        - Nav structure changed: 25 points
        - Content length delta > 30%: 15 points
        
        Args:
            baseline_html: HTML content from last full rescrape
            current_html: Current HTML content
            
        Returns:
            Score from 0-100
        """
        if not baseline_html or not current_html:
            return 0

        score = 0

        # Diff percentage (weight: 40%)
        diff_pct = self._calc_diff_percentage(baseline_html, current_html)
        score += min(40, diff_pct * 0.4)

        # Title changed (weight: 20%)
        if self._title_changed(baseline_html, current_html):
            score += 20

        # Nav structure changed (weight: 25%)
        if self._nav_changed(baseline_html, current_html):
            score += 25

        # Content length delta > 30% (weight: 15%)
        if self._significant_length_change(baseline_html, current_html):
            score += 15

        return min(100, int(score))

    def _calc_diff_percentage(self, old: str, new: str) -> float:
        """Calculate percentage of content that changed.
        
        Uses quick length-based estimate for very different sizes,
        otherwise samples and uses SequenceMatcher.
        """
        if not old or not new:
            return 100.0 if old != new else 0.0

        # Use quick length-based estimate for very different sizes
        max_len = max(len(old), len(new))
        min_len = min(len(old), len(new))
        len_ratio = min_len / max_len if max_len > 0 else 1

        if len_ratio < 0.5:
            return (1 - len_ratio) * 100

        # For similar lengths, use SequenceMatcher (can be slow for large content)
        # Sample first 10KB to avoid performance issues
        old_sample = old[:10000]
        new_sample = new[:10000]
        ratio = SequenceMatcher(None, old_sample, new_sample).quick_ratio()
        return (1 - ratio) * 100

    def _title_changed(self, old: str, new: str) -> bool:
        """Check if <title> tag content changed."""
        old_title = re.search(r"<title[^>]*>(.*?)</title>", old, re.I | re.S)
        new_title = re.search(r"<title[^>]*>(.*?)</title>", new, re.I | re.S)
        old_text = old_title.group(1).strip() if old_title else ""
        new_text = new_title.group(1).strip() if new_title else ""
        return old_text != new_text

    def _nav_changed(self, old: str, new: str) -> bool:
        """Check if navigation structure changed significantly."""

        def get_nav_links(html: str) -> set:
            # Try <nav> first
            nav_match = re.search(r"<nav[^>]*>(.*?)</nav>", html, re.I | re.S)
            if not nav_match:
                # Try header as fallback
                nav_match = re.search(r"<header[^>]*>(.*?)</header>", html, re.I | re.S)
            if not nav_match:
                return set()
            # Extract href values, excluding anchors
            links = re.findall(r'href=["\']([^"\'#]+)["\']', nav_match.group(1))
            return set(links)

        old_links = get_nav_links(old)
        new_links = get_nav_links(new)

        if not old_links and not new_links:
            return False
        if not old_links or not new_links:
            return True

        # More than 20% of nav links changed
        diff = len(old_links.symmetric_difference(new_links))
        max_links = max(len(old_links), len(new_links))
        return diff / max_links > 0.2 if max_links > 0 else False

    def _significant_length_change(self, old: str, new: str) -> bool:
        """Check if content length changed by more than 30%."""
        if len(old) == 0:
            return len(new) > 1000  # Only significant if new content is substantial
        ratio = abs(len(new) - len(old)) / len(old)
        return ratio > 0.3

