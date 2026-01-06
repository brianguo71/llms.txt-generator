"""Web crawler service using Scrapy with conditional Playwright fallback."""

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from app.config import Settings

logger = logging.getLogger(__name__)


class ScrapyCrawler:
    """Crawl websites using Scrapy with automatic Playwright fallback for JS-heavy pages."""

    def __init__(
        self,
        settings: Settings,
        on_progress: Callable[[int, int, str], None] | None = None,
    ):
        """Initialize crawler with settings.
        
        Args:
            settings: Application settings
            on_progress: Optional callback for progress reporting (crawled, total, url)
        """
        self.max_pages = settings.max_pages_per_crawl
        self.max_map_urls = 500  # Max URLs to discover in map operation
        self.on_progress = on_progress

    def _report_progress(self, crawled: int, total: int, url: str) -> None:
        """Report crawl progress if callback is set."""
        if self.on_progress:
            self.on_progress(crawled, total, url)

    def crawl_website(self, start_url: str) -> list[dict[str, Any]]:
        """Crawl entire website using Scrapy in a subprocess.
        
        Running Scrapy in a subprocess avoids the ReactorNotRestartable issue
        that occurs when running multiple Scrapy crawls in the same process.
        
        Args:
            start_url: The URL to start crawling from
            
        Returns:
            List of page data dictionaries with markdown content
        """
        logger.info(f"Starting Scrapy crawl of {start_url} (max {self.max_pages} pages)")
        
        self._report_progress(0, self.max_pages, start_url)
        
        # Create temp file for results
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            output_file = f.name
        
        try:
            # Get the path to the runner script
            runner_script = Path(__file__).parent / "scrapy_runner.py"
            
            # Run Scrapy in a subprocess
            result = subprocess.run(
                [
                    sys.executable,
                    str(runner_script),
                    start_url,
                    str(self.max_pages),
                    output_file,
                ],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )
            
            # Log subprocess output (stderr contains Scrapy logs)
            if result.stderr:
                for line in result.stderr.strip().split('\n'):
                    if line.strip():
                        # Log Playwright triggers at INFO level for visibility
                        if 'PLAYWRIGHT' in line.upper():
                            logger.info(f"Scrapy: {line}")
                        else:
                            logger.debug(f"Scrapy: {line}")
            
            # Check for errors
            if result.returncode != 0:
                logger.error(f"Scrapy failed with code {result.returncode}: {result.stderr}")
                return []
            
            # Read results from temp file
            output_path = Path(output_file)
            if output_path.exists():
                with open(output_path) as f:
                    collected_pages = json.load(f)
            else:
                logger.error(f"Output file not found: {output_file}")
                return []
            
        except subprocess.TimeoutExpired:
            logger.error(f"Scrapy crawl timed out after 600 seconds for {start_url}")
            return []
        except Exception as e:
            logger.error(f"Scrapy crawl error: {e}")
            return []
        finally:
            # Clean up temp file
            try:
                Path(output_file).unlink(missing_ok=True)
            except Exception:
                pass
        
        # Report final progress
        for i, page in enumerate(collected_pages):
            self._report_progress(i + 1, len(collected_pages), page.get('url', ''))
        
        logger.info(f"Scrapy completed: {len(collected_pages)} pages crawled")
        return collected_pages

    def crawl_page(self, url: str) -> dict[str, Any] | None:
        """Scrape a single page using Scrapy.
        
        Used for targeted re-crawls when a specific page changes.
        
        Args:
            url: The URL to scrape
            
        Returns:
            Page data dictionary or None if failed
        """
        logger.info(f"Scraping single page with Scrapy: {url}")
        
        # Use max_pages=1 to get just this page
        original_max = self.max_pages
        self.max_pages = 1
        
        try:
            pages = self.crawl_website(url)
            if pages:
                return pages[0]
            return None
        finally:
            self.max_pages = original_max

    def map_website(self, url: str) -> list[str]:
        """Discover all URLs on a website using Scrapy URL discovery spider.
        
        This is faster than a full crawl since it only collects URLs
        without extracting content or markdown.
        
        Args:
            url: The website URL to map
            
        Returns:
            List of all discovered URLs on the site
        """
        logger.info(f"Mapping website URLs with Scrapy: {url} (max {self.max_map_urls} URLs)")
        
        # Create temp file for results
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            output_file = f.name
        
        try:
            # Get the path to the map runner script
            runner_script = Path(__file__).parent / "scrapy_map_runner.py"
            
            # Run URL discovery in a subprocess
            result = subprocess.run(
                [
                    sys.executable,
                    str(runner_script),
                    url,
                    str(self.max_map_urls),
                    output_file,
                ],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for URL discovery
            )
            
            # Log subprocess output
            if result.stderr:
                for line in result.stderr.strip().split('\n'):
                    if line.strip():
                        logger.debug(f"Scrapy Map: {line}")
            
            # Check for errors
            if result.returncode != 0:
                logger.error(f"Scrapy URL discovery failed with code {result.returncode}: {result.stderr}")
                return []
            
            # Read results from temp file
            output_path = Path(output_file)
            if output_path.exists():
                with open(output_path) as f:
                    discovered_urls = json.load(f)
            else:
                logger.error(f"Output file not found: {output_file}")
                return []
            
        except subprocess.TimeoutExpired:
            logger.error(f"Scrapy URL discovery timed out after 300 seconds for {url}")
            return []
        except Exception as e:
            logger.error(f"Scrapy URL discovery error: {e}")
            return []
        finally:
            # Clean up temp file
            try:
                Path(output_file).unlink(missing_ok=True)
            except Exception:
                pass
        
        logger.info(f"Scrapy URL discovery completed: {len(discovered_urls)} URLs found")
        return discovered_urls

    def batch_scrape(self, urls: list[str], start_url: str = "") -> list[dict[str, Any]]:
        """Scrape multiple specific pages using Scrapy batch spider.
        
        More efficient than individual scrapes when you need content
        from a specific set of URLs.
        
        Args:
            urls: List of URLs to scrape
            start_url: The site's root URL (for homepage detection)
            
        Returns:
            List of page data dictionaries with markdown content
        """
        if not urls:
            return []
        
        logger.info(f"Batch scraping {len(urls)} URLs with Scrapy")
        
        self._report_progress(0, len(urls), "Starting batch scrape...")
        
        # Create temp files for input URLs and output results
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            urls_file = f.name
            json.dump(urls, f)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            output_file = f.name
        
        try:
            # Get the path to the batch runner script
            runner_script = Path(__file__).parent / "scrapy_batch_runner.py"
            
            # Run batch scrape in a subprocess
            result = subprocess.run(
                [
                    sys.executable,
                    str(runner_script),
                    urls_file,
                    start_url or urls[0],
                    output_file,
                ],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout for batch scrape
            )
            
            # Log subprocess output
            if result.stderr:
                for line in result.stderr.strip().split('\n'):
                    if line.strip():
                        # Log Playwright triggers at INFO level
                        if 'PLAYWRIGHT' in line.upper():
                            logger.info(f"Scrapy Batch: {line}")
                        else:
                            logger.debug(f"Scrapy Batch: {line}")
            
            # Check for errors
            if result.returncode != 0:
                logger.error(f"Scrapy batch scrape failed with code {result.returncode}: {result.stderr}")
                return []
            
            # Read results from temp file
            output_path = Path(output_file)
            if output_path.exists():
                with open(output_path) as f:
                    collected_pages = json.load(f)
            else:
                logger.error(f"Output file not found: {output_file}")
                return []
            
        except subprocess.TimeoutExpired:
            logger.error(f"Scrapy batch scrape timed out after 600 seconds")
            return []
        except Exception as e:
            logger.error(f"Scrapy batch scrape error: {e}")
            return []
        finally:
            # Clean up temp files
            try:
                Path(urls_file).unlink(missing_ok=True)
                Path(output_file).unlink(missing_ok=True)
            except Exception:
                pass
        
        # Report final progress
        for i, page in enumerate(collected_pages):
            self._report_progress(i + 1, len(collected_pages), page.get('url', ''))
        
        logger.info(f"Scrapy batch scrape completed: {len(collected_pages)} pages scraped")
        return collected_pages
