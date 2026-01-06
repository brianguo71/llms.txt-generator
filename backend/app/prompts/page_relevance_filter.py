"""Prompt for batch-classifying pages as relevant or irrelevant for llms.txt."""

PAGE_RELEVANCE_PROMPT = """Classify which pages are relevant for a llms.txt file.

## Context
llms.txt describes a website's purpose, features, and key content for AI systems.
It should include pages that help understand what the company/product does, NOT individual items or listings.

## Pages to Classify
{pages_data}

## Classification Rules

INCLUDE pages that:
- Describe the company, product, or service (about, overview, platform)
- Explain features, capabilities, or offerings
- Provide documentation, guides, or educational content
- Show pricing or plans
- Contain team, careers overview, or contact info
- Are hub/overview pages for a category (e.g., "Blog" main page, "Careers" overview)

EXCLUDE pages that:
- Are empty or contain no/minimal content
- Are individual items in a collection (single blog post, single job listing, single product)
- Are category, filter, tag, or search result pages
- Are user account or authentication pages
- Are legal boilerplate (privacy, terms) unless uniquely informative
- Are paginated archives (/page/2, ?page=3)
- Are date-based archives (/2024/01/)
- Are author pages or contributor profiles
- Are geographic/location-specific variants of the same content

## Output
Return ONLY a JSON object with relevant URLs:
{{
  "relevant_urls": ["https://example.com/features", "https://example.com/pricing"]
}}

Return ONLY valid JSON, no explanation or markdown code fences."""

