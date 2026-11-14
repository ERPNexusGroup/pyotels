"""
Scraping module exports.
"""
from __future__ import annotations

from typing import Any

from otelms.scraping.auth import OtelMSAuth, SessionManager
from otelms.scraping.exceptions import (
    AuthenticationError,
    BrowserError,
    ElementNotFoundError,
    ExtractionError,
    NavigationError,
    ParsingError,
    RateLimitError,
    ScrapingError,
    SessionExpiredError,
)
from otelms.scraping.rate_limiter import RateLimiter, rate_limiter
from otelms.scraping.retry import login_retry, navigation_retry, scraping_retry

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


def __getattr__(name: str) -> Any:
    if name in {"BrowserPool", "browser_pool"}:
        from otelms.scraping.browser import BrowserPool, browser_pool

        return {"BrowserPool": BrowserPool, "browser_pool": browser_pool}[name]
    if name in {"ScrapingOrchestrator", "ScrapingResult"}:
        from otelms.scraping.orchestrator import ScrapingOrchestrator, ScrapingResult

        return {"ScrapingOrchestrator": ScrapingOrchestrator, "ScrapingResult": ScrapingResult}[name]
    raise AttributeError(name)
