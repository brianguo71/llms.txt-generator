"""Prompt for regenerating a single section's description after content changes."""

SECTION_REGENERATION_PROMPT = """Regenerate the description for the "{section_name}" section.

## Site Context
{site_context}

## Pages in This Section
{pages}

## Output
Return JSON with ONE of these options:

Option 1 - Keep and update section:
{{
  "action": "keep",
  "description": "50-200 words describing this section with bullet points for key features. Explain what this area covers, its benefits, and who it's for."
}}

Option 2 - Delete section (use when pages are empty, deleted, or have no meaningful content):
{{
  "action": "delete",
  "reason": "Brief explanation why this section should be removed"
}}

## Rules
- If pages have little/no meaningful content, empty content, or only boilerplate text, choose "delete"
- Base content only on the provided pages - do not hallucinate content
- Scale length proportionally to content depth (fewer pages = shorter description)
- Avoid generic marketing phrases ("cutting-edge", "industry-leading", "seamlessly")
- Do not invent features not evidenced in the page data
- Return ONLY valid JSON, no markdown code fences"""

