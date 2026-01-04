"""Prompt for analyzing whether website changes are significant enough to warrant regeneration."""

CHANGE_SIGNIFICANCE_PROMPT = """
Analyze the changes between old and new website content.
Determine if these changes are significant enough to warrant regenerating the site's llms.txt.

SIGNIFICANT changes (score 70-100):
- New product/feature announcements
- Pricing changes
- New sections or pages
- Company information updates
- Substantial content additions or removals
- Navigation structure changes
- New services or offerings

NOT SIGNIFICANT changes (score 0-30):
- Date/time updates (copyright year, "last updated")
- Advertisement changes
- Minor typo fixes
- Session/cookie banners
- Analytics/tracking changes
- Slight rewording without new information
- Social media follower counts
- Stock prices or dynamic data

OLD CONTENT:
{old_content}

NEW CONTENT:
{new_content}

Respond with JSON only (no markdown, no explanation outside JSON):
{{"score": <0-100>, "reason": "<one sentence explanation>"}}
"""

