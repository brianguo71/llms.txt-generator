"""Prompt for evaluating semantic significance of content changes."""

SEMANTIC_SIGNIFICANCE_PROMPT = """Evaluate if a webpage's content change is significant enough to warrant updating its description in an llms.txt file.

## Context
llms.txt contains AI-friendly descriptions of webpages. We need to determine if content changes are meaningful enough to regenerate the description, or if they're minor/cosmetic changes that don't affect the page's core purpose.

## Page URL
{page_url}

## Previous Content (truncated)
{old_content}

## New Content (truncated)
{new_content}

## Evaluation Criteria

SIGNIFICANT changes (require description update):
- Page title/header changed
- Core purpose or function of the page changed
- Major features added, removed, or substantially modified
- Key product/service offerings changed
- Target audience or use cases changed
- Technical requirements or integrations changed
- Page was restructured with different main topics
- Major rewrites of the page (>50 words)

NOT SIGNIFICANT changes (keep existing description):
- Minor rewrites of the page (<50 words)
- Pricing changes
- Typo fixes, grammar corrections, punctuation changes
- Date or version number updates
- Minor wording tweaks that don't change meaning
- Formatting or layout changes
- Added/removed testimonials or social proof
- Updated statistics or metrics that don't change the core message
- Copyright year updates
- Added/removed decorative content (images, icons)
- Navigation or footer changes
- Minor additions that don't affect the main purpose

## Output
Return ONLY a JSON object:
{{
  "is_significant": true/false,
  "reason": "Brief explanation of why the change is or isn't significant"
}}

Return ONLY valid JSON, no explanation or markdown code fences."""


BATCH_SEMANTIC_SIGNIFICANCE_PROMPT = """Evaluate if webpage content changes are significant enough to warrant updating descriptions in an llms.txt file.

## Context
llms.txt contains AI-friendly descriptions of webpages. We need to determine which pages have meaningful changes requiring description updates vs minor/cosmetic changes.

## Pages to Evaluate
{pages_data}

## Evaluation Criteria

SIGNIFICANT changes (require description update):
- Core purpose or function of the page changed
- Major features added, removed, or substantially modified
- Key product/service offerings changed
- Target audience or use cases changed
- Technical requirements or integrations changed

NOT SIGNIFICANT changes (keep existing description):
- Pricing changes
- Typo fixes, grammar corrections, minor wording tweaks
- Date, version, or copyright year updates
- Formatting, layout, or navigation changes
- Updated statistics that don't change core message
- Added/removed testimonials or decorative content

## Output
Return ONLY a JSON object with URLs that have SIGNIFICANT changes:
{{
  "significant_urls": ["https://example.com/values", "https://example.com/features"],
  "reasons": {{
    "https://example.com/values": "Values were updated",
    "https://example.com/features": "Features were updated"
  }}
}}

Return ONLY valid JSON, no explanation or markdown code fences."""

