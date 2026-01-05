"""Prompt for full site curation - generates complete llms.txt structure."""

CURATION_PROMPT = """You are generating structured data for a llms.txt file. This file helps AI systems understand a website's purpose and structure, similar to how a README helps developers.

## Your Task

Analyze the crawled pages and return a JSON object with:
1. A site title (use the ACTUAL site name from the content, never invent one)
2. A one-sentence tagline (10-25 words)
3. A multi-paragraph overview (scales with content depth - see guidelines)
4. Sections with prose descriptions and relevant page links

## Critical: Use Only Actual Content

You MUST base all output on the actual crawled content. Never invent or hallucinate:
- Company names (if no company name is evident, use the domain name or site title from the page)
- Products or services not mentioned in the pages
- Features, capabilities, or benefits not explicitly described

If the crawled content is:
- A quote collection, blog, or content aggregator: describe it as such
- Minimal or unclear: produce minimal output reflecting only what's evident
- Not a company/product site: adapt the structure accordingly (e.g., "Content" instead of "Platform Features")

## Content Scaling Guidelines

Scale your output proportionally to the source content depth:

| Site Complexity | Overview Length | Sections | Section Prose |
|-----------------|-----------------|----------|---------------|
| Minimal (1-2 pages) | 25-50 words | 1-2 | 25-50 words each |
| Simple (3-5 pages) | 50-100 words | 1-2 | 50-100 words each |
| Medium (10-20 pages) | 150-250 words | 3-4 | 100-200 words each |
| Complex (20+ pages) | 250-400 words | 5-7 | 150-300 words each |

## Selection Criteria

**INCLUDE** pages that describe:
- What the company/product/service does (about, features, platform)
- Key capabilities and offerings (products, solutions, integrations)
- Documentation, guides, or educational content
- Pricing or plans
- Contact, team, or company information

**EXCLUDE**:
- Individual listings (job posts, product items, blog articles)
- Category, filter, or browse pages
- Geographic or location-specific pages
- User account pages (login, register, dashboard)
- Legal boilerplate (privacy policy, terms of service)
- Pagination or archive pages

## Output Format

Return ONLY a valid JSON object with this exact structure:
{{
  "site_title": "Company/Product Name",
  "tagline": "One impactful sentence describing core value proposition (10-25 words)",
  "overview": "Paragraph overview describing the company/product, its mission, target audience, and primary capabilities. Length scales with content depth.",
  "sections": [
    {{
      "name": "Platform Features",
      "description": "Prose description (50-300 words) explaining this area. Describe what the features are, how they work, their benefits, and who they're for. Use bullet points within the prose where appropriate to highlight key aspects.",
      "pages": [
        {{
          "url": "<URL from crawled pages above>",
          "title": "Page title from crawled content",
          "description": "One sentence describing this page"
        }}
      ]
    }},
    {{
      "name": "Resources",
      "description": "Description of the resources available, what users can learn, and how they help.",
      "pages": [
        {{
          "url": "<URL from crawled pages above>",
          "title": "Page title from crawled content",
          "description": "Technical documentation and API reference"
        }}
      ]
    }}
  ]
}}

## Section Names

Use these standard section names when appropriate:
- "Platform Features" - core product/feature pages
- "Solutions" - industry or role-specific pages
- "Resources" - guides, docs, learning content
- "Integrations" - third-party connections
- "Pricing" - plans and pricing info
- "Company" - team, about, contact, careers

You may create custom section names if the content clearly warrants it (e.g., "Shopping Analysis" for an e-commerce analytics platform).

## Section Guidelines

- Only create sections with 2+ relevant pages; skip categories with insufficient content
- Each section's prose should explain the overall theme, not just list pages
- Include bullet points within prose to highlight key features or capabilities
- Base all descriptions on actual crawled content - do not invent features

## Anti-Filler Rules

CRITICAL: Generate concise, factual content. Avoid:
- Generic marketing phrases ("cutting-edge", "industry-leading", "seamlessly", "revolutionary")
- Inventing features, capabilities, or benefits not evidenced in the source pages
- Padding short content with vague filler text
- When in doubt, be concise rather than verbose
- NEVER invent company names like "Example Company", "Tech Solutions Inc", or similar placeholders
- If no company name is clear, use the actual site title or domain name

If a site has minimal content, produce minimal output. A 3-page site should NOT have a 400-word overview.
If a site is not a typical company/product site (e.g., a blog, quote collection, personal site), describe what it actually is.

## Pages Crawled

{pages_data}

## Important

- Return ONLY valid JSON, no markdown code fences, no explanation
- The JSON must be parseable by Python's json.loads()
- Scale output length proportionally to input content depth
- **CRITICAL: Only use URLs from the crawled pages listed above. NEVER invent or hallucinate URLs. Each URL in the output MUST appear in the "Pages Crawled" section. Do not use example.com or any placeholder URLs.**"""

