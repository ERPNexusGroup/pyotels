"""
Scraping module exports.
"""
from otelms.scraping.orchestrator import ScrapingOrchestrator, ScrapingResult
from otelms.scraping.browser import browser_pool, BrowserPool
from otelms.scraping.auth import OtelMSAuth, SessionManager
from otelms.scraping.rate_limiter import rate_limiter, RateLimiter
from otelms.scraping.retry import scraping_retry, login_retry, navigation_retry
from otelms.scraping.exceptions import (
    ScrapingError,
    AuthenticationError,
    NavigationError,
    ExtractionError,
    RateLimitError,
    BrowserError,
    SessionExpiredError,
    ElementNotFoundError,
    ParsingError,
)

__all__ = [
    "ScrapingOrchestrator",
    "ScrapingResult",
    "browser_pool",
    "BrowserPool",
    "OtelMSAuth",
    "SessionManager",
    "rate_limiter",
    "RateLimiter",
    "scraping_retry",
    "login_retry",
    "navigation_retry",
    "ScrapingError",
    "AuthenticationError",
    "NavigationError",
    "ExtractionError",
    "RateLimitError",
    "BrowserError",
    "SessionExpiredError",
    "ElementNotFoundError",
    "ParsingError",
]