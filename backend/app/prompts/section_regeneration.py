"""Prompt for regenerating a single section's description after content changes."""

SECTION_REGENERATION_PROMPT = """Regenerate the description for the "{section_name}" section.

## Site Context
Site: {site_title}
Tagline: {site_tagline}

## Pages in This Section
{pages_data}

## Output
Return JSON with:
{{
  "description": "50-200 words describing this section with bullet points for key features. Explain what this area covers, its benefits, and who it's for."
}}

## Rules
- Base content only on the provided pages
- Scale length proportionally to content depth (fewer pages = shorter description)
- Avoid generic marketing phrases ("cutting-edge", "industry-leading", "seamlessly")
- Do not invent features not evidenced in the page data
- Return ONLY valid JSON, no markdown code fences"""

