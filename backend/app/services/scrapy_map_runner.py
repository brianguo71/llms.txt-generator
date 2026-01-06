#!/usr/bin/env python3
"""
Scrapy URL discovery runner script for subprocess execution.

This script runs the URL discovery spider to find all URLs on a website
without extracting content. Much faster than a full crawl.
"""

import json
import logging
import sys
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scrapy.crawler import CrawlerProcess

from app.services.spiders.url_discovery_spider import UrlDiscoverySpider

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def main():
    """Run URL discovery spider and save results to JSON file."""
    if len(sys.argv) != 4:
        print("Usage: scrapy_map_runner.py <start_url> <max_urls> <output_file>", file=sys.stderr)
        sys.exit(1)
    
    start_url = sys.argv[1]
    max_urls = int(sys.argv[2])
    output_file = sys.argv[3]
    
    logger.info(f"Starting URL discovery: {start_url} (max {max_urls} URLs)")
    
    # Shared list to collect URLs from spider
    collected_urls: list[str] = []
    
    # Configure Scrapy process - lightweight settings for URL discovery
    process = CrawlerProcess(settings={
        'LOG_LEVEL': 'INFO',
        'REQUEST_FINGERPRINTER_IMPLEMENTATION': '2.7',
        'ROBOTSTXT_OBEY': True,
        'CONCURRENT_REQUESTS': 16,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 16,
        'DOWNLOAD_DELAY': 0.25,
        'AUTOTHROTTLE_ENABLED': True,
        'AUTOTHROTTLE_START_DELAY': 0.25,
        'AUTOTHROTTLE_MAX_DELAY': 5,
        # No Playwright needed for URL discovery
    })
    
    # Add spider to process
    process.crawl(
        UrlDiscoverySpider,
        start_url=start_url,
        max_urls=max_urls,
        collected_urls=collected_urls,
    )
    
    # Run the crawler (blocks until complete)
    process.start()
    
    # Save results to output file
    logger.info(f"Saving {len(collected_urls)} URLs to {output_file}")
    with open(output_file, 'w') as f:
        json.dump(collected_urls, f)
    
    logger.info("URL discovery complete")


if __name__ == '__main__':
    main()

