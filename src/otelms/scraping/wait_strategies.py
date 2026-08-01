"""
Wait strategies for JavaScript-heavy pages and SPA interactions.
Provides utilities to wait for AJAX completion, infinite scroll, and dynamic content.
"""
import asyncio
from typing import Optional, Callable, Any
from playwright.async_api import Page, Locator

from otelms.utils.logging import get_logger

logger = get_logger(__name__)


async def wait_for_ajax_complete(page: Page, timeout: int = 30000) -> bool:
    """
    Wait for all AJAX/fetch requests to complete.
    
    Uses a combination of approaches:
    1. jQuery.active (if jQuery present)
    2. fetch/XHR monitoring via page.evaluate
    3. Network idle state
    
    Args:
        page: Playwright page
        timeout: Maximum wait time in milliseconds
        
    Returns:
        True if AJAX completed, False if timeout
    """
    try:
        # Wait for network to be idle (no requests for 500ms)
        await page.wait_for_load_state("networkidle", timeout=timeout)
        
        # Additional check for jQuery if present
        jquery_active = await page.evaluate("""() => {
            return typeof jQuery !== 'undefined' ? jQuery.active : 0;
        }""")
        
        if jquery_active > 0:
            # Wait for jQuery to finish
            await page.wait_for_function(
                "() => typeof jQuery === 'undefined' || jQuery.active === 0",
                timeout=timeout
            )
        
        # Check for pending fetch/XHR
        pending_requests = await page.evaluate("""() => {
            return window._otelms_pending_requests || 0;
        }""")
        
        if pending_requests > 0:
            await page.wait_for_function(
                "() => (window._otelms_pending_requests || 0) === 0",
                timeout=timeout
            )
        
        logger.debug("AJAX completion wait finished")
        return True
        
    except Exception as e:
        logger.warning("AJAX wait timeout", error=str(e))
        return False


async def wait_for_infinite_scroll(
    page: Page,
    scroll_container: Optional[str] = None,
    max_scrolls: int = 50,
    wait_between: int = 500,
    timeout: int = 60000
) -> int:
    """
    Scroll to bottom of page/container to load all infinite scroll content.
    
    Args:
        page: Playwright page
        scroll_container: CSS selector for scrollable container (None = window)
        max_scrolls: Maximum scroll attempts
        wait_between: Wait time between scrolls in ms
        timeout: Total timeout in ms
        
    Returns:
        Number of scrolls performed
    """
    scrolls = 0
    start_time = asyncio.get_event_loop().time()
    
    try:
        previous_height = 0
        
        for _ in range(max_scrolls):
            # Check timeout
            if asyncio.get_event_loop().time() - start_time > timeout / 1000:
                break
            
            # Get current scroll height
            if scroll_container:
                current_height = await page.evaluate(
                    f"""() => document.querySelector('{scroll_container}').scrollHeight""")
                await page.evaluate(f"""() => document.querySelector('{scroll_container}').scrollTo(0, document.querySelector('{scroll_container}').scrollHeight)""")
            else:
                current_height = await page.evaluate("document.body.scrollHeight")
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            # Wait for new content to load
            await asyncio.sleep(wait_between / 1000)
            
            # Check if new content loaded
            if scroll_container:
                new_height = await page.evaluate(f"""() => document.querySelector('{scroll_container}').scrollHeight""")
            else:
                new_height = await page.evaluate("document.body.scrollHeight")
            
            scrolls += 1
            
            if new_height == previous_height:
                # No new content, we're at the bottom
                break
            
            previous_height = new_height
            
        logger.debug("Infinite scroll completed", scrolls=scrolls)
        return scrolls
        
    except Exception as e:
        logger.warning("Infinite scroll error", error=str(e), scrolls=scrolls)
        return scrolls


async def wait_for_element_stable(
    page: Page,
    selector: str,
    stable_duration: int = 500,
    timeout: int = 30000
) -> bool:
    """
    Wait for an element to stop changing (stabilize).
    Useful for dynamic content that renders progressively.
    
    Args:
        page: Playwright page
        selector: CSS selector for element
        stable_duration: Time in ms element must remain unchanged
        timeout: Maximum wait time
        
    Returns:
        True if element stabilized, False if timeout
    """
    try:
        element = page.locator(selector)
        
        # Get initial state
        previous_html = await element.inner_html()
        
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout / 1000:
            await asyncio.sleep(stable_duration / 1000)
            
            current_html = await element.inner_html()
            
            if current_html == previous_html:
                # Element hasn't changed for stable_duration
                logger.debug("Element stabilized", selector=selector)
                return True
            
            previous_html = current_html
        
        logger.warning("Element stabilization timeout", selector=selector)
        return False
        
    except Exception as e:
        logger.warning("Element stable wait error", selector=selector, error=str(e))
        return False


async def wait_for_text_in_element(
    page: Page,
    selector: str,
    expected_text: str,
    timeout: int = 30000
) -> bool:
    """
    Wait for specific text to appear in element.
    More reliable than waiting for selector when content loads dynamically.
    """
    try:
        await page.wait_for_function(
            f"""() => document.querySelector('{selector}')?.textContent?.includes('{expected_text}')""",
            timeout=timeout
        )
        return True
    except Exception:
        return False


async def wait_for_spa_navigation(
    page: Page,
    expected_url_pattern: str,
    timeout: int = 30000
) -> bool:
    """
    Wait for SPA navigation to complete (URL change without full reload).
    """
    try:
        await page.wait_for_url(expected_url_pattern, timeout=timeout)
        # Also wait for network idle after navigation
        await page.wait_for_load_state("networkidle", timeout=5000)
        return True
    except Exception:
        return False


async def setup_ajax_monitoring(page: Page) -> None:
    """
    Inject AJAX/fetch monitoring into page to track pending requests.
    Call this after page creation, before navigation.
    """
    await page.add_init_script("""
        // Track pending fetch requests
        window._otelms_pending_requests = 0;
        
        const originalFetch = window.fetch;
        window.fetch = function(...args) {
            window._otelms_pending_requests++;
            const promise = originalFetch.apply(this, args);
            promise.finally(() => {
                window._otelms_pending_requests--;
            });
            return promise;
        };
        
        // Track XHR requests
        const originalXHROpen = XMLHttpRequest.prototype.open;
        const originalXHRSend = XMLHttpRequest.prototype.send;
        
        XMLHttpRequest.prototype.open = function() {
            this._otelms_tracked = true;
            return originalXHROpen.apply(this, arguments);
        };
        
        XMLHttpRequest.prototype.send = function() {
            if (this._otelms_tracked) {
                window._otelms_pending_requests++;
                this.addEventListener('loadend', () => {
                    window._otelms_pending_requests--;
                });
            }
            return originalXHRSend.apply(this, arguments);
        };
    """)


# Convenience function for common scraping wait pattern
async def smart_wait(page: Page, timeout: int = 30000) -> None:
    """
    Smart wait combining multiple strategies:
    1. Network idle
    2. AJAX completion
    2. Brief stabilization wait
    """
    await page.wait_for_load_state("networkidle", timeout=timeout)
    await wait_for_ajax_complete(page, timeout=5000)
    await asyncio.sleep(0.5)  # Brief stabilization