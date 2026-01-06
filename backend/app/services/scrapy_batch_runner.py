#!/usr/bin/env python3
"""
Scrapy batch scrape runner script for subprocess execution.

This script runs the batch scrape spider to scrape a specific list of URLs
rather than crawling an entire website.
"""

import json
import logging
import sys
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scrapy.crawler import CrawlerProcess

from app.services.spiders.batch_scrape_spider import BatchScrapeSpider

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def main():
    """Run batch scrape spider and save results to JSON file."""
    if len(sys.argv) != 4:
        print("Usage: scrapy_batch_runner.py <urls_file> <start_url> <output_file>", file=sys.stderr)
        sys.exit(1)
    
    urls_file = sys.argv[1]
    start_url = sys.argv[2]
    output_file = sys.argv[3]
    
    # Load URLs to scrape
    with open(urls_file) as f:
        urls = json.load(f)
    
    logger.info(f"Starting batch scrape of {len(urls)} URLs")
    
    # Shared list to collect results from spider
    collected_pages: list[dict] = []
    
    # Configure Scrapy process
    process = CrawlerProcess(settings={
        'LOG_LEVEL': 'INFO',
        'REQUEST_FINGERPRINTER_IMPLEMENTATION': '2.7',
        'ROBOTSTXT_OBEY': True,
        'CONCURRENT_REQUESTS': 8,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 8,
        'DOWNLOAD_DELAY': 0.5,
        'AUTOTHROTTLE_ENABLED': True,
        'AUTOTHROTTLE_START_DELAY': 0.5,
        'AUTOTHROTTLE_MAX_DELAY': 10,
        # Playwright settings (only used when needed)
        'PLAYWRIGHT_LAUNCH_OPTIONS': {'headless': True},
        'DOWNLOAD_HANDLERS': {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        'TWISTED_REACTOR': "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    })
    
    # Add spider to process
    process.crawl(
        BatchScrapeSpider,
        urls=urls,
        start_url=start_url,
        collected_pages=collected_pages,
    )
    
    # Run the crawler (blocks until complete)
    process.start()
    
    # Save results to output file
    logger.info(f"Saving {len(collected_pages)} pages to {output_file}")
    with open(output_file, 'w') as f:
        json.dump(collected_pages, f)
    
    logger.info("Batch scrape complete")


if __name__ == '__main__':
    main()

