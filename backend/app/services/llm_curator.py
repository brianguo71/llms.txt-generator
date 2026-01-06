"""LLM-based page curation and summarization for llms.txt generation."""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.config import Settings
from app.prompts import (
    BATCH_SEMANTIC_SIGNIFICANCE_PROMPT,
    CURATION_PROMPT,
    PAGE_CATEGORIZATION_PROMPT,
    PAGE_DESCRIPTION_PROMPT,
    PAGE_RELEVANCE_PROMPT,
    SECTION_REGENERATION_PROMPT,
    SEMANTIC_SIGNIFICANCE_PROMPT,
)
from app.services.llms_txt_parser import LlmsTxtParser, ParsedLlmsTxt

logger = logging.getLogger(__name__)

# Fixed seed for deterministic output (OpenAI only)
DETERMINISTIC_SEED = 42


@dataclass
class CuratedPageData:
    """Data for a single curated page."""
    url: str
    title: str
    description: str
    category: str


@dataclass
class SectionData:
    """Data for a curated section with prose description."""
    name: str
    description: str  # Prose description (50-300 words)
    pages: list[CuratedPageData] = field(default_factory=list)


@dataclass
class FullCurationResult:
    """Result of full LLM curation (initial crawl) with section-based structure."""
    site_title: str
    tagline: str
    overview: str
    sections: list[SectionData]
    model_used: str
    prompt_hash: str


@dataclass
class PageDescriptionResult:
    """Result of selective page description generation."""
    pages: list[CuratedPageData]
    model_used: str


@dataclass
class SectionRegenerationResult:
    """Result of regenerating a single section's prose."""
    description: str
    model_used: str
    should_delete: bool = False
    delete_reason: str = ""


@dataclass
class PageCategorizationResult:
    """Result of categorizing newly discovered pages."""
    pages: list[CuratedPageData]
    new_sections_needed: list[str]
    model_used: str


@dataclass
class SemanticSignificanceResult:
    """Result of evaluating semantic significance of content changes."""
    significant_urls: list[str]
    reasons: dict[str, str]  # url -> reason
    model_used: str


