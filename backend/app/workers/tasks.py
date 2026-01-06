"""Celery task definitions.

These tasks are thin wrappers that call into the service layer.
The actual business logic lives in the services module.
"""

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import create_engine, delete, func
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models import (
    CrawlJob,
    CuratedPage,
    CuratedSection,
    GeneratedFile,
    GeneratedFileVersion,
    Page,
    Project,
    SiteOverview,
    SiteUrlInventory,
)
from app.workers.celery_app import celery_app

settings = get_settings()
logger = logging.getLogger(__name__)

# Sync engine for Celery tasks (Celery doesn't support async well)
sync_database_url = settings.database_url.replace("+asyncpg", "")
sync_engine = create_engine(sync_database_url)
SyncSessionLocal = sessionmaker(bind=sync_engine)


def _compute_section_hash(pages_data: list[dict], page_urls: list[str]) -> str:
    """Compute a hash of all page content hashes in a section."""
    url_to_hash = {p.get("url"): p.get("content_hash", "") for p in pages_data}
    combined = "|".join(url_to_hash.get(url, "") for url in sorted(page_urls))
    return hashlib.sha256(combined.encode()).hexdigest()


def _save_curated_data(
    session,
    project_id: str,
    site_title: str,
    tagline: str,
    overview: str,
    sections: list,
    pages_data: list[dict],
) -> None:
    """Save or update site overview, curated sections, and curated pages."""
    from app.services.llm_curator import SectionData
    
    # Save/update site overview
    existing_overview = session.query(SiteOverview).filter(
        SiteOverview.project_id == project_id
    ).first()
    
    if existing_overview:
        existing_overview.site_title = site_title
        existing_overview.tagline = tagline
        existing_overview.overview = overview
        existing_overview.updated_at = datetime.now(timezone.utc)
    else:
        new_overview = SiteOverview(
            project_id=project_id,
            site_title=site_title,
            tagline=tagline,
            overview=overview,
        )
        session.add(new_overview)
    
    # Build URL to content_hash map from crawled data
    url_to_hash = {p.get("url"): p.get("content_hash", "") for p in pages_data}
    
    # Delete existing sections and pages (we'll recreate them)
    session.query(CuratedSection).filter(CuratedSection.project_id == project_id).delete()
    session.query(CuratedPage).filter(CuratedPage.project_id == project_id).delete()
    
    # Save sections and pages
    for section in sections:
        page_urls = [p.url for p in section.pages]
        section_hash = _compute_section_hash(pages_data, page_urls)
        
        new_section = CuratedSection(
            project_id=project_id,
            name=section.name,
            description=section.description,
            page_urls=page_urls,
            content_hash=section_hash,
        )
        session.add(new_section)
        
        # Save individual pages within section
        for page in section.pages:
            content_hash = url_to_hash.get(page.url, "")
            
            new_page = CuratedPage(
                project_id=project_id,
                url=page.url,
                title=page.title,
                description=page.description,
                category=section.name,  # Use section name as category
                content_hash=content_hash,
            )
            session.add(new_page)


def _normalize_url(url: str) -> str:
    """Normalize URL for comparison (lowercase, no trailing slash)."""
    return url.rstrip("/").lower()


