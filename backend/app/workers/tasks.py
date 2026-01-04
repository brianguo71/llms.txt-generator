"""Celery task definitions.

These tasks are thin wrappers that call into the service layer.
The actual business logic lives in the services module.
"""

import hashlib
import logging
import time
from datetime import datetime, timezone

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
    from app.services.crawler import CrawlerService
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
        crawler = CrawlerService(settings, on_progress=on_crawl_progress)
        pages_data = crawler.crawl_website(project.url)
        crawl_elapsed = time.time() - crawl_start
        
        total_crawled = len(pages_data)
        logger.info(f"=== Crawl complete: {total_crawled} pages in {crawl_elapsed:.1f}s ===")
        log_progress(stage="CRAWL", current=total_crawled, total=total_crawled, elapsed=crawl_elapsed, extra="Complete")

        # Filter pages using batch LLM classification
        logger.info("=== Filtering pages with LLM ===")
        log_progress(stage="FILTER", current=0, total=1, elapsed=0, extra="Classifying page relevance...")
        
        filter_start = time.time()
        curator = LLMCurator(settings)
        relevant_pages = curator.filter_relevant_pages(pages_data, batch_size=25)
        filter_elapsed = time.time() - filter_start
        
        logger.info(f"=== Filtering complete: {len(relevant_pages)}/{total_crawled} pages relevant in {filter_elapsed:.1f}s ===")
        log_progress(stage="FILTER", current=1, total=1, elapsed=filter_elapsed, extra=f"Kept {len(relevant_pages)}/{total_crawled} pages")

        # Use LLM to curate relevant pages (full curation with section-based JSON response)
        logger.info("=== Curating pages with LLM ===")
        log_progress(stage="CURATE", current=0, total=1, elapsed=0, extra="Calling LLM to curate pages...")
        
        curate_start = time.time()
        curation_result = curator.curate_full(pages=relevant_pages)
        
        curate_elapsed = time.time() - curate_start
        total_pages = sum(len(s.pages) for s in curation_result.sections)
        logger.info(f"=== LLM curation complete in {curate_elapsed:.1f}s ===")
        log_progress(stage="CURATE", current=1, total=1, elapsed=curate_elapsed, extra=f"Curated {total_pages} pages in {len(curation_result.sections)} sections")

        # Save crawled pages for reference
        max_version = session.query(func.max(Page.version)).filter(
            Page.project_id == project_id
        ).scalar() or 0
        new_version = max_version + 1

        for page_data in pages_data:
            # Store markdown content in first_paragraph field for backwards compatibility
            markdown = page_data.get("markdown", "")
            first_para = markdown[:2000] if markdown else page_data.get("first_paragraph")
            
            page = Page(
                project_id=project.id,
                url=page_data.get("url", ""),
                title=page_data.get("title", ""),
                description=page_data.get("description"),
                first_paragraph=first_para,
                content_hash=page_data.get("content_hash"),
                depth=page_data.get("depth", 0),
                version=new_version,
            )
            session.add(page)

        # Save curated data (site overview + sections + pages)
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
        
        trigger_reason = crawl_job.trigger_reason if crawl_job else "initial"
        _assemble_and_save_llms_txt(session, project.id, trigger_reason)
        
        # Update project status
        project.status = "ready"
        project.last_checked_at = datetime.now(timezone.utc)
        
        total_elapsed = time.time() - start_time
        logger.info(f"=== COMPLETE ===")
        logger.info(f"  Pages crawled: {total_crawled}")
        logger.info(f"  Pages relevant: {len(relevant_pages)}")
        logger.info(f"  Pages curated: {total_pages}")
        logger.info(f"  Sections: {len(curation_result.sections)}")
        logger.info(f"  Crawl time: {crawl_elapsed:.1f}s")
        logger.info(f"  Filter time: {filter_elapsed:.1f}s")
        logger.info(f"  Curation time: {curate_elapsed:.1f}s")
        logger.info(f"  Total time: {total_elapsed:.1f}s")
        
        log_progress(stage="COMPLETE", current=total_crawled, total=total_crawled, elapsed=total_elapsed, extra="Done")
        
        crawl_job.complete(pages_crawled=total_crawled)
        session.commit()

        return {
            "status": "completed",
            "pages_crawled": total_crawled,
            "pages_curated": total_pages,
            "sections": len(curation_result.sections),
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
    from app.services.crawler import CrawlerService
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
        crawler = CrawlerService(settings)
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
            
            regeneration = curator.regenerate_section(
                section_name=section_name,
                pages=pages_for_prompt,
                site_title=site_overview.site_title,
                site_tagline=site_overview.tagline,
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
SIGNIFICANCE_THRESHOLD = 70  # Score threshold for triggering recrawl


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


@celery_app.task(soft_time_limit=180, time_limit=240)
def check_single_project(project_id: str):
    """Check a single project for changes and trigger recrawl if significant.
    
    Uses Firecrawl to scrape the homepage, compares content hash,
    and uses LLM to determine if changes are significant enough
    to warrant regenerating llms.txt.
    
    Implements adaptive backoff:
    - No change: double check interval (up to weekly)
    - Significant change: reset to daily checks
    """
    from datetime import timedelta
    from app.services.crawler import CrawlerService
    from app.services.llm_curator import LLMCurator
    
    session = SyncSessionLocal()
    
    try:
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            logger.warning(f"Project {project_id} not found for change check")
            return {"error": "Project not found"}
        
        if project.status != "ready":
            logger.info(f"Project {project_id} not ready (status={project.status}), skipping check")
            return {"skipped": True, "reason": f"Status is {project.status}"}
        
        logger.info(f"Checking {project.url} for changes (interval: {project.check_interval_hours}h)")
        
        # 1. Scrape homepage with Firecrawl (1 credit)
        crawler = CrawlerService(settings)
        page_data = crawler.crawl_page(project.url)
        
        if not page_data:
            logger.warning(f"Failed to scrape {project.url} for change check")
            # Keep current interval, try again later
            _schedule_next_check(project, changed=False)
            project.last_checked_at = datetime.now(timezone.utc)
            session.commit()
            return {"error": "Failed to scrape homepage"}
        
        new_hash = page_data.get("content_hash", "")
        old_hash = project.homepage_content_hash
        
        # 2. Compare hashes
        if new_hash == old_hash:
            logger.info(f"No change detected for {project.url}")
            _schedule_next_check(project, changed=False)
            project.last_checked_at = datetime.now(timezone.utc)
            session.commit()
            return {
                "changed": False,
                "next_check_hours": project.check_interval_hours,
            }
        
        logger.info(f"Content hash changed for {project.url}, analyzing significance...")
        
        # 3. Get old content for comparison
        old_content = _get_stored_homepage_content(session, project_id)
        new_content = page_data.get("markdown", "")
        
        # 4. Use LLM to score significance
        curator = LLMCurator(settings)
        significance = curator.analyze_change_significance(old_content, new_content)
        
        score = significance.get("score", 0)
        reason = significance.get("reason", "Unknown")
        
        logger.info(f"Change significance for {project.url}: score={score}, reason={reason}")
        
        if score >= SIGNIFICANCE_THRESHOLD:
            # Significant change - trigger full recrawl
            logger.info(f"Significant change detected for {project.url}, triggering recrawl")
            
            # Create new crawl job
            job = CrawlJob(project_id=project.id, trigger_reason="change_detected")
            session.add(job)
            session.flush()
            
            # Update project state
            project.homepage_content_hash = new_hash
            project.last_checked_at = datetime.now(timezone.utc)
            project.check_interval_hours = MIN_CHECK_INTERVAL  # Reset to daily
            _schedule_next_check(project, changed=True)
            session.commit()
            
            # Trigger full recrawl
            initial_crawl.delay(str(project.id), str(job.id))
            
            return {
                "changed": True,
                "significant": True,
                "score": score,
                "reason": reason,
                "action": "recrawl_triggered",
            }
        else:
            # Not significant - back off
            logger.info(f"Non-significant change for {project.url}, backing off")
            
            project.homepage_content_hash = new_hash
            project.last_checked_at = datetime.now(timezone.utc)
            _schedule_next_check(project, changed=False)
            session.commit()
            
            return {
                "changed": True,
                "significant": False,
                "score": score,
                "reason": reason,
                "next_check_hours": project.check_interval_hours,
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


def _get_stored_homepage_content(session, project_id: str) -> str:
    """Get the stored homepage content from the most recent crawl.
    
    Returns:
        Homepage markdown content, or empty string if not found
    """
    # Find the homepage page from the latest version
    max_version = session.query(func.max(Page.version)).filter(
        Page.project_id == project_id
    ).scalar() or 0
    
    project = session.query(Project).filter(Project.id == project_id).first()
    if not project:
        return ""
    
    # Find page matching the project URL
    homepage = session.query(Page).filter(
        Page.project_id == project_id,
        Page.version == max_version,
        Page.url == project.url,
    ).first()
    
    if homepage and homepage.first_paragraph:
        return homepage.first_paragraph
    
    return ""
