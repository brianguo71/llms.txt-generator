"""LLM-based page curation and summarization for llms.txt generation."""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.config import Settings
from app.prompts import (
    CHANGE_SIGNIFICANCE_PROMPT,
    CURATION_PROMPT,
    PAGE_CATEGORIZATION_PROMPT,
    PAGE_DESCRIPTION_PROMPT,
    PAGE_RELEVANCE_PROMPT,
    SECTION_REGENERATION_PROMPT,
)

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


@dataclass
class PageCategorizationResult:
    """Result of categorizing newly discovered pages."""
    pages: list[CuratedPageData]
    new_sections_needed: list[str]
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
            if markdown:
                # Truncate to ~500 chars for prompt efficiency
                preview = markdown[:500].strip()
                if len(markdown) > 500:
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
        
        # Parse sections from new schema
        sections = []
        for section_data in data.get("sections", []):
            section_pages = [
                CuratedPageData(
                    url=p.get("url", ""),
                    title=p.get("title", ""),
                    description=p.get("description", ""),
                    category=section_data.get("name", "Other"),
                )
                for p in section_data.get("pages", [])
            ]
            
            sections.append(SectionData(
                name=section_data.get("name", ""),
                description=section_data.get("description", ""),
                pages=section_pages,
            ))
        
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

    def regenerate_section(
        self,
        section_name: str,
        pages: list[dict[str, Any]],
        site_title: str,
        site_tagline: str,
    ) -> SectionRegenerationResult:
        """Regenerate prose description for a single section.
        
        Used when pages within a section change during targeted recrawl.
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

    def analyze_change_significance(
        self,
        old_content: str,
        new_content: str,
    ) -> dict[str, Any]:
        """Analyze whether content changes are significant enough to regenerate llms.txt.
        
        Args:
            old_content: Previous homepage content (markdown, truncated)
            new_content: New homepage content (markdown, truncated)
            
        Returns:
            Dict with "score" (0-100) and "reason" (brief explanation)
        """
        # Truncate content to avoid token limits
        max_chars = 3000
        old_truncated = old_content[:max_chars] if old_content else "(empty)"
        new_truncated = new_content[:max_chars] if new_content else "(empty)"
        
        prompt = CHANGE_SIGNIFICANCE_PROMPT.format(
            old_content=old_truncated,
            new_content=new_truncated,
        )
        
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
        logger.info(f"Change significance prompt hash: {prompt_hash}")
        
        response = self._call_llm(prompt)
        
        # Parse JSON response
        try:
            # Clean up response - remove markdown code blocks if present
            clean_response = response.strip()
            if clean_response.startswith("```"):
                lines = clean_response.split("\n")
                clean_response = "\n".join(lines[1:-1])
            
            result = json.loads(clean_response)
            
            score = int(result.get("score", 0))
            reason = result.get("reason", "No reason provided")
            
            logger.info(f"Change significance: score={score}, reason={reason}")
            
            return {
                "score": max(0, min(100, score)),  # Clamp to 0-100
                "reason": reason,
            }
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse change significance response: {e}")
            logger.warning(f"Raw response: {response[:200]}")
            
            # Default to significant if parsing fails (safer to regenerate)
            return {
                "score": 75,
                "reason": "Failed to parse LLM response, defaulting to significant",
            }
