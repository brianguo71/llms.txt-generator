"""Prompt for generating descriptions for individual pages."""

PAGE_DESCRIPTION_PROMPT = """Generate a description and category for each of these web pages.

## Context

Site: {site_title}
Site description: {site_tagline}

## Pages to Describe

{pages_data}

## Category Options

Assign each page to ONE of these categories:
- "Features" - core product/feature pages
- "Solutions" - industry or role-specific pages
- "Resources" - guides, docs, learning content
- "Integrations" - third-party connections
- "Pricing" - plans and pricing info
- "Company" - team, about, contact, careers

## Output Format

Return ONLY a valid JSON array:
[
  {{
    "url": "https://example.com/page",
    "title": "Page Title",
    "description": "One sentence describing what this page contains",
    "category": "Category Name"
  }}
]

## Important

- One clear sentence per description
- Return ONLY valid JSON, no markdown code fences
- Include all pages from the input"""

