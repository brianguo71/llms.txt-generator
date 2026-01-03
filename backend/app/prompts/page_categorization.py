"""Prompt for categorizing newly discovered pages into existing or new sections."""

PAGE_CATEGORIZATION_PROMPT = """Categorize these newly discovered pages.

## Site Context
Site: {site_title}
Tagline: {site_tagline}
Existing sections: {existing_sections}

## New Pages
{pages_data}

## Output
Return JSON:
{{
  "pages": [
    {{
      "url": "https://example.com/new-page",
      "title": "Page Title",
      "description": "One sentence describing this page",
      "category": "Existing Section Name OR suggest new section name"
    }}
  ],
  "new_sections_needed": ["Pricing"]
}}

## Rules
- Prefer existing sections when a page clearly fits
- Only suggest a new section if 2+ pages clearly belong together in a new category
- Use standard categories when possible: Platform Features, Solutions, Resources, Integrations, Pricing, Company
- The "new_sections_needed" array should be empty if all pages fit existing sections
- Return ONLY valid JSON, no markdown code fences"""