class LLMCurator:
    """Curates and summarizes pages using LLM APIs."""

    SECTION_ORDER = [
        "Platform Features",
        "Solutions",
        "Integrations",
        "Resources",
        "Pricing",
        "Company",
        "Other",
    ]

    def __init__(self, settings: Settings):
        self.settings = settings
        self._openai_client = None
        self._anthropic_client = None

    def _get_openai_client(self):
        """Lazy load OpenAI client."""
        if self._openai_client is None:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=self.settings.openai_api_key)
        return self._openai_client

    def _get_anthropic_client(self):
        """Lazy load Anthropic client."""
        if self._anthropic_client is None:
            from anthropic import Anthropic
            self._anthropic_client = Anthropic(api_key=self.settings.anthropic_api_key)
        return self._anthropic_client

    def format_pages_for_prompt(self, pages: list[dict[str, Any]]) -> str:
        """Format crawled page data for the LLM prompt.
        
        Uses markdown content from Firecrawl, truncated for efficiency.
        Falls back to first_paragraph/h2s for legacy data.
        """
        formatted = []
        for i, page in enumerate(pages, 1):
            url = page.get("url", "")
            title = page.get("title", "Untitled") or "Untitled"
            
            entry = f"{i}. URL: {url}\n"
            entry += f"   Title: {title}\n"
            
            # Prefer markdown content from Firecrawl
            markdown = page.get("markdown", "")
            if markdown and len(markdown.strip()) > 50:
                # Truncate to ~2000 chars for prompt efficiency
                preview = markdown[:2000].strip()
                if len(markdown) > 2000:
                    preview += "..."
                entry += f"   Content:\n{preview}\n"
            else:
                # Fallback for legacy data without markdown
                first_para = (page.get("first_paragraph") or "")[:200]
                h2s = (page.get("h2_headings") or page.get("h2s") or [])[:5]
                if first_para:
                    entry += f"   Preview: {first_para}...\n"
                if h2s:
                    entry += f"   Sections: {', '.join(h2s)}\n"
                
                # Explicitly indicate empty pages to help LLM filter
                if not first_para and not h2s and not markdown:
                    entry += f"   Content: [EMPTY PAGE - NO CONTENT]\n"
            
            formatted.append(entry)
        
        return "\n".join(formatted)

    def _call_openai(self, prompt: str, model: str = "gpt-4o-mini") -> str:
        """Call OpenAI API with deterministic settings."""
        client = self._get_openai_client()
        
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            seed=DETERMINISTIC_SEED,
            response_format={"type": "json_object"},
        )
        
        logger.info(f"OpenAI fingerprint: {response.system_fingerprint}")
        return response.choices[0].message.content

    def _call_anthropic(self, prompt: str, model: str = "claude-3-haiku-20240307") -> str:
        """Call Anthropic API."""
        client = self._get_anthropic_client()
        
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        
        return response.content[0].text

    def _call_llm(self, prompt: str) -> str:
        """Call configured LLM provider."""
        provider = self.settings.llm_provider
        model = self.settings.llm_model
        
        logger.info(f"Calling {provider} {model}...")
        
        if provider == "openai":
            return self._call_openai(prompt, model)
        elif provider == "anthropic":
            return self._call_anthropic(prompt, model)
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

    def _parse_json(self, response: str) -> dict | list:
        """Parse JSON from LLM response, handling code fences."""
        content = response.strip()
        
        # Remove markdown code fences if present
        if content.startswith("```"):
            first_newline = content.find("\n")
            if first_newline != -1:
                content = content[first_newline + 1:]
            if content.endswith("```"):
                content = content[:-3].rstrip()
        
        return json.loads(content)

    def curate_full(self, pages: list[dict[str, Any]]) -> FullCurationResult:
        """Full curation: generate site overview and section-based structure.
        
        Used for initial crawl and manual re-scrapes.
        Returns sections with prose descriptions instead of flat page list.
        """
        pages_data = self.format_pages_for_prompt(pages)
        
        prompt = CURATION_PROMPT.format(pages_data=pages_data)
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
        logger.info(f"Full curation prompt hash: {prompt_hash}")
        
        response = self._call_llm(prompt)
        response_hash = hashlib.md5(response.encode()).hexdigest()[:8]
        logger.info(f"LLM response hash: {response_hash}")
        
        data = self._parse_json(response)
        
        # Build set of valid URLs from the provided pages
        valid_urls = {p.get("url", "").rstrip("/").lower() for p in pages}
        
        def is_valid_url(url: str) -> bool:
            """Check if URL was in the crawled pages (not hallucinated)."""
            normalized = url.rstrip("/").lower()
            return normalized in valid_urls
        
        # Parse sections from new schema, filtering out hallucinated URLs
        sections = []
        seen_urls = set()  # Track URLs we've already assigned to a section
        for section_data in data.get("sections", []):
            section_pages = []
            for p in section_data.get("pages", []):
                url = p.get("url", "")
                if is_valid_url(url):
                    url_normalized = url.rstrip("/").lower()
                    if url_normalized in seen_urls:
                        continue  # Skip duplicate URL
                    seen_urls.add(url_normalized)
                    section_pages.append(CuratedPageData(
                        url=url,
                        title=p.get("title", ""),
                        description=p.get("description", ""),
                        category=section_data.get("name", "Other"),
                    ))
                else:
                    logger.warning(f"Filtered hallucinated URL: {url}")
            
            # Only add section if it has valid pages
            if section_pages:
                sections.append(SectionData(
                    name=section_data.get("name", ""),
                    description=section_data.get("description", ""),
                    pages=section_pages,
                ))
            else:
                logger.warning(f"Skipping section '{section_data.get('name')}' - no valid pages")
        
        return FullCurationResult(
            site_title=data.get("site_title", ""),
            tagline=data.get("tagline", ""),
            overview=data.get("overview", ""),
            sections=sections,
            model_used=self.settings.llm_model,
            prompt_hash=prompt_hash,
        )

    def filter_relevant_pages(
        self,
        pages: list[dict[str, Any]],
        batch_size: int = 25,
    ) -> list[dict[str, Any]]:
        """Filter pages to only those relevant for llms.txt using batch LLM classification.
        
        This replaces hardcoded URL pattern filtering with intelligent LLM-based
        classification. Pages are processed in batches for cost efficiency.
        
        The homepage is always preserved regardless of LLM classification, as it
        provides essential context for understanding the site.
        
        Args:
            pages: List of crawled page data dictionaries
            batch_size: Number of pages to classify per LLM request (default 25)
            
        Returns:
            Filtered list containing only relevant pages (homepage always included)
        """
        if not pages:
            return []
        
        # Always preserve homepage - it's essential context for llms.txt
        homepage = next((p for p in pages if p.get("is_homepage")), None)
        non_homepage_pages = [p for p in pages if not p.get("is_homepage")]
        
        if homepage:
            logger.info(f"Homepage preserved: {homepage.get('url')}")
        
        # Pre-filter: remove obviously empty pages before LLM classification (saves API costs)
        # A page is considered empty if it has < 50 chars of content
        min_content_length = 50
        pages_with_content = []
        empty_pages_filtered = 0
        for p in non_homepage_pages:
            markdown = p.get("markdown", "") or ""
            first_para = p.get("first_paragraph", "") or ""
            content_length = len(markdown.strip()) + len(first_para.strip())
            if content_length >= min_content_length:
                pages_with_content.append(p)
            else:
                empty_pages_filtered += 1
                logger.debug(f"Pre-filtered empty page: {p.get('url')} (content length: {content_length})")
        
        if empty_pages_filtered > 0:
            logger.info(f"Pre-filtered {empty_pages_filtered} empty pages (< {min_content_length} chars content)")
        
        non_homepage_pages = pages_with_content
        
        # If only homepage exists, return it directly
        if not non_homepage_pages:
            return [homepage] if homepage else []
        
        # Build URL to page data map for quick lookup
        url_to_page = {p.get("url"): p for p in non_homepage_pages}
        
        relevant_urls = set()
        total_batches = (len(non_homepage_pages) + batch_size - 1) // batch_size
        
        logger.info(f"Filtering {len(non_homepage_pages)} non-homepage pages in {total_batches} batches (batch_size={batch_size})")
        
        # Process pages in batches
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(non_homepage_pages))
            batch = non_homepage_pages[start_idx:end_idx]
            
            # Format batch for prompt
            pages_data = self.format_pages_for_prompt(batch)
            
            prompt = PAGE_RELEVANCE_PROMPT.format(pages_data=pages_data)
            
            logger.info(f"Filtering batch {batch_num + 1}/{total_batches} ({len(batch)} pages)")
            
            try:
                response = self._call_llm(prompt)
                data = self._parse_json(response)
                
                batch_relevant = data.get("relevant_urls", [])
                relevant_urls.update(batch_relevant)
                
                logger.info(f"Batch {batch_num + 1}: {len(batch_relevant)}/{len(batch)} pages relevant")
                
            except Exception as e:
                # On error, include all pages in batch (fail open)
                logger.warning(f"Batch {batch_num + 1} filtering failed: {e}. Including all pages.")
                relevant_urls.update(p.get("url") for p in batch)
        
        # Build filtered list preserving original page data
        filtered_pages = [
            url_to_page[url]
            for url in relevant_urls
            if url in url_to_page
        ]
        
        # Always include homepage at the beginning (most important page)
        if homepage:
            filtered_pages.insert(0, homepage)
        
        total_input = len(non_homepage_pages) + (1 if homepage else 0)
        
        
        logger.info(f"Filtering complete: {len(filtered_pages)}/{total_input} pages relevant (homepage always included)")
        
        return filtered_pages

    def evaluate_semantic_significance(
        self,
        pages_with_changes: list[dict[str, Any]],
        batch_size: int = 10,
    ) -> SemanticSignificanceResult:
        """Evaluate semantic significance of content changes for multiple pages.
        
        Takes pages that have hash mismatches and determines which changes
        are semantically significant enough to warrant regenerating descriptions.
        
        Args:
            pages_with_changes: List of dicts with 'url', 'old_content', 'new_content'
            batch_size: Number of pages to evaluate per LLM request
            
        Returns:
            SemanticSignificanceResult with significant URLs and reasons
        """
        if not pages_with_changes:
            return SemanticSignificanceResult(
                significant_urls=[],
                reasons={},
                model_used=self.settings.llm_model,
            )
        
        significant_urls = []
        all_reasons = {}
        total_batches = (len(pages_with_changes) + batch_size - 1) // batch_size
        
        logger.info(f"Evaluating semantic significance for {len(pages_with_changes)} pages in {total_batches} batches")
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(pages_with_changes))
            batch = pages_with_changes[start_idx:end_idx]
            
            # Format batch for prompt
            pages_data = self._format_changes_for_prompt(batch)
            
            prompt = BATCH_SEMANTIC_SIGNIFICANCE_PROMPT.format(pages_data=pages_data)
            
            logger.info(f"Evaluating batch {batch_num + 1}/{total_batches} ({len(batch)} pages)")
            
            try:
                response = self._call_llm(prompt)
                data = self._parse_json(response)
                
                batch_significant = data.get("significant_urls", [])
                batch_reasons = data.get("reasons", {})
                
                significant_urls.extend(batch_significant)
                all_reasons.update(batch_reasons)
                
                logger.info(f"Batch {batch_num + 1}: {len(batch_significant)}/{len(batch)} pages have significant changes")
                
            except Exception as e:
                # On error, assume all changes are significant (fail safe)
                logger.warning(f"Batch {batch_num + 1} evaluation failed: {e}. Assuming all changes significant.")
                for page in batch:
                    url = page.get("url", "")
                    significant_urls.append(url)
                    all_reasons[url] = "Evaluation failed - assuming significant"
        
        logger.info(f"Semantic significance evaluation complete: {len(significant_urls)}/{len(pages_with_changes)} pages have significant changes")
        
        return SemanticSignificanceResult(
            significant_urls=significant_urls,
            reasons=all_reasons,
            model_used=self.settings.llm_model,
        )

    def _format_changes_for_prompt(self, pages: list[dict[str, Any]]) -> str:
        """Format page content changes for the semantic significance prompt."""
        formatted = []
        for i, page in enumerate(pages, 1):
            url = page.get("url", "")
            old_content = page.get("old_content", "")
            new_content = page.get("new_content", "")
            
            # Truncate content for prompt efficiency
            old_preview = old_content[:800].strip() if old_content else "(no previous content)"
            new_preview = new_content[:800].strip() if new_content else "(no new content)"
            
            if len(old_content) > 800:
                old_preview += "..."
            if len(new_content) > 800:
                new_preview += "..."
            
            entry = f"{i}. URL: {url}\n"
            entry += f"   PREVIOUS CONTENT:\n{old_preview}\n\n"
            entry += f"   NEW CONTENT:\n{new_preview}\n"
            
            formatted.append(entry)
        
        return "\n---\n".join(formatted)

    def regenerate_section(
        self,
        section_name: str,
        pages: list[dict[str, Any]],
        site_title: str,
        site_tagline: str,
    ) -> SectionRegenerationResult:
        """Regenerate prose description for a single section.
        
        Used when pages within a section change during targeted recrawl.
        May return should_delete=True if the section should be removed.
        """
        pages_data = self.format_pages_for_prompt(pages)
        
        prompt = SECTION_REGENERATION_PROMPT.format(
            section_name=section_name,
            site_title=site_title,
            site_tagline=site_tagline,
            pages_data=pages_data,
        )
        
        logger.info(f"Regenerating section '{section_name}' with {len(pages)} pages")
        
        response = self._call_llm(prompt)
        data = self._parse_json(response)
        
        # Check if LLM decided to delete the section
        action = data.get("action", "keep")
        if action == "delete":
            logger.info(f"Section '{section_name}' marked for deletion: {data.get('reason', 'no reason provided')}")
            return SectionRegenerationResult(
                description="",
                model_used=self.settings.llm_model,
                should_delete=True,
                delete_reason=data.get("reason", ""),
            )
        
        return SectionRegenerationResult(
            description=data.get("description", ""),
            model_used=self.settings.llm_model,
        )

    def categorize_new_pages(
        self,
        pages: list[dict[str, Any]],
        site_title: str,
        site_tagline: str,
        existing_sections: list[str],
    ) -> PageCategorizationResult:
        """Categorize newly discovered pages.
        
        Used during targeted recrawl when new pages are discovered.
        Returns categorized pages and any new sections that should be created.
        """
        pages_data = self.format_pages_for_prompt(pages)
        
        prompt = PAGE_CATEGORIZATION_PROMPT.format(
            site_title=site_title,
            site_tagline=site_tagline,
            existing_sections=", ".join(existing_sections),
            pages_data=pages_data,
        )
        
        logger.info(f"Categorizing {len(pages)} new pages")
        
        response = self._call_llm(prompt)
        data = self._parse_json(response)
        
        curated_pages = [
            CuratedPageData(
                url=p.get("url", ""),
                title=p.get("title", ""),
                description=p.get("description", ""),
                category=p.get("category", "Other"),
            )
            for p in data.get("pages", [])
        ]
        
        return PageCategorizationResult(
            pages=curated_pages,
            new_sections_needed=data.get("new_sections_needed", []),
            model_used=self.settings.llm_model,
        )

    def curate_pages_only(
        self,
        pages: list[dict[str, Any]],
        site_title: str,
        site_tagline: str,
    ) -> PageDescriptionResult:
        """Generate descriptions for specific pages only.
        
        Used for selective regeneration when only some pages changed.
        Note: This doesn't update section prose - use regenerate_section for that.
        """
        pages_data = self.format_pages_for_prompt(pages)
        
        prompt = PAGE_DESCRIPTION_PROMPT.format(
            site_title=site_title,
            site_tagline=site_tagline,
            pages_data=pages_data,
        )
        
        logger.info(f"Selective curation for {len(pages)} pages")
        
        response = self._call_llm(prompt)
        data = self._parse_json(response)
        
        # Response is a list of pages
        if isinstance(data, dict):
            data = data.get("pages", [])
        
        curated_pages = [
            CuratedPageData(
                url=p.get("url", ""),
                title=p.get("title", ""),
                description=p.get("description", ""),
                category=p.get("category", "Other"),
            )
            for p in data
        ]
        
        return PageDescriptionResult(
            pages=curated_pages,
            model_used=self.settings.llm_model,
        )

    def _is_homepage_url(self, url: str, base_url: str) -> bool:
        """Check if a URL is the homepage of the given base URL.
        
        Handles variations like:
        - https://example.com vs https://example.com/
        - http vs https
        - With or without www
        """
        def normalize(u: str) -> str:
            parsed = urlparse(u)
            # Normalize path: empty or "/" are both homepage
            path = parsed.path.rstrip("/") or ""
            # Remove www. prefix for comparison
            netloc = parsed.netloc.lower().replace("www.", "")
            return f"{netloc}{path}"
        
        return normalize(url) == normalize(base_url)

    def _order_sections(self, sections: list[SectionData]) -> list[SectionData]:
        """Order sections according to SECTION_ORDER, with custom sections at end."""
        ordered = []
        section_by_name = {s.name: s for s in sections}
        
        # Add sections in defined order
        for name in self.SECTION_ORDER:
            if name in section_by_name:
                ordered.append(section_by_name[name])
        
        # Add any custom sections not in the standard order
        for section in sections:
            if section.name not in self.SECTION_ORDER:
                ordered.append(section)
        
        return ordered

    def assemble_llms_txt(
        self,
        site_title: str,
        tagline: str,
        overview: str,
        sections: list[SectionData],
        base_url: str | None = None,
    ) -> str:
        """Assemble llms.txt content from stored curated data in Profound style.
        
        Args:
            site_title: The site's title
            tagline: One-line site tagline
            overview: Multi-paragraph site overview
            sections: List of sections with prose and pages
            base_url: If provided, homepage URL will be filtered from page links
        """
        lines = []
        
        # Title
        lines.append(f"# {site_title}")
        lines.append("")
        
        # Tagline (blockquote)
        if tagline:
            lines.append(f"> {tagline}")
            lines.append("")
        
        # Overview
        if overview:
            lines.append(overview)
            lines.append("")
        
        # Separator before sections
        lines.append("---")
        lines.append("")
        
        # Order sections
        ordered_sections = self._order_sections(sections)
        
        for i, section in enumerate(ordered_sections):
            # Section header
            lines.append(f"## {section.name}")
            lines.append("")
            
            # Section prose description
            if section.description:
                lines.append(section.description)
                lines.append("")
            
            # Filter out homepage from pages
            section_pages = section.pages
            if base_url:
                section_pages = [
                    p for p in section.pages
                    if not self._is_homepage_url(p.url, base_url)
                ]
            
            # Links subsection (if there are pages)
            if section_pages:
                lines.append("### Links")
                lines.append("")
                
                for page in section_pages:
                    desc = f": {page.description}" if page.description else ""
                    lines.append(f"- [{page.title}]({page.url}){desc}")
                lines.append("")
            
            # Separator between sections (not after last)
            if i < len(ordered_sections) - 1:
                lines.append("---")
                lines.append("")
        
        # Final separator and closing statement
        lines.append("---")
        lines.append("")
        lines.append(f"This document helps AI systems understand {site_title}'s purpose and offerings.")
        
        return "\n".join(lines)

    # Legacy method for backward compatibility
    def assemble_llms_txt_legacy(
        self,
        site_title: str,
        tagline: str,
        overview: str,
        pages: list[CuratedPageData],
        base_url: str | None = None,
    ) -> str:
        """Assemble llms.txt from flat page list (legacy format).
        
        This is kept for backward compatibility with existing data.
        Converts flat pages to sections and uses the new assembly method.
        """
        # Group pages by category into sections
        categories: dict[str, list[CuratedPageData]] = {}
        for page in pages:
            if base_url and self._is_homepage_url(page.url, base_url):
                continue
            cat = page.category or "Other"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(page)
        
        # Create sections without prose (legacy mode)
        sections = [
            SectionData(
                name=name,
                description="",  # No prose in legacy mode
                pages=cat_pages,
            )
            for name, cat_pages in categories.items()
        ]
        
        return self.assemble_llms_txt(
            site_title=site_title,
            tagline=tagline,
            overview=overview,
            sections=sections,
            base_url=base_url,
        )

    def analyze_section_significance(
        self,
        existing_llms_txt: str,
        site_url: str,
        crawled_pages: list[dict[str, Any]],
        old_page_hashes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Analyze which sections of llms.txt need regeneration.
        
        Uses DETERMINISTIC comparison (not LLM interpretation) to avoid false positives:
        1. URL comparison - detect pages added/removed
        2. Content hash comparison - detect content changes on existing pages
        
        Args:
            existing_llms_txt: Current llms.txt content (full, no truncation)
            site_url: The site's base URL
            crawled_pages: List of page dicts with 'url', 'title', 'description', 'content_hash'
            old_page_hashes: Dict of url -> content_hash from previous crawl
            
        Returns:
            Dict with:
            - any_changes: True if any section needs regeneration
            - overview_changed: True if site overview needs update
            - sections_to_regenerate: List of section dicts needing regeneration
            - sections_unchanged: List of section names to keep
            - content_changed_urls: List of URLs with content changes
            - summary: Brief explanation
        """
        # Parse existing llms.txt into structured sections
        parser = LlmsTxtParser()
        parsed = parser.parse(existing_llms_txt)
        
        # Get all URLs currently in the llms.txt
        existing_urls = parsed.get_all_urls()
        
        # Get all URLs from the new crawl
        crawled_urls = {page.get("url", "") for page in crawled_pages if page.get("url")}
        
        # Normalize URLs for comparison (remove trailing slashes, etc.)
        def normalize_url(url: str) -> str:
            return url.rstrip("/").lower()
        
        existing_normalized = {normalize_url(u) for u in existing_urls}
        crawled_normalized = {normalize_url(u) for u in crawled_urls}
        
        # Calculate URL differences
        urls_removed = existing_normalized - crawled_normalized
        urls_added = crawled_normalized - existing_normalized
        urls_unchanged = existing_normalized & crawled_normalized
        
        # Build content hash map for new pages
        new_page_hashes = {}
        for page in crawled_pages:
            url = page.get("url", "")
            # Use content_hash if available, otherwise compute from markdown
            content_hash = page.get("content_hash")
            if not content_hash:
                markdown = page.get("markdown", "") or page.get("first_paragraph", "")
                if markdown:
                    content_hash = hashlib.sha256(markdown.encode()).hexdigest()
            if url and content_hash:
                new_page_hashes[normalize_url(url)] = content_hash
        
        # Compare content hashes for URLs that exist in both old and new
        content_changed_urls = []
        if old_page_hashes:
            old_normalized = {normalize_url(u): h for u, h in old_page_hashes.items()}
            
            for url in urls_unchanged:
                old_hash = old_normalized.get(url)
                new_hash = new_page_hashes.get(url)
                
                if old_hash and new_hash and old_hash != new_hash:
                    content_changed_urls.append(url)
            
            if content_changed_urls:
                logger.info(
                    f"Content changes detected for {len(content_changed_urls)} pages: "
                    f"{content_changed_urls[:5]}{'...' if len(content_changed_urls) > 5 else ''}"
                )
        
        logger.info(
            f"URL comparison for {site_url}: "
            f"existing={len(existing_normalized)}, crawled={len(crawled_normalized)}, "
            f"removed={len(urls_removed)}, added={len(urls_added)}, unchanged={len(urls_unchanged)}, "
            f"content_changed={len(content_changed_urls)}"
        )
        
        # Determine which sections are affected
        sections_to_regenerate = []
        sections_unchanged = []
        
        for section in parsed.sections:
            section_urls = {normalize_url(u) for u in section.get_urls()}
            section_removed = section_urls & urls_removed
            section_content_changed = section_urls & set(content_changed_urls)
            
            # Check if any section URLs were removed OR had content changes
            if section_removed or section_content_changed:
                reasons = []
                if section_removed:
                    reasons.append(f"URLs removed: {list(section_removed)[:3]}")
                if section_content_changed:
                    reasons.append(f"Content changed: {list(section_content_changed)[:3]}")
                
                sections_to_regenerate.append({
                    "name": section.name,
                    "reason": "; ".join(reasons),
                    "pages_removed": list(section_removed),
                    "pages_added": [],
                    "content_changed": list(section_content_changed),
                })
            else:
                sections_unchanged.append(section.name)
        
        # Check if we need new sections for added URLs
        # Only suggest new sections if there are MANY new URLs (>30% increase)
        new_sections = []
        if urls_added:
            pct_new = len(urls_added) / max(len(existing_normalized), 1) * 100
            if pct_new > 30:
                new_sections.append({
                    "suggested_name": "New Pages",
                    "pages": list(urls_added)[:10],
                    "reason": f"{len(urls_added)} new URLs ({pct_new:.0f}% increase)",
                })
                logger.info(f"Significant URL additions detected: {len(urls_added)} new URLs ({pct_new:.0f}%)")
        
        # Determine if overview needs updating
        overview_changed = False
        overview_reason = "No significant changes detected"
        
        if len(urls_removed) > len(existing_normalized) * 0.5:
            # More than 50% of URLs removed - major structural change
            overview_changed = True
            overview_reason = f"Major restructure: {len(urls_removed)} URLs removed"
        elif len(content_changed_urls) > len(existing_normalized) * 0.5:
            # More than 50% of pages have content changes - major content update
            overview_changed = True
            overview_reason = f"Major content update: {len(content_changed_urls)} pages changed"
        
        any_changes = (
            overview_changed or 
            len(sections_to_regenerate) > 0 or 
            len(new_sections) > 0 or
            len(content_changed_urls) > 0
        )
        
        if not any_changes:
            summary = f"No changes: all {len(existing_normalized)} URLs present with same content"
        else:
            parts = []
            if urls_removed:
                parts.append(f"{len(urls_removed)} removed")
            if urls_added:
                parts.append(f"{len(urls_added)} added")
            if content_changed_urls:
                parts.append(f"{len(content_changed_urls)} content changed")
            summary = f"Changes: {', '.join(parts)}"
        
        logger.info(
            f"Section significance for {site_url}: "
            f"any_changes={any_changes}, "
            f"overview_changed={overview_changed}, "
            f"sections_to_regenerate={[s['name'] for s in sections_to_regenerate]}, "
            f"sections_unchanged={sections_unchanged}, "
            f"content_changed={len(content_changed_urls)}"
        )
        
        return {
            "any_changes": any_changes,
            "overview_changed": overview_changed,
            "overview_reason": overview_reason,
            "sections_to_regenerate": sections_to_regenerate,
            "sections_unchanged": sections_unchanged,
            "new_sections": new_sections,
            "content_changed_urls": content_changed_urls,
            "summary": summary,
            "parsed_existing": parsed,
        }
    
    def regenerate_section(
        self,
        section_name: str,
        pages: list[dict[str, Any]],
        site_context: str,
    ) -> dict[str, Any]:
        """Regenerate a single section's content.
        
        Args:
            section_name: Name of the section to regenerate
            pages: List of pages belonging to this section
            site_context: Brief context about the site
            
        Returns:
            Dict with section description and formatted links
        """
        prompt = SECTION_REGENERATION_PROMPT.format(
            section_name=section_name,
            site_context=site_context,
            pages=json.dumps([
                {"title": p.get("title", ""), "url": p.get("url", ""), "description": p.get("description", "")}
                for p in pages
            ], indent=2),
        )
        
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
        logger.info(f"Section regeneration prompt hash: {prompt_hash} for section '{section_name}'")
        
        response = self._call_llm(prompt)
        
        try:
            clean_response = response.strip()
            if clean_response.startswith("```"):
                lines = clean_response.split("\n")
                clean_response = "\n".join(lines[1:-1])
            
            result = json.loads(clean_response)
            return {
                "name": section_name,
                "description": result.get("description", ""),
                "pages": result.get("pages", []),
            }
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse section regeneration response: {e}")
            # Return basic section with just the pages
            return {
                "name": section_name,
                "description": "",
                "pages": [{"title": p.get("title", ""), "url": p.get("url", ""), "description": ""} for p in pages],
            }