def _store_url_inventory(
    session,
    project_id: str,
    urls: list[str],
) -> dict:
    """Store or update URL inventory from Firecrawl /map results.
    
    Returns:
        Dict with:
        - new_urls: URLs not previously in inventory
        - removed_urls: URLs in inventory but not in current map
        - existing_urls: URLs in both
        - total_stored: Total URLs now in inventory
    """
    now = datetime.now(timezone.utc)
    
    # Get existing inventory
    existing_inventory = session.query(SiteUrlInventory).filter(
        SiteUrlInventory.project_id == project_id
    ).all()
    existing_urls_map = {_normalize_url(inv.url): inv for inv in existing_inventory}
    existing_url_set = set(existing_urls_map.keys())
    
    # Normalize incoming URLs
    incoming_urls = {_normalize_url(url): url for url in urls if url}
    incoming_url_set = set(incoming_urls.keys())
    
    # Calculate differences
    new_url_keys = incoming_url_set - existing_url_set
    removed_url_keys = existing_url_set - incoming_url_set
    existing_url_keys = existing_url_set & incoming_url_set
    
    # Add new URLs
    for url_key in new_url_keys:
        original_url = incoming_urls[url_key]
        inventory_entry = SiteUrlInventory(
            project_id=project_id,
            url=url_key,  # Store normalized URL
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(inventory_entry)
    
    # Update last_seen for existing URLs
    for url_key in existing_url_keys:
        inv = existing_urls_map[url_key]
        inv.last_seen_at = now
    
    # Note: We don't delete removed URLs - they might come back
    # But we track them for change detection
    
    session.commit()
    
    logger.info(
        f"URL inventory updated: {len(new_url_keys)} new, "
        f"{len(removed_url_keys)} removed, {len(existing_url_keys)} existing"
    )
    
    return {
        "new_urls": [incoming_urls[k] for k in new_url_keys],
        "removed_urls": list(removed_url_keys),
        "existing_urls": [incoming_urls[k] for k in existing_url_keys],
        "total_stored": len(incoming_url_set),
    }


def _get_url_inventory(session, project_id: str) -> set[str]:
    """Get all URLs in the inventory for a project (normalized)."""
    inventory = session.query(SiteUrlInventory.url).filter(
        SiteUrlInventory.project_id == project_id
    ).all()
    return {url for (url,) in inventory}


def _categorize_crawled_pages(
    session,
    project_id: str,
    crawled_pages: list[dict],
) -> dict:
    """Categorize crawled pages against existing curated data.
    
    Returns:
        Dict with:
        - curated_urls: Set of URLs currently in CuratedPage
        - previously_seen_urls: Set of URLs ever crawled (in Page table)
        - still_curated: Pages in both crawl and CuratedPage
        - removed_from_site: URLs in CuratedPage but not in crawl
        - new_urls: Pages in crawl but never seen before
        - previously_filtered: Pages in crawl and Page table, but not in CuratedPage
    """
    # Get existing curated URLs (source of truth for what's in llms.txt)
    curated_pages = session.query(CuratedPage).filter(
        CuratedPage.project_id == project_id
    ).all()
    curated_urls = {_normalize_url(p.url) for p in curated_pages}
    curated_by_url = {_normalize_url(p.url): p for p in curated_pages}
    
    # Get all previously crawled URLs (to identify truly new vs filtered)
    all_pages = session.query(Page).filter(
        Page.project_id == project_id
    ).all()
    previously_seen_urls = {_normalize_url(p.url) for p in all_pages}
    
    # Build map of crawled URLs
    crawled_urls = {_normalize_url(p.get("url", "")) for p in crawled_pages if p.get("url")}
    crawled_by_url = {_normalize_url(p.get("url", "")): p for p in crawled_pages if p.get("url")}
    
    # Categorize
    still_curated = []  # In both crawl and CuratedPage
    removed_from_site = []  # In CuratedPage but not in crawl
    new_urls = []  # Never seen before
    previously_filtered = []  # Seen before but not in CuratedPage
    
    # Check curated pages
    for url_normalized in curated_urls:
        if url_normalized in crawled_urls:
            page_data = crawled_by_url.get(url_normalized)
            curated_page = curated_by_url.get(url_normalized)
            if page_data and curated_page:
                still_curated.append({
                    "url": page_data.get("url"),
                    "page_data": page_data,
                    "curated_page": curated_page,
                })
        else:
            removed_from_site.append(url_normalized)
    
    # Check crawled pages that aren't curated
    for url_normalized, page_data in crawled_by_url.items():
        if url_normalized not in curated_urls:
            if url_normalized in previously_seen_urls:
                previously_filtered.append(page_data)
            else:
                new_urls.append(page_data)
    
    logger.info(
        f"Page categorization: curated={len(curated_urls)}, crawled={len(crawled_urls)}, "
        f"still_curated={len(still_curated)}, removed={len(removed_from_site)}, "
        f"new={len(new_urls)}, previously_filtered={len(previously_filtered)}"
    )
    
    return {
        "curated_urls": curated_urls,
        "previously_seen_urls": previously_seen_urls,
        "curated_by_url": curated_by_url,
        "still_curated": still_curated,
        "removed_from_site": removed_from_site,
        "new_urls": new_urls,
        "previously_filtered": previously_filtered,
    }


def _check_full_regeneration_threshold(
    curated_count: int,
    removed_count: int,
    significant_change_count: int,
    new_relevant_count: int,
    existing_section_count: int,
    new_section_count: int,
) -> tuple[bool, str]:
    """Check if changes warrant full regeneration instead of selective updates.
    
    Returns:
        Tuple of (should_full_regen: bool, reason: str)
    """
    if curated_count == 0:
        return False, "No existing curated pages"
    
    # >50% of curated URLs removed
    removed_pct = (removed_count / curated_count) * 100
    if removed_pct > 50:
        return True, f"{removed_pct:.0f}% of curated URLs removed (major restructure)"
    
    # >50% of curated pages have significant content changes
    significant_pct = (significant_change_count / curated_count) * 100
    if significant_pct > 50:
        return True, f"{significant_pct:.0f}% of curated pages have significant changes (major content overhaul)"
    
    # >30% new relevant URLs
    if curated_count > 0 and new_relevant_count > 0:
        new_pct = (new_relevant_count / curated_count) * 100
        if new_pct > 30:
            return True, f"{new_pct:.0f}% new relevant URLs (major expansion)"
    
    # New sections would outnumber existing
    if new_section_count > 0 and existing_section_count > 0:
        if new_section_count >= existing_section_count:
            return True, f"{new_section_count} new sections >= {existing_section_count} existing (site pivot)"
    
    return False, "Changes within threshold for selective update"


def _assemble_and_save_llms_txt(
    session,
    project_id: str,
    trigger_reason: str,
) -> str:
    """Assemble llms.txt from stored curated data and save it."""
    from app.services.llm_curator import LLMCurator, CuratedPageData, SectionData
    
    # Get project for base URL (used to filter homepage from links)
    project = session.query(Project).filter(
        Project.id == project_id
    ).first()
    
    if not project:
        logger.warning(f"No project found for {project_id}")
        return ""
    
    # Get site overview
    overview = session.query(SiteOverview).filter(
        SiteOverview.project_id == project_id
    ).first()
    
    if not overview:
        logger.warning(f"No site overview found for project {project_id}")
        return ""
    
    # Get all curated sections (ordered by name for deterministic output)
    curated_sections = session.query(CuratedSection).filter(
        CuratedSection.project_id == project_id
    ).order_by(CuratedSection.name).all()
    
    # Get all curated pages grouped by section
    curated_pages = session.query(CuratedPage).filter(
        CuratedPage.project_id == project_id
    ).order_by(CuratedPage.url).all()
    
    # Build sections with pages
    pages_by_category = {}
    for page in curated_pages:
        if page.category not in pages_by_category:
            pages_by_category[page.category] = []
        pages_by_category[page.category].append(page)
    
    sections = []
    for section in curated_sections:
        section_pages = pages_by_category.get(section.name, [])
        sections.append(SectionData(
            name=section.name,
            description=section.description,
            pages=[
                CuratedPageData(
                    url=p.url,
                    title=p.title,
                    description=p.description,
                    category=p.category,
                )
                for p in section_pages
            ],
        ))
    
    # Assemble llms.txt (homepage filtered from links but used for LLM context)
    curator = LLMCurator(settings)
    content = curator.assemble_llms_txt(
        site_title=overview.site_title,
        tagline=overview.tagline,
        overview=overview.overview,
        sections=sections,
        base_url=project.url,
    )
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    logger.info(f"Assembled llms.txt hash: {content_hash[:16]}")
    
    # Get next version number
    max_file_version = session.query(func.max(GeneratedFileVersion.version)).filter(
        GeneratedFileVersion.project_id == project_id
    ).scalar() or 0
    new_file_version = max_file_version + 1
    
    # Save/update current generated file
    existing_file = session.query(GeneratedFile).filter(
        GeneratedFile.project_id == project_id
    ).first()
    
    if existing_file:
        existing_file.content = content
        existing_file.content_hash = content_hash
        existing_file.generated_at = datetime.now(timezone.utc)
    else:
        generated_file = GeneratedFile(
            project_id=project_id,
            content=content,
            content_hash=content_hash,
        )
        session.add(generated_file)
    
    # Save to version history
    file_version = GeneratedFileVersion(
        project_id=project_id,
        version=new_file_version,
        content=content,
        content_hash=content_hash,
        trigger_reason=trigger_reason,
    )
    session.add(file_version)
    logger.info(f"Saved llms.txt version {new_file_version}")
    
    return content


def _merge_llms_txt_sections(
    session,
    project_id: str,
    parsed_existing,
    regenerated_sections: list[dict],
    unchanged_section_names: list[str],
) -> str:
    """Merge regenerated sections with existing llms.txt content.
    
    Args:
        session: Database session
        project_id: Project ID
        parsed_existing: Parsed existing llms.txt (ParsedLlmsTxt)
        regenerated_sections: List of regenerated section dicts
        unchanged_section_names: Names of sections to keep unchanged
        
    Returns:
        Merged llms.txt content as string
    """
    if not parsed_existing:
        logger.warning("No parsed existing content for merge")
        return ""
    
    lines = []
    
    # Header
    lines.append(f"# {parsed_existing.site_title}")
    lines.append("")
    lines.append(f"> {parsed_existing.tagline}")
    lines.append("")
    
    # Overview (keep existing)
    if parsed_existing.overview:
        lines.append(parsed_existing.overview)
        lines.append("")
    
    # Create a map of regenerated sections by name
    regen_by_name = {s["name"]: s for s in regenerated_sections}
    
    # Process each existing section
    for existing_section in parsed_existing.sections:
        section_name = existing_section.name
        
        if section_name in regen_by_name:
            # Use regenerated content
            regen = regen_by_name[section_name]
            lines.append(f"## {section_name}")
            lines.append("")
            if regen.get("description"):
                lines.append(regen["description"])
                lines.append("")
            
            # Add links
            pages = regen.get("pages", [])
            if pages:
                lines.append("### Links")
                lines.append("")
                for page in pages:
                    title = page.get("title", "")
                    url = page.get("url", "")
                    desc = page.get("description", "")
                    if desc:
                        lines.append(f"- [{title}]({url}): {desc}")
                    else:
                        lines.append(f"- [{title}]({url})")
                lines.append("")
            
            logger.info(f"Merged regenerated section: {section_name}")
            
        elif section_name in unchanged_section_names:
            # Keep existing content unchanged
            lines.append(f"## {section_name}")
            lines.append("")
            if existing_section.description:
                lines.append(existing_section.description)
                lines.append("")
            
            if existing_section.links:
                lines.append("### Links")
                lines.append("")
                for link in existing_section.links:
                    if link.description:
                        lines.append(f"- [{link.title}]({link.url}): {link.description}")
                    else:
                        lines.append(f"- [{link.title}]({link.url})")
                lines.append("")
            
            logger.info(f"Kept unchanged section: {section_name}")
    
    # Footer
    lines.append("---")
    lines.append("")
    lines.append(f"This document helps AI systems understand {parsed_existing.site_title}'s purpose and offerings.")
    
    return "\n".join(lines)


def _save_merged_llms_txt(
    session,
    project_id: str,
    content: str,
    trigger_reason: str,
) -> None:
    """Save merged llms.txt content to database."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    logger.info(f"Saving merged llms.txt hash: {content_hash[:16]}")
    
    # Get next version number
    max_file_version = session.query(func.max(GeneratedFileVersion.version)).filter(
        GeneratedFileVersion.project_id == project_id
    ).scalar() or 0
    new_file_version = max_file_version + 1
    
    # Save/update current generated file
    existing_file = session.query(GeneratedFile).filter(
        GeneratedFile.project_id == project_id
    ).first()
    
    if existing_file:
        existing_file.content = content
        existing_file.content_hash = content_hash
        existing_file.generated_at = datetime.now(timezone.utc)
    else:
        generated_file = GeneratedFile(
            project_id=project_id,
            content=content,
            content_hash=content_hash,
        )
        session.add(generated_file)
    
    # Save to version history
    file_version = GeneratedFileVersion(
        project_id=project_id,
        version=new_file_version,
        content=content,
        content_hash=content_hash,
        trigger_reason=trigger_reason,
    )
    session.add(file_version)
    session.commit()
    
    logger.info(f"Saved merged llms.txt version {new_file_version}")


@celery_app.task(bind=True, max_retries=3, soft_time_limit=600, time_limit=660)
def initial_crawl(self, project_id: str, crawl_job_id: str) -> dict:
    """Perform initial crawl of a website.

    This task:
    1. Crawls the website starting from the root URL
    2. Uses LLM to curate and summarize pages (returns JSON with sections)
    3. Stores curated sections and pages in database
    4. Assembles and saves llms.txt in Profound style
    5. Updates project status to 'ready'
    """
    from app.services.crawler_factory import get_crawler_service
    from app.services.llm_curator import LLMCurator
    from app.services.progress import get_progress_service

    progress_service = get_progress_service()
    
    def log_progress(stage: str, current: int, total: int, elapsed: float, current_url: str = "", extra: str = ""):
        """Log progress with time estimate and store in Redis."""
        eta = None
        if current > 0 and total > 0:
            rate = current / elapsed if elapsed > 0 else 0
            eta = (total - current) / rate if rate > 0 else 0
            pct = (current / total) * 100
            logger.info(
                f"[{stage}] {current}/{total} ({pct:.1f}%) | "
                f"Elapsed: {elapsed:.1f}s | ETA: {eta:.1f}s{extra}"
            )
        else:
            logger.info(f"[{stage}] {extra}")
        
        progress_service.update(
            project_id=project_id,
            stage=stage,
            current=current,
            total=total,
            elapsed_seconds=elapsed,
            eta_seconds=eta,
            current_url=current_url if current_url else None,
            extra=extra if extra else None,
        )

    session = SyncSessionLocal()
    start_time = time.time()
    
    try:
        project = session.query(Project).filter(Project.id == project_id).first()
        crawl_job = session.query(CrawlJob).filter(CrawlJob.id == crawl_job_id).first()

        if not project or not crawl_job:
            return {"error": "Project or job not found"}

        project.status = "crawling"
        crawl_job.start()
        session.commit()
        
        logger.info(f"=== Starting crawl for {project.url} ===")
        log_progress(stage="CRAWL", current=0, total=0, elapsed=0, current_url=project.url, extra="Starting crawl")

        # Progress callback for crawler
        crawl_start = time.time()
        def on_crawl_progress(crawled: int, total: int, url: str):
            elapsed = time.time() - crawl_start
            log_progress(
                stage="CRAWL",
                current=crawled,
                total=total,
                elapsed=elapsed,
                current_url=url,
            )

        # Perform crawl
        crawler = get_crawler_service(settings, on_progress=on_crawl_progress)
        pages_data = crawler.crawl_website(project.url)
        crawl_elapsed = time.time() - crawl_start
        
        total_crawled = len(pages_data)
        logger.info(f"=== Crawl complete: {total_crawled} pages in {crawl_elapsed:.1f}s ===")
        log_progress(stage="CRAWL", current=total_crawled, total=total_crawled, elapsed=crawl_elapsed, extra="Complete")

        # Determine trigger reason and flow
        trigger_reason = crawl_job.trigger_reason if crawl_job else "initial"
        curator = LLMCurator(settings)
        
        # Variables for tracking changes
        should_run_full_curation = True
        significance_result = None
        sections_to_regenerate = []
        sections_unchanged = []
        new_relevant_pages = []
        new_sections_needed = []
        pages_with_significant_changes = []
        relevant_pages = []  # Will be populated differently based on trigger
        filter_elapsed = 0.0  # Will be set if filtering occurs
        removed_from_site = []  # URLs removed from site (for selective update)
        
        # Check if we have existing curated data (required for smart change detection)
        has_existing_curated_data = session.query(CuratedPage).filter(
            CuratedPage.project_id == project_id
        ).first() is not None
        
        if trigger_reason == "initial" or (trigger_reason == "manual" and not has_existing_curated_data):
            # INITIAL CRAWL (or manual with no existing data): Filter all pages with LLM
            
            # Map website to build URL inventory
            logger.info("=== Mapping website URLs ===")
            try:
                mapped_urls = crawler.map_website(project.url)
                _store_url_inventory(session, project_id, mapped_urls)
                logger.info(f"=== URL inventory stored: {len(mapped_urls)} URLs ===")
            except Exception as e:
                # Map is optional - don't fail the whole crawl if it doesn't work
                logger.warning(f"Failed to map website URLs: {e}")
            
            logger.info("=== Filtering pages with LLM ===")
            log_progress(stage="FILTER", current=0, total=1, elapsed=0, extra="Classifying page relevance...")
            
            filter_start = time.time()
            relevant_pages = curator.filter_relevant_pages(pages_data, batch_size=25)
            filter_elapsed = time.time() - filter_start
            
            logger.info(f"=== Filtering complete: {len(relevant_pages)}/{total_crawled} pages relevant in {filter_elapsed:.1f}s ===")
            log_progress(stage="FILTER", current=1, total=1, elapsed=filter_elapsed, extra=f"Kept {len(relevant_pages)}/{total_crawled} pages")
        
        elif trigger_reason in ("manual", "scheduled_check", "lightweight_change_detected"):
            # RESCRAPE: Use URL inventory + CuratedPage as source of truth
            logger.info("=== Smart change detection (URL inventory + CuratedPage as source of truth) ===")
            log_progress(stage="ANALYZE", current=0, total=1, elapsed=0, extra="Mapping website URLs...")
            
            analyze_start = time.time()
            
            # Step 1: Map website to get current URLs (fast, reliable)
            try:
                mapped_urls = crawler.map_website(project.url)
                logger.info(f"Mapped {len(mapped_urls)} URLs on site")
            except Exception as e:
                logger.warning(f"Failed to map website, falling back to crawl URLs: {e}")
                mapped_urls = [p.get("url") for p in pages_data if p.get("url")]
            
            # Step 2: Compare to URL inventory to find truly new URLs
            inventory_result = _store_url_inventory(session, project_id, mapped_urls)
            truly_new_urls = set(_normalize_url(u) for u in inventory_result["new_urls"])
            removed_url_keys = set(inventory_result["removed_urls"])
            
            logger.info(f"URL inventory comparison: {len(truly_new_urls)} new, {len(removed_url_keys)} removed")
            
            # Step 3: Get curated pages and their URLs
            curated_pages = session.query(CuratedPage).filter(
                CuratedPage.project_id == project_id
            ).all()
            curated_urls = {_normalize_url(p.url): p for p in curated_pages}
            curated_url_set = set(curated_urls.keys())
            
            # Check which curated URLs are removed from site
            removed_from_site = [url for url in curated_url_set if url in removed_url_keys]
            still_curated_urls = curated_url_set - set(removed_from_site)
            
            logger.info(f"Curated pages: {len(curated_url_set)} total, {len(removed_from_site)} removed, {len(still_curated_urls)} still present")
            
            # Step 4: Build list of URLs to scrape (curated + new)
            urls_to_scrape = list(still_curated_urls | truly_new_urls)
            
            if urls_to_scrape and len(urls_to_scrape) < len(pages_data):
                # Use batch scrape for efficiency - only scrape what we need
                logger.info(f"=== Batch scraping {len(urls_to_scrape)} URLs (curated + new) ===")
                log_progress(stage="CRAWL", current=0, total=len(urls_to_scrape), elapsed=time.time() - analyze_start,
                           extra=f"Scraping {len(urls_to_scrape)} targeted pages...")
                
                try:
                    scraped_pages = crawler.batch_scrape(urls_to_scrape, start_url=project.url)
                    logger.info(f"Batch scrape complete: {len(scraped_pages)} pages")
                except Exception as e:
                    logger.warning(f"Batch scrape failed, using full crawl data: {e}")
                    scraped_pages = pages_data
            else:
                # Use the full crawl data we already have
                scraped_pages = pages_data
            
            # Build URL to page_data map for scraped pages
            scraped_by_url = {_normalize_url(p.get("url", "")): p for p in scraped_pages if p.get("url")}
            
            # Get existing sections for categorization
            existing_sections = session.query(CuratedSection).filter(
                CuratedSection.project_id == project_id
            ).all()
            existing_section_names = [s.name for s in existing_sections]
            
            # Get site overview for context
            site_overview = session.query(SiteOverview).filter(
                SiteOverview.project_id == project_id
            ).first()
            
            # Step 5: Check for content changes in curated pages (hash mismatch)
            pages_with_hash_mismatch = []
            still_curated = []
            for url_normalized in still_curated_urls:
                curated_page = curated_urls.get(url_normalized)
                page_data = scraped_by_url.get(url_normalized)
                
                if not page_data or not curated_page:
                    continue
                
                still_curated.append({
                    "url": page_data.get("url"),
                    "page_data": page_data,
                    "curated_page": curated_page,
                })
                
                # Compare content hashes
                new_hash = page_data.get("content_hash", "")
                old_hash = curated_page.content_hash or ""
                
                if new_hash and old_hash and new_hash != old_hash:
                    pages_with_hash_mismatch.append({
                        "url": page_data.get("url"),
                        "old_content": curated_page.description,
                        "new_content": page_data.get("markdown", "")[:1500],
                        "page_data": page_data,
                        "curated_page": curated_page,
                    })
            
            logger.info(f"Found {len(pages_with_hash_mismatch)} pages with content hash mismatches")
            
            # Step 6: Evaluate semantic significance of hash mismatches
            if pages_with_hash_mismatch:
                logger.info("=== Evaluating semantic significance of content changes ===")
                log_progress(stage="ANALYZE", current=0, total=1, elapsed=time.time() - analyze_start, 
                           extra=f"Checking {len(pages_with_hash_mismatch)} changed pages...")
                
                semantic_result = curator.evaluate_semantic_significance(pages_with_hash_mismatch)
                significant_urls = set(semantic_result.significant_urls)
                
                for item in pages_with_hash_mismatch:
                    url = item["url"]
                    if _normalize_url(url) in {_normalize_url(u) for u in significant_urls}:
                        pages_with_significant_changes.append(item)
                
                logger.info(f"Semantic evaluation: {len(pages_with_significant_changes)}/{len(pages_with_hash_mismatch)} changes are significant")
            
            # Step 7: Filter and categorize truly new URLs
            new_urls = [scraped_by_url[url] for url in truly_new_urls if url in scraped_by_url]
            
            if new_urls:
                logger.info(f"=== Filtering {len(new_urls)} truly new URLs ===")
                log_progress(stage="FILTER", current=0, total=1, elapsed=time.time() - analyze_start,
                           extra=f"Filtering {len(new_urls)} new pages...")
                
                new_relevant = curator.filter_relevant_pages(new_urls, batch_size=25)
                
                if new_relevant:
                    logger.info(f"Found {len(new_relevant)} relevant new pages, categorizing...")
                    
                    if site_overview:
                        categorization = curator.categorize_new_pages(
                            pages=new_relevant,
                            site_title=site_overview.site_title,
                            site_tagline=site_overview.tagline,
                            existing_sections=existing_section_names,
                        )
                        
                        new_relevant_pages = [
                            {"url": p.url, "title": p.title, "description": p.description, "category": p.category}
                            for p in categorization.pages
                        ]
                        new_sections_needed = categorization.new_sections_needed
                        
                        logger.info(f"Categorized {len(new_relevant_pages)} new pages, {len(new_sections_needed)} new sections needed")
                    else:
                        new_relevant_pages = new_relevant
            
            # Create curated_by_url map for compatibility with existing code
            curated_by_url = curated_urls
            
            # Step 8: Check full regeneration threshold
            should_full_regen, full_regen_reason = _check_full_regeneration_threshold(
                curated_count=len(curated_url_set),
                removed_count=len(removed_from_site),
                significant_change_count=len(pages_with_significant_changes),
                new_relevant_count=len(new_relevant_pages),
                existing_section_count=len(existing_section_names),
                new_section_count=len(new_sections_needed),
            )
            
            analyze_elapsed = time.time() - analyze_start
            
            if should_full_regen:
                logger.info(f"=== FULL REGENERATION TRIGGERED: {full_regen_reason} ===")
                log_progress(stage="ANALYZE", current=1, total=1, elapsed=analyze_elapsed,
                           extra=f"Full regen: {full_regen_reason}")
                should_run_full_curation = True
                
                # For full regen, filter all pages fresh
                logger.info("=== Re-filtering all pages for full regeneration ===")
                relevant_pages = curator.filter_relevant_pages(pages_data, batch_size=25)
            else:
                # Selective update path
                any_changes = (
                    len(removed_from_site) > 0 or
                    len(pages_with_significant_changes) > 0 or
                    len(new_relevant_pages) > 0
                )
                
                if any_changes:
                    logger.info(f"=== Selective update: {len(removed_from_site)} removed, "
                              f"{len(pages_with_significant_changes)} changed, {len(new_relevant_pages)} new ===")
                    log_progress(stage="ANALYZE", current=1, total=1, elapsed=analyze_elapsed,
                               extra=f"Selective: -{len(removed_from_site)}, ~{len(pages_with_significant_changes)}, +{len(new_relevant_pages)}")
                    
                    # Determine which sections are affected
                    affected_sections = set()
                    
                    # Sections with removed pages
                    for url in removed_from_site:
                        curated_page = curated_by_url.get(url)
                        if curated_page:
                            affected_sections.add(curated_page.category)
                    
                    # Sections with changed pages
                    for item in pages_with_significant_changes:
                        curated_page = item["curated_page"]
                        affected_sections.add(curated_page.category)
                    
                    # Sections getting new pages
                    for page in new_relevant_pages:
                        if isinstance(page, dict):
                            affected_sections.add(page.get("category", "Other"))
                    
                    sections_to_regenerate = [{"name": name} for name in affected_sections]
                    sections_unchanged = [name for name in existing_section_names if name not in affected_sections]
                    
                    should_run_full_curation = False
                    
                    # Build relevant_pages from still-curated pages for section regeneration
                    relevant_pages = [item["page_data"] for item in still_curated]
                    relevant_pages.extend([p if isinstance(p, dict) else {"url": p.get("url")} for p in new_relevant_pages if isinstance(p, dict)])
                else:
                    logger.info("=== No significant changes detected ===")
                    log_progress(stage="ANALYZE", current=1, total=1, elapsed=analyze_elapsed,
                               extra="No significant changes - keeping existing llms.txt")
                    should_run_full_curation = False
                    
                    # Use still-curated pages as relevant
                    relevant_pages = [item["page_data"] for item in still_curated]

        # Determine curation approach
        curation_result = None
        total_pages = 0
        curate_elapsed = 0.0  # Will be set if curation occurs
        
        if trigger_reason == "initial" or (trigger_reason == "manual" and not has_existing_curated_data) or should_run_full_curation:
            # Full curation for initial crawl, manual with no data, or when thresholds exceeded
            logger.info("=== Curating pages with LLM (full curation) ===")
            log_progress(stage="CURATE", current=0, total=1, elapsed=0, extra="Calling LLM to curate pages...")
            
            curate_start = time.time()
            curation_result = curator.curate_full(pages=relevant_pages)
            
            curate_elapsed = time.time() - curate_start
            total_pages = sum(len(s.pages) for s in curation_result.sections)
            logger.info(f"=== LLM curation complete in {curate_elapsed:.1f}s ===")
            log_progress(stage="CURATE", current=1, total=1, elapsed=curate_elapsed, extra=f"Curated {total_pages} pages in {len(curation_result.sections)} sections")
        
        elif sections_to_regenerate or new_sections_needed:
            # Selective section regeneration
            total_sections = len(sections_to_regenerate) + len(new_sections_needed)
            logger.info(f"=== Regenerating {len(sections_to_regenerate)} sections, creating {len(new_sections_needed)} new sections ===")
            log_progress(stage="CURATE", current=0, total=total_sections, elapsed=0, extra="Regenerating changed sections...")
            
            curate_start = time.time()
            
            # Get site context from site overview
            site_overview = session.query(SiteOverview).filter(
                SiteOverview.project_id == project_id
            ).first()
            site_context = f"{site_overview.site_title}: {site_overview.tagline}" if site_overview else project.url
            
            # Get existing curated pages by category
            existing_curated = session.query(CuratedPage).filter(
                CuratedPage.project_id == project_id
            ).all()
            curated_by_category = {}
            for cp in existing_curated:
                if cp.category not in curated_by_category:
                    curated_by_category[cp.category] = []
                curated_by_category[cp.category].append(cp)
            
            # Build URL to page_data map from relevant_pages
            page_data_by_url = {_normalize_url(p.get("url", "")): p for p in relevant_pages if p.get("url")}
            
            # Regenerate each changed section
            regenerated_sections = []
            section_idx = 0
            
            for section_info in sections_to_regenerate:
                section_name = section_info["name"]
                
                # Get existing curated pages for this section
                section_curated = curated_by_category.get(section_name, [])
                
                # Build section pages from curated pages that still exist in crawl
                section_pages = []
                for cp in section_curated:
                    normalized = _normalize_url(cp.url)
                    page_data = page_data_by_url.get(normalized)
                    if page_data:
                        section_pages.append(page_data)
                
                # Add new pages assigned to this section
                for new_page in new_relevant_pages:
                    if isinstance(new_page, dict) and new_page.get("category") == section_name:
                        url = new_page.get("url", "")
                        page_data = page_data_by_url.get(_normalize_url(url))
                        if page_data and page_data not in section_pages:
                            section_pages.append(page_data)
                
                if section_pages:
                    regen_result = curator.regenerate_section(
                        section_name=section_name,
                        pages=section_pages,
                        site_context=site_context,
                    )
                    regenerated_sections.append(regen_result)
                    logger.info(f"Regenerated section '{section_name}' with {len(section_pages)} pages")
                
                section_idx += 1
                log_progress(
                    stage="CURATE", current=section_idx, total=total_sections,
                    elapsed=time.time() - curate_start, extra=f"Regenerated: {section_name}"
                )
            
            # Create new sections
            for new_section_name in new_sections_needed:
                # Get pages assigned to this new section
                section_pages = []
                for new_page in new_relevant_pages:
                    if isinstance(new_page, dict) and new_page.get("category") == new_section_name:
                        url = new_page.get("url", "")
                        page_data = page_data_by_url.get(_normalize_url(url))
                        if page_data:
                            section_pages.append(page_data)
                
                if section_pages:
                    regen_result = curator.regenerate_section(
                        section_name=new_section_name,
                        pages=section_pages,
                        site_context=site_context,
                    )
                    regenerated_sections.append(regen_result)
                    
                    # Create new CuratedSection
                    new_section = CuratedSection(
                        project_id=project_id,
                        name=new_section_name,
                        description=regen_result.get("description", ""),
                        page_urls=[p.get("url") for p in section_pages],
                        content_hash="",
                    )
                    session.add(new_section)
                    
                    # Add curated pages for new section
                    for page_data in section_pages:
                        new_curated_page = CuratedPage(
                            project_id=project_id,
                            url=page_data.get("url", ""),
                            title=page_data.get("title", ""),
                            description=next(
                                (p.get("description", "") for p in regen_result.get("pages", []) 
                                 if p.get("url") == page_data.get("url")),
                                ""
                            ),
                            category=new_section_name,
                            content_hash=page_data.get("content_hash", ""),
                        )
                        session.add(new_curated_page)
                    
                    logger.info(f"Created new section '{new_section_name}' with {len(section_pages)} pages")
                
                section_idx += 1
                log_progress(
                    stage="CURATE", current=section_idx, total=total_sections,
                    elapsed=time.time() - curate_start, extra=f"Created: {new_section_name}"
                )
            
            curate_elapsed = time.time() - curate_start
            total_pages = sum(len(s.get("pages", [])) for s in regenerated_sections)
            
            # Store regenerated sections for later merging
            curation_result = {
                "type": "selective",
                "regenerated_sections": regenerated_sections,
                "unchanged_sections": sections_unchanged,
                "new_sections": new_sections_needed,
                "removed_urls": removed_from_site,
                "pages_with_changes": pages_with_significant_changes,
            }
            
            logger.info(f"=== Selective curation complete in {curate_elapsed:.1f}s ===")
            log_progress(stage="CURATE", current=total_sections, total=total_sections, elapsed=curate_elapsed, 
                        extra=f"Regenerated {len(regenerated_sections)} sections")
        
        else:
            # No changes - keep existing llms.txt
            logger.info("=== Skipping curation (no significant changes) ===")
            log_progress(stage="CURATE", current=1, total=1, elapsed=0, extra="Skipped - no significant changes")
            curation_result = None
            total_pages = 0

        # Save crawled pages for reference (always, even if skipping curation)
        max_version = session.query(func.max(Page.version)).filter(
            Page.project_id == project_id
        ).scalar() or 0
        new_version = max_version + 1

        for page_data in pages_data:
            # Store markdown content in first_paragraph field for backwards compatibility
            markdown = page_data.get("markdown", "")
            first_para = markdown[:2000] if markdown else page_data.get("first_paragraph")
            
            # Compute baseline hash for lightweight change detection
            content_for_hash = markdown or first_para or ""
            baseline_hash = hashlib.sha256(content_for_hash.encode()).hexdigest() if content_for_hash else None
            
            page = Page(
                project_id=project.id,
                url=page_data.get("url", ""),
                title=page_data.get("title", ""),
                description=page_data.get("description"),
                first_paragraph=first_para,
                content_hash=page_data.get("content_hash"),
                baseline_html_hash=baseline_hash,  # Set baseline for lightweight checks
                depth=page_data.get("depth", 0),
                version=new_version,
                # Clear ETag so first lightweight check fetches fresh headers
                etag=None,
                last_modified_header=None,
            )
            session.add(page)

        # Save curated data and regenerate llms.txt based on curation type
        content_changed = False
        sections_count = 0
        
        if curation_result:
            if isinstance(curation_result, dict) and curation_result.get("type") == "selective":
                # Selective section regeneration - update database and reassemble llms.txt
                logger.info("=== Updating curated data for selective changes ===")
                log_progress(stage="GENERATE", current=0, total=1, elapsed=0, extra="Updating curated data...")
                
                regenerated_sections = curation_result.get("regenerated_sections", [])
                unchanged_section_names = curation_result.get("unchanged_sections", [])
                removed_urls = curation_result.get("removed_urls", [])
                pages_with_changes = curation_result.get("pages_with_changes", [])
                
                # Step 1: Remove curated pages for URLs no longer on the site
                if removed_urls:
                    for url in removed_urls:
                        session.query(CuratedPage).filter(
                            CuratedPage.project_id == project_id,
                            func.lower(CuratedPage.url) == url.lower()
                        ).delete(synchronize_session=False)
                    logger.info(f"Removed {len(removed_urls)} curated pages no longer on site")
                
                # Step 2: Update curated pages with significant content changes
                for item in pages_with_changes:
                    curated_page = item.get("curated_page")
                    page_data = item.get("page_data")
                    if curated_page and page_data:
                        # Find the regenerated description for this page
                        new_description = None
                        for section in regenerated_sections:
                            for page in section.get("pages", []):
                                if _normalize_url(page.get("url", "")) == _normalize_url(curated_page.url):
                                    new_description = page.get("description", "")
                                    break
                            if new_description:
                                break
                        
                        if new_description:
                            curated_page.description = new_description
                            curated_page.content_hash = page_data.get("content_hash", "")
                            curated_page.updated_at = datetime.now(timezone.utc)
                
                # Step 3: Update section descriptions from regenerated sections
                for regen_section in regenerated_sections:
                    section_name = regen_section.get("name", "")
                    section_desc = regen_section.get("description", "")
                    
                    existing_section = session.query(CuratedSection).filter(
                        CuratedSection.project_id == project_id,
                        CuratedSection.name == section_name
                    ).first()
                    
                    if existing_section:
                        existing_section.description = section_desc
                        existing_section.updated_at = datetime.now(timezone.utc)
                
                session.commit()
                
                # Step 4: Reassemble llms.txt from updated database
                _assemble_and_save_llms_txt(session, project.id, trigger_reason)
                
                sections_count = len(regenerated_sections) + len(unchanged_section_names)
                content_changed = True
                
                log_progress(stage="GENERATE", current=1, total=1, elapsed=0, 
                           extra=f"Updated {len(regenerated_sections)} sections, removed {len(removed_urls)} pages")
                
            else:
                # Full curation - save everything fresh
                _save_curated_data(
                    session=session,
                    project_id=project.id,
                    site_title=curation_result.site_title,
                    tagline=curation_result.tagline,
                    overview=curation_result.overview,
                    sections=curation_result.sections,
                    pages_data=pages_data,
                )
                session.commit()

                # Assemble and save llms.txt
                logger.info("=== Saving llms.txt ===")
                log_progress(stage="GENERATE", current=0, total=1, elapsed=0, extra="Assembling llms.txt file")
                
                _assemble_and_save_llms_txt(session, project.id, trigger_reason)
                
                sections_count = len(curation_result.sections)
                content_changed = True
        else:
            # No changes - commit page data only, keep existing llms.txt
            session.commit()
            logger.info("=== Keeping existing llms.txt (no significant changes) ===")
            log_progress(stage="GENERATE", current=1, total=1, elapsed=0, extra="Kept existing - no regeneration needed")
            content_changed = False
        
        # Update project status
        project.status = "ready"
        project.last_checked_at = datetime.now(timezone.utc)
        
        if trigger_reason in ("scheduled_check", "lightweight_change_detected"):
            # Apply backoff based on whether changes were significant
            _schedule_next_check(project, changed=content_changed)
            
            if content_changed:
                logger.info(f"Significant changes for {project.url}, resetting to daily checks")
            else:
                logger.info(f"No significant changes for {project.url}, applying backoff")
            
            # Clear the temporary hash storage
            project.homepage_content_hash = None
        
        total_elapsed = time.time() - start_time
        
        logger.info(f"=== COMPLETE ===")
        logger.info(f"  Pages crawled: {total_crawled}")
        logger.info(f"  Pages relevant: {len(relevant_pages)}")
        logger.info(f"  Pages curated: {total_pages}")
        logger.info(f"  Sections: {sections_count}")
        logger.info(f"  Crawl time: {crawl_elapsed:.1f}s")
        if filter_elapsed > 0:
            logger.info(f"  Filter time: {filter_elapsed:.1f}s")
        if curate_elapsed > 0:
            logger.info(f"  Curation time: {curate_elapsed:.1f}s")
        elif not curation_result:
            logger.info(f"  Curation: Skipped (no significant changes)")
        logger.info(f"  Total time: {total_elapsed:.1f}s")
        
        log_progress(stage="COMPLETE", current=total_crawled, total=total_crawled, elapsed=total_elapsed, extra="Done")
        
        crawl_job.complete(pages_crawled=total_crawled)
        session.commit()

        return {
            "status": "completed",
            "pages_crawled": total_crawled,
            "pages_curated": total_pages,
            "sections": sections_count,
            "significant_changes": content_changed,
            "sections_regenerated": [s["name"] for s in sections_to_regenerate] if sections_to_regenerate else None,
            "curation_type": "full" if (trigger_reason in ("initial", "manual") or should_run_full_curation) else ("selective" if content_changed else "skipped"),
        }

    except SoftTimeLimitExceeded:
        session.rollback()
        logger.error(f"Crawl timed out for project {project_id} (10 minute limit)")
        
        # Mark job as failed with timeout message
        crawl_job = session.query(CrawlJob).filter(CrawlJob.id == crawl_job_id).first()
        project = session.query(Project).filter(Project.id == project_id).first()
        if crawl_job:
            crawl_job.fail("Crawl timed out after 10 minutes - site may be protected or too large")
        if project:
            project.status = "failed"
        session.commit()
        
        return {"error": "Crawl timed out", "status": "failed"}

    except Exception as e:
        session.rollback()
        crawl_job = session.query(CrawlJob).filter(CrawlJob.id == crawl_job_id).first()
        if crawl_job:
            crawl_job.fail(str(e))
            session.commit()

        raise self.retry(exc=e, countdown=60)

    finally:
        session.close()


@celery_app.task(bind=True, soft_time_limit=600, time_limit=660)
def targeted_recrawl(self, project_id: str, changed_urls: list[str]) -> dict:
    """Re-crawl only changed pages with selective regeneration.

    This task:
    1. Fetches changed pages and extracts new outbound links
    2. Discovers and crawls any new pages
    3. Categorizes new pages (potentially creating new sections)
    4. Regenerates prose for affected sections
    5. Regenerates overview if >50% of pages changed or new section created
    6. Assembles llms.txt from stored curated data
    """
    from app.services.crawler_factory import get_crawler_service
    from app.services.llm_curator import LLMCurator, CuratedPageData, SectionData

    session = SyncSessionLocal()
    try:
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"error": "Project not found"}

        # Create crawl job
        crawl_job = CrawlJob(
            project_id=project_id,
            trigger_reason="scheduled",
        )
        crawl_job.start()
        session.add(crawl_job)
        session.commit()

        # Get existing curated pages and sections
        existing_curated = session.query(CuratedPage).filter(
            CuratedPage.project_id == project_id
        ).all()
        existing_by_url = {p.url: p for p in existing_curated}
        existing_urls = set(existing_by_url.keys())
        total_existing = len(existing_curated)

        existing_sections = session.query(CuratedSection).filter(
            CuratedSection.project_id == project_id
        ).all()
        sections_by_name = {s.name: s for s in existing_sections}
        existing_section_names = list(sections_by_name.keys())

        # Get site overview
        site_overview = session.query(SiteOverview).filter(
            SiteOverview.project_id == project_id
        ).first()

        if not site_overview:
            logger.warning("No site overview found, performing full recrawl")
            return initial_crawl(project_id, crawl_job.id)

        # Re-crawl changed pages and extract links
        crawler = get_crawler_service(settings)
        curator = LLMCurator(settings)
        
        actually_changed_pages = []
        discovered_new_urls = set()
        
        max_version = session.query(func.max(Page.version)).filter(
            Page.project_id == project_id
        ).scalar() or 1

        for url in changed_urls:
            page_data = crawler.crawl_page(url)
            if page_data:
                new_hash = page_data.get("content_hash", "")
                
                # Extract outbound links to discover new pages
                links = page_data.get("links", [])
                for link in links:
                    if link not in existing_urls and link not in discovered_new_urls:
                        discovered_new_urls.add(link)
                
                # Check if content actually changed
                existing = existing_by_url.get(url)
                if existing and existing.content_hash != new_hash:
                    actually_changed_pages.append(page_data)
                    
                    # Update raw page data
                    page = session.query(Page).filter(
                        Page.project_id == project_id,
                        Page.url == url,
                        Page.version == max_version,
                    ).first()
                    
                    if page:
                        page.title = page_data.get("title")
                        page.description = page_data.get("description")
                        page.h1 = page_data.get("h1")
                        page.h2s = page_data.get("h2s")
                        page.first_paragraph = page_data.get("first_paragraph")
                        page.content_hash = new_hash
                        page.crawled_at = datetime.now(timezone.utc)

        session.commit()
        
        changed_count = len(actually_changed_pages)
        logger.info(f"Actually changed pages: {changed_count}/{len(changed_urls)}")
        logger.info(f"Discovered new URLs: {len(discovered_new_urls)}")

        # Crawl newly discovered pages
        new_pages_data = []
        for url in discovered_new_urls:
            page_data = crawler.crawl_page(url)
            if page_data:
                new_pages_data.append(page_data)
                
                # Save raw page
                page = Page(
                    project_id=project_id,
                    url=page_data.get("url", ""),
                    title=page_data.get("title", ""),
                    description=page_data.get("description"),
                    h1=page_data.get("h1"),
                    h2s=page_data.get("h2s"),
                    first_paragraph=page_data.get("first_paragraph"),
                    content_hash=page_data.get("content_hash"),
                    depth=page_data.get("depth", 0),
                    version=max_version,
                )
                session.add(page)
        
        session.commit()
        logger.info(f"Crawled {len(new_pages_data)} new pages")

        new_section_created = False
        affected_sections = set()

        # Categorize new pages if any
        if new_pages_data:
            categorization = curator.categorize_new_pages(
                pages=new_pages_data,
                site_title=site_overview.site_title,
                site_tagline=site_overview.tagline,
                existing_sections=existing_section_names,
            )
            
            # Create new sections if needed
            for section_name in categorization.new_sections_needed:
                if section_name not in sections_by_name:
                    new_section = CuratedSection(
                        project_id=project_id,
                        name=section_name,
                        description="",  # Will be regenerated below
                        page_urls=[],
                        content_hash="",
                    )
                    session.add(new_section)
                    sections_by_name[section_name] = new_section
                    affected_sections.add(section_name)
                    new_section_created = True
                    logger.info(f"Created new section: {section_name}")
            
            # Add new pages to curated_pages
            for curated_page in categorization.pages:
                content_hash = next(
                    (p.get("content_hash", "") for p in new_pages_data if p.get("url") == curated_page.url),
                    ""
                )
                
                new_curated = CuratedPage(
                    project_id=project_id,
                    url=curated_page.url,
                    title=curated_page.title,
                    description=curated_page.description,
                    category=curated_page.category,
                    content_hash=content_hash,
                )
                session.add(new_curated)
                affected_sections.add(curated_page.category)
                
                # Update section's page_urls
                if curated_page.category in sections_by_name:
                    section = sections_by_name[curated_page.category]
                    if curated_page.url not in section.page_urls:
                        section.page_urls = section.page_urls + [curated_page.url]
            
            session.commit()

        # Identify affected sections from changed pages
        for page_data in actually_changed_pages:
            url = page_data.get("url")
            existing_page = existing_by_url.get(url)
            if existing_page:
                affected_sections.add(existing_page.category)

        if changed_count == 0 and not new_pages_data:
            # No actual changes, keep existing llms.txt
            crawl_job.complete(pages_crawled=len(changed_urls), pages_changed=0)
            session.commit()
            return {
                "status": "completed",
                "pages_checked": len(changed_urls),
                "pages_changed": 0,
                "new_pages": 0,
                "message": "No content changes detected",
            }

        # Regenerate descriptions for changed pages
        if actually_changed_pages:
            page_result = curator.curate_pages_only(
                pages=actually_changed_pages,
                site_title=site_overview.site_title,
                site_tagline=site_overview.tagline,
            )

            # Update curated pages
            for curated in page_result.pages:
                page_data = next((p for p in actually_changed_pages if p.get("url") == curated.url), None)
                content_hash = page_data.get("content_hash", "") if page_data else ""
                
                existing = existing_by_url.get(curated.url)
                if existing:
                    existing.title = curated.title
                    existing.description = curated.description
                    existing.category = curated.category
                    existing.content_hash = content_hash
                    existing.updated_at = datetime.now(timezone.utc)

        # Regenerate prose for affected sections
        for section_name in affected_sections:
            if section_name not in sections_by_name:
                continue
            
            section = sections_by_name[section_name]
            
            # Get all pages in this section
            section_pages = session.query(Page).filter(
                Page.project_id == project_id,
                Page.version == max_version,
                Page.url.in_(section.page_urls),
            ).all()
            
            if not section_pages:
                continue
            
            pages_for_prompt = [
                {
                    "url": p.url,
                    "title": p.title,
                    "first_paragraph": p.first_paragraph,
                    "h2_headings": p.h2s or [],
                }
                for p in section_pages
            ]
            
            site_context = f"{site_overview.site_title}: {site_overview.tagline}" if site_overview.tagline else site_overview.site_title
            regeneration = curator.regenerate_section(
                section_name=section_name,
                pages=pages_for_prompt,
                site_context=site_context,
            )
            
            section.description = regeneration.description
            section.content_hash = _compute_section_hash(
                [{"url": p.url, "content_hash": p.content_hash} for p in section_pages],
                section.page_urls,
            )
            section.updated_at = datetime.now(timezone.utc)
            
            logger.info(f"Regenerated section: {section_name}")

        session.commit()

        # Check if we should regenerate overview (>50% changed or new section)
        change_ratio = (changed_count + len(new_pages_data)) / total_existing if total_existing > 0 else 1.0
        regenerate_overview = change_ratio > 0.5 or new_section_created
        
        if regenerate_overview:
            logger.info(f"Regenerating overview (change_ratio={change_ratio:.0%}, new_section={new_section_created})")
            # Get all current pages for full curation
            all_pages = session.query(Page).filter(
                Page.project_id == project_id,
                Page.version == max_version,
            ).all()
            
            pages_data = [
                {
                    "url": p.url,
                    "title": p.title,
                    "first_paragraph": p.first_paragraph,
                    "h2_headings": p.h2s or [],
                }
                for p in all_pages
            ]
            
            full_result = curator.curate_full(pages=pages_data)
            site_overview.site_title = full_result.site_title
            site_overview.tagline = full_result.tagline
            site_overview.overview = full_result.overview
            site_overview.updated_at = datetime.now(timezone.utc)
            
            # Also update all sections from full result
            for section_data in full_result.sections:
                if section_data.name in sections_by_name:
                    sections_by_name[section_data.name].description = section_data.description
                else:
                    new_section = CuratedSection(
                        project_id=project_id,
                        name=section_data.name,
                        description=section_data.description,
                        page_urls=[p.url for p in section_data.pages],
                        content_hash="",
                    )
                    session.add(new_section)

        session.commit()

        # Assemble and save llms.txt from stored data
        _assemble_and_save_llms_txt(session, project_id, "scheduled")

        crawl_job.complete(pages_crawled=len(changed_urls) + len(new_pages_data), pages_changed=changed_count)
        session.commit()

        return {
            "status": "completed",
            "pages_checked": len(changed_urls),
            "pages_changed": changed_count,
            "new_pages": len(new_pages_data),
            "sections_affected": len(affected_sections),
            "new_section_created": new_section_created,
            "overview_regenerated": regenerate_overview,
        }

    except Exception as e:
        session.rollback()
        logger.error(f"Targeted recrawl failed: {e}")
        return {"error": str(e)}

    finally:
        session.close()


# =============================================================================
# Native Change Detection Tasks
# =============================================================================

# Backoff constants
MIN_CHECK_INTERVAL = 24   # hours (daily)
MAX_CHECK_INTERVAL = 168  # hours (weekly)


@celery_app.task
def check_projects_for_changes():
    """Periodic task: find and dispatch checks for all due projects.
    
    This task runs every hour via Celery Beat and finds projects
    that are due for a change check based on their next_check_at time.
    """
    from datetime import timedelta
    
    session = SyncSessionLocal()
    try:
        now = datetime.now(timezone.utc)
        
        # Find projects due for checking
        due_projects = session.query(Project).filter(
            Project.status == "ready",
            (Project.next_check_at <= now) | (Project.next_check_at.is_(None))
        ).all()
        
        logger.info(f"Found {len(due_projects)} projects due for change check")
        
        for project in due_projects:
            # Dispatch individual check task
            check_single_project.delay(str(project.id))
            
            # Immediately update next_check_at to prevent duplicate dispatches
            # The actual next check time will be recalculated after the check completes
            project.next_check_at = now + timedelta(hours=project.check_interval_hours)
        
        session.commit()
        
        return {"projects_dispatched": len(due_projects)}
        
    except Exception as e:
        session.rollback()
        logger.error(f"check_projects_for_changes failed: {e}")
        return {"error": str(e)}
        
    finally:
        session.close()


@celery_app.task(soft_time_limit=30, time_limit=60)
def check_single_project(project_id: str):
    """Scheduled task: trigger full recrawl for a project.
    
    This is the fallback scheduled check (default: every 24h).
    It always performs a full recrawl and compares the resulting llms.txt
    to apply adaptive backoff.
    
    Backoff is applied AFTER the recrawl completes (in initial_crawl).
    """
    from datetime import timedelta
    
    session = SyncSessionLocal()
    
    try:
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            logger.warning(f"Project {project_id} not found for scheduled check")
            return {"error": "Project not found"}
        
        if project.status != "ready":
            logger.info(f"Project {project_id} not ready (status={project.status}), skipping")
            return {"skipped": True, "reason": f"Status is {project.status}"}
        
        logger.info(f"Scheduled check for {project.url} - triggering full recrawl")
        
        # Store current llms.txt hash for comparison after recrawl
        current_llms_hash = None
        current_file = session.query(GeneratedFile).filter(
            GeneratedFile.project_id == project_id
        ).first()
        
        if current_file:
            import hashlib
            current_llms_hash = hashlib.sha256(
                current_file.content.encode('utf-8')
            ).hexdigest()
        
        # Create crawl job with scheduled trigger reason
        job = CrawlJob(
            project_id=project.id, 
            trigger_reason="scheduled_check",
        )
        session.add(job)
        session.flush()
        
        # Store the pre-recrawl hash in job metadata for comparison
        # We'll use a simple approach: store it in the session and check after
        project.status = "pending"
        project.homepage_content_hash = current_llms_hash  # Temporarily store for comparison
        session.commit()
        
        # Dispatch full recrawl
        initial_crawl.delay(str(project.id), str(job.id))
        
        return {
            "action": "full_recrawl_triggered",
            "trigger": "scheduled_check",
        }
        
    except Exception as e:
        session.rollback()
        logger.error(f"check_single_project failed for {project_id}: {e}")
        return {"error": str(e)}
        
    finally:
        session.close()


def _schedule_next_check(project: Project, changed: bool) -> None:
    """Calculate and set next check time with adaptive backoff.
    
    Args:
        project: The project to update
        changed: Whether significant changes were detected
    """
    from datetime import timedelta
    
    now = datetime.now(timezone.utc)
    
    if changed:
        # Reset to daily checks
        project.check_interval_hours = MIN_CHECK_INTERVAL
    else:
        # Double interval, cap at weekly
        new_interval = min(project.check_interval_hours * 2, MAX_CHECK_INTERVAL)
        project.check_interval_hours = new_interval
    
    project.next_check_at = now + timedelta(hours=project.check_interval_hours)
    
    logger.info(f"Scheduled next check for {project.url} in {project.check_interval_hours}h")


# =============================================================================
# Lightweight Change Detection Tasks
# =============================================================================

@celery_app.task
def dispatch_lightweight_checks():
    """Dispatch lightweight checks for projects that are due.
    
    Runs every minute via Celery Beat. Projects are staggered so that
    each project is checked once per LIGHTWEIGHT_CHECK_INTERVAL_MINUTES.
    
    Example: 10,000 projects with 5 min interval = ~2,000 dispatched per minute
    """
    from datetime import timedelta
    
    if not settings.lightweight_check_enabled:
        return {"skipped": True, "reason": "disabled"}
    
    session = SyncSessionLocal()
    try:
        now = datetime.now(timezone.utc)
        interval = timedelta(minutes=settings.lightweight_check_interval_minutes)
        
        # Find projects due for lightweight check
        due_projects = session.query(Project).filter(
            Project.status == "ready",
            (Project.next_lightweight_check_at <= now) | (Project.next_lightweight_check_at.is_(None))
        ).all()
        
        dispatched = 0
        for project in due_projects:
            # Dispatch the check
            lightweight_batch_check.delay(str(project.id))
            
            # Schedule next check (staggered)
            project.next_lightweight_check_at = now + interval
            dispatched += 1
        
        session.commit()
        
        if dispatched > 0:
            logger.info(f"Dispatched {dispatched} lightweight checks")
        return {"dispatched": dispatched, "interval_minutes": settings.lightweight_check_interval_minutes}
    
    except Exception as e:
        session.rollback()
        logger.error(f"dispatch_lightweight_checks failed: {e}")
        return {"error": str(e)}
    finally:
        session.close()


@celery_app.task(soft_time_limit=120, time_limit=150)
def lightweight_batch_check(project_id: str):
    """Check all pages for cumulative drift using async HEAD requests.
    
    Uses two-hash strategy:
    - etag: For optimizing HEAD requests (skip fetch if unchanged)
    - baseline_html_hash: For significance analysis (cumulative drift detection)
    """
    import asyncio
    import hashlib
    import httpx
    from app.services.change_analyzer import ChangeAnalyzer
    
    session = SyncSessionLocal()
    try:
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project or project.status != "ready":
            return {"skipped": True, "reason": "not_ready"}
        
        # Get max version for this project
        max_version = session.query(func.max(Page.version)).filter(
            Page.project_id == project_id
        ).scalar() or 0
        
        # Get all pages with their stored etags and baseline hashes
        pages = session.query(Page).filter(
            Page.project_id == project_id,
            Page.version == max_version,
        ).all()
        
        if not pages:
            return {"skipped": True, "reason": "no_pages"}
        
        logger.info(f"Lightweight check for {project.url}: {len(pages)} pages")
        
        # Async HEAD requests with rate limiting
        async def check_etags():
            connector = httpx.AsyncHTTPTransport(retries=1)
            async with httpx.AsyncClient(transport=connector, timeout=10.0, follow_redirects=True) as client:
                semaphore = asyncio.Semaphore(settings.lightweight_concurrent_requests)
                delay = settings.lightweight_request_delay_ms / 1000
                
                async def check_one(page):
                    async with semaphore:
                        if delay > 0:
                            await asyncio.sleep(delay)
                        try:
                            headers = {}
                            if page.etag:
                                headers["If-None-Match"] = page.etag
                            if page.last_modified_header:
                                headers["If-Modified-Since"] = page.last_modified_header
                            
                            resp = await client.head(page.url, headers=headers)
                            
                            # 304 = not modified
                            if resp.status_code == 304:
                                return {"url": page.url, "changed": False}
                            
                            # Check if ETag or Last-Modified changed
                            new_etag = resp.headers.get("ETag")
                            new_last_modified = resp.headers.get("Last-Modified")
                            new_content_length = resp.headers.get("Content-Length")
                            
                            # Parse content length to int for comparison
                            new_cl_int = int(new_content_length) if new_content_length else None
                            
                            # Only consider "changed" if we had prior values that differ
                            etag_changed = page.etag and new_etag and new_etag != page.etag
                            lm_changed = page.last_modified_header and new_last_modified and new_last_modified != page.last_modified_header
                            
                            # Option 1: Content-Length change detection
                            cl_changed = page.content_length and new_cl_int and page.content_length != new_cl_int
                            
                            # First check after crawl: no prior tracking headers
                            has_any_prior = page.etag or page.last_modified_header or page.content_length or page.sample_hash
                            is_first_check = not has_any_prior
                            
                            # Detect if this site has NO tracking headers (needs sample fetch)
                            has_no_headers = not new_etag and not new_last_modified and not new_content_length
                            needs_sample_check = has_no_headers and not is_first_check and page.sample_hash
                            
                            return {
                                "url": page.url,
                                "changed": etag_changed or lm_changed or cl_changed,
                                "is_first_check": is_first_check,
                                "needs_sample_check": needs_sample_check,
                                "has_no_headers": has_no_headers,
                                "new_etag": new_etag,
                                "new_last_modified": new_last_modified,
                                "new_content_length": new_cl_int,
                                "page_id": str(page.id),
                            }
                        except Exception as e:
                            logger.debug(f"HEAD failed for {page.url}: {e}")
                            return {"url": page.url, "changed": False, "error": str(e)}
                
                return await asyncio.gather(*[check_one(p) for p in pages])
        
        results = asyncio.run(check_etags())
        
        # Collect pages with changes vs first-time checks
        changed_results = [r for r in results if r.get("changed")]
        first_check_results = [r for r in results if r.get("is_first_check") and not r.get("error")]
        needs_sample_check = [r for r in results if r.get("needs_sample_check")]
        errors = [r for r in results if r.get("error")]
        
        # Build lookup for updating ETags
        pages_by_url = {p.url: p for p in pages}
        
        # For first-check pages, store all available headers and fetch sample hash if no headers
        if first_check_results:
            headerless_urls = [r["url"] for r in first_check_results if r.get("has_no_headers")]
            
            # Fetch semantic fingerprints for header-less pages (Option 2)
            # Uses semantic extraction to ignore noisy elements like deploy hashes
            sample_hashes = {}
            if headerless_urls:
                logger.info(f"Fetching semantic fingerprints for {len(headerless_urls)} header-less pages")
                from app.services.semantic_extractor import extract_semantic_fingerprint
                
                async def fetch_samples():
                    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                        sem = asyncio.Semaphore(settings.lightweight_concurrent_requests)
                        
                        async def fetch_one(url):
                            async with sem:
                                try:
                                    # Fetch full page for semantic extraction
                                    resp = await client.get(url)
                                    html = resp.text
                                    # Extract semantic fingerprint (ignores scripts, styles, deploy hashes)
                                    fingerprint = extract_semantic_fingerprint(html, max_content_length=10000)
                                    return url, fingerprint
                                except Exception as e:
                                    logger.debug(f"Semantic fetch failed for {url}: {e}")
                                    return url, None
                        
                        return await asyncio.gather(*[fetch_one(u) for u in headerless_urls])
                
                sample_results = asyncio.run(fetch_samples())
                sample_hashes = {url: h for url, h in sample_results if h}
            
            logger.info(f"First lightweight check for {len(first_check_results)} pages - storing tracking data")
            for result in first_check_results:
                page = pages_by_url.get(result["url"])
                if page:
                    if result.get("new_etag"):
                        page.etag = result["new_etag"]
                    if result.get("new_last_modified"):
                        page.last_modified_header = result["new_last_modified"]
                    if result.get("new_content_length"):
                        page.content_length = result["new_content_length"]
                    # Store sample hash for header-less pages
                    if result["url"] in sample_hashes:
                        page.sample_hash = sample_hashes[result["url"]]
            session.commit()
        
        # Option 2: Check semantic fingerprints for header-less sites (subsequent checks)
        if needs_sample_check and not changed_results:
            logger.info(f"Checking {len(needs_sample_check)} header-less pages via semantic fingerprint")
            from app.services.semantic_extractor import extract_semantic_fingerprint
            
            async def check_sample_hashes():
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    sem = asyncio.Semaphore(settings.lightweight_concurrent_requests)
                    
                    async def check_one(result):
                        async with sem:
                            try:
                                page = pages_by_url.get(result["url"])
                                if not page or not page.sample_hash:
                                    return {"url": result["url"], "changed": False}
                                
                                # Fetch full page for semantic extraction
                                resp = await client.get(result["url"])
                                html = resp.text
                                # Extract semantic fingerprint (ignores scripts, styles, deploy hashes)
                                new_hash = extract_semantic_fingerprint(html, max_content_length=10000)
                                
                                return {
                                    "url": result["url"],
                                    "changed": new_hash != page.sample_hash,
                                    "new_sample_hash": new_hash,
                                }
                            except Exception as e:
                                logger.debug(f"Semantic check failed for {result['url']}: {e}")
                                return {"url": result["url"], "changed": False, "error": str(e)}
                    
                    return await asyncio.gather(*[check_one(r) for r in needs_sample_check])
            
            sample_results = asyncio.run(check_sample_hashes())
            sample_changed = [r for r in sample_results if r.get("changed")]
            
            if sample_changed:
                logger.info(f"{len(sample_changed)} header-less pages changed via semantic fingerprint")
                changed_results.extend(sample_changed)
        
        if not changed_results:
            logger.info(f"No changes detected for {project.url} (first_checks: {len(first_check_results)}, sample_checks: {len(needs_sample_check)})")
            return {
                "changed": False,
                "pages_checked": len(pages),
                "first_checks": len(first_check_results),
                "sample_checks": len(needs_sample_check),
                "errors": len(errors),
            }
        
        logger.info(f"{len(changed_results)}/{len(pages)} pages changed for {project.url}")
        
        # Fast path: bulk change threshold
        change_ratio = len(changed_results) / len(pages)
        if change_ratio > settings.lightweight_change_threshold_percent / 100:
            logger.info(f"Bulk change ({change_ratio:.0%}) for {project.url}, triggering rescrape")
            trigger_result = _trigger_lightweight_rescrape(session, project)
            session.commit()
            if trigger_result.get("triggered"):
                return {"significant": True, "reason": "bulk_change", "rescrape_triggered": True}
            else:
                return {"significant": True, "reason": "bulk_change", "rescrape_skipped": True, "skip_reason": trigger_result.get("reason")}
        
        # Fetch HTML for changed pages and compare to baseline
        async def fetch_changed():
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                semaphore = asyncio.Semaphore(settings.lightweight_concurrent_requests)
                
                async def fetch_one(result):
                    async with semaphore:
                        try:
                            resp = await client.get(result["url"])
                            page = pages_by_url.get(result["url"])
                            baseline = page.first_paragraph if page else ""
                            return {
                                "url": result["url"],
                                "current_html": resp.text,
                                "baseline_html": baseline,
                                "new_etag": result.get("new_etag"),
                                "new_last_modified": result.get("new_last_modified"),
                            }
                        except Exception as e:
                            logger.debug(f"GET failed for {result['url']}: {e}")
                            return None
                
                fetched = await asyncio.gather(*[fetch_one(r) for r in changed_results])
                return [f for f in fetched if f]
        
        fetched_pages = asyncio.run(fetch_changed())
        
        if not fetched_pages:
            logger.info(f"Failed to fetch changed pages for {project.url}")
            return {"changed": True, "fetch_failed": True}
        
        # Analyze cumulative significance
        analyzer = ChangeAnalyzer(significance_threshold=settings.lightweight_significance_threshold)
        significance = analyzer.analyze_batch_significance(
            fetched_pages, 
            len(pages),
            settings.lightweight_change_threshold_percent,
        )
        
        if significance["significant"]:
            logger.info(f"Significant drift for {project.url} (score={significance['score']}, reason={significance['reason']})")
            trigger_result = _trigger_lightweight_rescrape(session, project)
            session.commit()
            if trigger_result.get("triggered"):
                return {
                    "significant": True,
                    "score": significance["score"],
                    "reason": significance["reason"],
                    "rescrape_triggered": True,
                }
            else:
                return {
                    "significant": True,
                    "score": significance["score"],
                    "reason": significance["reason"],
                    "rescrape_skipped": True,
                    "skip_reason": trigger_result.get("reason"),
                }
        else:
            # Update ETags only (keep baseline unchanged for cumulative detection)
            logger.debug(f"Non-significant changes for {project.url} (score={significance['score']}), updating ETags")
            for fp in fetched_pages:
                page = pages_by_url.get(fp["url"])
                if page:
                    if fp.get("new_etag"):
                        page.etag = fp["new_etag"]
                    if fp.get("new_last_modified"):
                        page.last_modified_header = fp["new_last_modified"]
            
            session.commit()
            return {
                "significant": False,
                "score": significance["score"],
                "pages_checked": len(pages),
                "pages_changed": len(changed_results),
            }
    
    except Exception as e:
        session.rollback()
        logger.error(f"lightweight_batch_check failed for {project_id}: {e}")
        return {"error": str(e)}
    finally:
        session.close()


def _trigger_lightweight_rescrape(session, project: Project) -> dict:
    """Trigger a full rescrape from lightweight change detection.
    
    Respects cooldown period to prevent over-triggering on frequently
    changing pages or false positives.
    
    Returns:
        dict with 'triggered' bool and 'reason' if skipped
    """
    # Check cooldown period
    cooldown_hours = settings.full_rescrape_cooldown_hours
    if project.last_lightweight_rescrape_at:
        cooldown = timedelta(hours=cooldown_hours)
        time_since_last = datetime.now(timezone.utc) - project.last_lightweight_rescrape_at
        if time_since_last < cooldown:
            remaining = cooldown - time_since_last
            logger.info(
                f"Skipping rescrape for {project.url} - within {cooldown_hours}h cooldown "
                f"({remaining.total_seconds() / 3600:.1f}h remaining)"
            )
            return {"triggered": False, "reason": "cooldown", "remaining_hours": remaining.total_seconds() / 3600}
    
    # Trigger the rescrape
    job = CrawlJob(project_id=project.id, trigger_reason="lightweight_change_detected")
    session.add(job)
    session.flush()  # Get job ID
    
    now = datetime.now(timezone.utc)
    project.status = "pending"  # Will be set to crawling by initial_crawl
    project.last_lightweight_rescrape_at = now
    
    # Reset the 24h scheduled rescrape timer since we're doing a rescrape now
    project.next_check_at = now + timedelta(hours=project.check_interval_hours or 24)
    
    logger.info(f"Triggering rescrape for {project.url} due to lightweight change detection (next scheduled check reset to {project.next_check_at})")
    
    # Dispatch async
    initial_crawl.delay(str(project.id), str(job.id))
    
    return {"triggered": True}
