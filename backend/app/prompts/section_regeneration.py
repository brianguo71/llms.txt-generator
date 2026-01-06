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

Option 2 - Delete section:
{{
  "action": "delete",
  "reason": "Brief explanation why this section should be removed"
}}

## When to DELETE
Choose "delete" if ANY of these are true:
- Pages have empty or missing "content" fields
- Pages have empty or missing "title" fields  
- Content is just boilerplate (e.g. "Page not found", "Error", "Loading...")
- All pages appear to be deleted, broken, or placeholder pages
- There is no substantive content to describe

## When to KEEP
Choose "keep" only if pages have meaningful content you can describe.

## Rules
- Base content only on the provided pages - do not hallucinate content
- Scale length proportionally to content depth (fewer pages = shorter description)
- Avoid generic marketing phrases ("cutting-edge", "industry-leading", "seamlessly")
- Do not invent features not evidenced in the page data
- Return ONLY valid JSON, no markdown code fences"""

