"""LLM prompts for various tasks."""

from app.prompts.full_site_curation import CURATION_PROMPT
from app.prompts.page_categorization import PAGE_CATEGORIZATION_PROMPT
from app.prompts.page_description import PAGE_DESCRIPTION_PROMPT
from app.prompts.page_relevance_filter import PAGE_RELEVANCE_PROMPT
from app.prompts.section_regeneration import SECTION_REGENERATION_PROMPT
from app.prompts.semantic_significance import (
    SEMANTIC_SIGNIFICANCE_PROMPT,
    BATCH_SEMANTIC_SIGNIFICANCE_PROMPT,
)

__all__ = [
    "CURATION_PROMPT",
    "PAGE_CATEGORIZATION_PROMPT",
    "PAGE_DESCRIPTION_PROMPT",
    "PAGE_RELEVANCE_PROMPT",
    "SECTION_REGENERATION_PROMPT",
    "SEMANTIC_SIGNIFICANCE_PROMPT",
    "BATCH_SEMANTIC_SIGNIFICANCE_PROMPT",
]
