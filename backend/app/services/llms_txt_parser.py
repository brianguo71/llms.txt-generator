"""Parser for llms.txt files to extract structured sections."""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedLink:
    """A link extracted from a section."""
    title: str
    url: str
    description: str = ""


@dataclass
class ParsedSection:
    """A section parsed from llms.txt."""
    name: str
    description: str = ""
    links: list[ParsedLink] = field(default_factory=list)
    
    def get_urls(self) -> set[str]:
        """Get all URLs in this section."""
        return {link.url for link in self.links}


@dataclass
class ParsedLlmsTxt:
    """Fully parsed llms.txt structure."""
    site_title: str = ""
    tagline: str = ""
    overview: str = ""
    sections: list[ParsedSection] = field(default_factory=list)
    footer: str = ""
    
    def get_section_by_name(self, name: str) -> ParsedSection | None:
        """Find a section by name (case-insensitive)."""
        name_lower = name.lower()
        for section in self.sections:
            if section.name.lower() == name_lower:
                return section
        return None
    
    def get_all_urls(self) -> set[str]:
        """Get all URLs across all sections."""
        urls = set()
        for section in self.sections:
            urls.update(section.get_urls())
        return urls


class LlmsTxtParser:
    """Parse llms.txt markdown into structured data."""
    
    def parse(self, content: str) -> ParsedLlmsTxt:
        """Parse llms.txt content into structured format."""
        if not content:
            return ParsedLlmsTxt()
        
        lines = content.split('\n')
        result = ParsedLlmsTxt()
        
        current_section: ParsedSection | None = None
        in_links_block = False
        overview_lines: list[str] = []
        description_lines: list[str] = []
        parsing_overview = False
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Skip empty lines at start
            if not stripped and not result.site_title:
                i += 1
                continue
            
            # First non-empty line is the title (# Title)
            if not result.site_title and stripped.startswith('# '):
                result.site_title = stripped[2:].strip()
                i += 1
                continue
            
            # Line after title starting with > is tagline
            if result.site_title and not result.tagline and stripped.startswith('> '):
                result.tagline = stripped[2:].strip()
                parsing_overview = True
                i += 1
                continue
            
            # Check for section header (## Section Name)
            if stripped.startswith('## '):
                # Save any pending overview
                if parsing_overview and overview_lines:
                    result.overview = '\n'.join(overview_lines).strip()
                    parsing_overview = False
                    overview_lines = []
                
                # Save previous section's description
                if current_section and description_lines:
                    current_section.description = '\n'.join(description_lines).strip()
                    description_lines = []
                
                # Start new section
                section_name = stripped[3:].strip()
                current_section = ParsedSection(name=section_name)
                result.sections.append(current_section)
                in_links_block = False
                i += 1
                continue
            
            # Check for links subsection (### Links)
            if stripped == '### Links' or stripped.lower() == '### links':
                # Save description before links
                if current_section and description_lines:
                    current_section.description = '\n'.join(description_lines).strip()
                    description_lines = []
                in_links_block = True
                i += 1
                continue
            
            # Parse link lines (- [Title](URL): Description)
            if in_links_block and current_section and stripped.startswith('- '):
                link = self._parse_link_line(stripped)
                if link:
                    current_section.links.append(link)
                i += 1
                continue
            
            # Check for footer (starts with ---)
            # Only treat as footer if it's near the end and followed by footer-like content
            if stripped.startswith('---'):
                # Look ahead to see if this is a section separator or the actual footer
                # Footer typically contains "This document helps AI systems" or similar
                remaining_content = '\n'.join(lines[i+1:]).strip()
                
                # If there are section headers (##) after this, it's a separator not footer
                if remaining_content and '## ' in remaining_content:
                    # This is a section separator, skip it
                    i += 1
                    continue
                
                # This is the actual footer
                # Save any pending section description
                if current_section and description_lines:
                    current_section.description = '\n'.join(description_lines).strip()
                    description_lines = []
                
                # Rest is footer
                footer_lines = []
                i += 1
                while i < len(lines):
                    footer_lines.append(lines[i])
                    i += 1
                result.footer = '\n'.join(footer_lines).strip()
                break
            
            # Accumulate lines for overview or section description
            if parsing_overview:
                overview_lines.append(line)
            elif current_section:
                if not in_links_block:
                    description_lines.append(line)
            
            i += 1
        
        # Handle any remaining content
        if parsing_overview and overview_lines:
            result.overview = '\n'.join(overview_lines).strip()
        if current_section and description_lines:
            current_section.description = '\n'.join(description_lines).strip()
        
        return result
    
    def _parse_link_line(self, line: str) -> ParsedLink | None:
        """Parse a link line like '- [Title](URL): Description'."""
        # Pattern: - [Title](URL): Description
        # or: - [Title](URL)
        pattern = r'^-\s*\[([^\]]+)\]\(([^)]+)\)(?::\s*(.*))?$'
        match = re.match(pattern, line.strip())
        
        if match:
            title = match.group(1).strip()
            url = match.group(2).strip()
            description = match.group(3).strip() if match.group(3) else ""
            return ParsedLink(title=title, url=url, description=description)
        
        return None
    
    def sections_to_dict(self, parsed: ParsedLlmsTxt) -> dict[str, dict[str, Any]]:
        """Convert parsed sections to a dictionary for comparison."""
        return {
            section.name: {
                "description": section.description,
                "urls": sorted(section.get_urls()),
                "link_count": len(section.links),
            }
            for section in parsed.sections
        }

