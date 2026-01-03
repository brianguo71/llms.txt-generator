"""Browser service for JavaScript-rendered page content using Playwright."""

import asyncio
import logging
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page

from app.config import Settings

logger = logging.getLogger(__name__)


class BrowserService:
    """Playwright-based browser for rendering JavaScript-heavy pages."""

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize browser service.
        
        Args:
            settings: Application settings. If None, uses default settings.
        """
        if settings is None:
            from app.config import get_settings
            settings = get_settings()
        self.ws_endpoint = settings.playwright_ws_url
        self._browser: Optional[Browser] = None

    async def render_page(self, url: str, timeout: int = 15000) -> str:
        """Render a page with JavaScript and return the final HTML.
        
        Args:
            url: The URL to render
            timeout: Maximum time to wait for page load (milliseconds), default 15s
        
        Returns:
            The rendered HTML content
            
        Raises:
            Exception: If browser connection or page rendering fails
        """
        logger.info(f"Rendering JS page with Playwright: {url}")
        
        async with async_playwright() as p:
            try:
                # Connect to the remote browser via WebSocket
                browser = await p.chromium.connect_over_cdp(self.ws_endpoint)
                page = await browser.new_page()
                
                try:
                    # Navigate and wait for DOM to be ready
                    # Using domcontentloaded instead of networkidle to avoid stalling
                    # on sites with analytics/trackers that keep connections open
                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=timeout,
                    )
                    
                    # Brief wait for any immediate JS rendering
                    await page.wait_for_timeout(1000)
                    
                    # Get the fully rendered HTML
                    content = await page.content()
                    logger.info(f"Successfully rendered {url} ({len(content)} bytes)")
                    return content
                    
                finally:
                    await page.close()
                    await browser.close()
                    
            except Exception as e:
                logger.error(f"Playwright rendering failed for {url}: {e}")
                raise

    def render_page_sync(self, url: str, timeout: int = 15000) -> str:
        """Synchronous wrapper for rendering pages.
        
        This is useful for Celery tasks which run in a synchronous context.
        
        Args:
            url: The URL to render
            timeout: Maximum time to wait for page load (milliseconds), default 15s
            
        Returns:
            The rendered HTML content
        """
        # Create a new event loop if we're not in an async context
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        
        if loop is not None:
            # We're in an async context, create a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    self.render_page(url, timeout)
                )
                return future.result()
        else:
            # No event loop, we can just run directly
            return asyncio.run(self.render_page(url, timeout))

