"""
HTTP Cache with ETag/If-None-Match support for scraping.
Reduces redundant requests by caching responses with ETags.
"""
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from playwright.async_api import Page, Response as PlaywrightResponse

from otelms.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CachedResponse:
    """Cached HTTP response with ETag support."""
    url: str
    status_code: int
    headers: Dict[str, str]
    body: bytes
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    cached_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    
    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def to_headers(self) -> Dict[str, str]:
        """Generate conditional request headers (If-None-Match, If-Modified-Since)."""
        headers = {}
        if self.etag:
            headers["If-None-Match"] = self.etag
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified
        return headers


class HTTPCache:
    """
    HTTP response cache with ETag/If-None-Match support.
    
    Features:
    - ETag-based conditional requests (304 Not Modified)
    - Last-Modified conditional requests
    - In-memory + diskcache backend
    - Configurable TTL
    - Automatic 304 handling
    """
    
    def __init__(
        self,
        cache_dir: str = "http_cache",
        default_ttl: int = 3600,
        max_size_mb: int = 100,
    ):
        self.cache_dir = cache_dir
        self.default_ttl = default_ttl
        self.max_size_mb = max_size_mb
        
        # In-memory cache for hot entries
        self._memory_cache: Dict[str, CachedResponse] = {}
        
        # Disk cache for persistence
        import diskcache
        self._disk_cache = diskcache.Cache(
            cache_dir,
            size_limit=max_size_mb * 1024 * 1024,
        )
        
        logger.info("HTTP cache initialized", cache_dir=cache_dir, default_ttl=default_ttl)
    
    def _make_key(self, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None) -> str:
        """Generate cache key from URL and relevant headers."""
        # Normalize URL (remove query params that shouldn't affect cache)
        parsed = urlparse(url)
        key_parts = [method, parsed.scheme, parsed.netloc, parsed.path]
        
        # Include relevant query params (sort for consistency)
        if parsed.query:
            key_parts.append(parsed.query)
        
        # Include relevant headers (Accept, Accept-Language, etc.)
        if headers:
            relevant_headers = {k: v for k, v in headers.items() 
                              if k.lower() in ['accept', 'accept-language', 'accept-encoding']}
            if relevant_headers:
                key_parts.append(json.dumps(relevant_headers, sort_keys=True))
        
        key_string = "|".join(key_parts)
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]
    
    def get(self, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None) -> Optional[CachedResponse]:
        """Get cached response if valid."""
        key = self._make_key(url, method, headers)
        
        # Check memory cache first
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if not entry.is_expired():
                logger.debug("Cache hit (memory)", url=url)
                return entry
            else:
                del self._memory_cache[key]
        
        # Check disk cache
        try:
            data = self._disk_cache.get(key)
            if data:
                entry = CachedResponse(**data)
                if not entry.is_expired():
                    # Promote to memory cache
                    self._memory_cache[key] = entry
                    logger.debug("Cache hit (disk)", url=url)
                    return entry
                else:
                    self._disk_cache.delete(key)
        except Exception as e:
            logger.warning("Disk cache read error", url=url, error=str(e))
        
        return None
    
    def set(self, url: str, response: httpx.Response, method: str = "GET", headers: Optional[Dict[str, str]] = None, ttl: Optional[int] = None) -> None:
        """Cache HTTP response."""
        key = self._make_key(url, method, headers)
        ttl = ttl or self.default_ttl
        
        # Extract ETag and Last-Modified
        etag = response.headers.get("ETag") or response.headers.get("etag")
        last_modified = response.headers.get("Last-Modified") or response.headers.get("last-modified")
        
        # Parse Cache-Control for TTL
        cache_control = response.headers.get("Cache-Control") or response.headers.get("cache-control")
        if cache_control:
            # Simple max-age parsing
            import re
            max_age_match = re.search(r"max-age=(\d+)", cache_control)
            if max_age_match:
                ttl = int(max_age_match.group(1))
        
        entry = CachedResponse(
            url=url,
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response.content,
            etag=etag,
            last_modified=last_modified,
            expires_at=time.time() + ttl if ttl > 0 else None,
        )
        
        # Store in memory cache
        self._memory_cache[key] = entry
        
        # Store in disk cache
        try:
            self._disk_cache.set(key, {
                "url": entry.url,
                "status_code": entry.status_code,
                "headers": entry.headers,
                "body": entry.body,
                "etag": entry.etag,
                "last_modified": entry.last_modified,
                "cached_at": entry.cached_at,
                "expires_at": entry.expires_at,
            }, expire=ttl)
        except Exception as e:
            logger.warning("Disk cache write error", url=url, error=str(e))
        
        logger.debug("Cached response", url=url, ttl=ttl, has_etag=bool(etag))
    
    def get_conditional_headers(self, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Get conditional request headers (If-None-Match, If-Modified-Since)."""
        entry = self.get(url, method, headers)
        if entry:
            return entry.to_headers()
        return {}
    
    async def fetch_with_cache(
        self,
        client: httpx.AsyncClient,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        ttl: Optional[int] = None,
    ) -> httpx.Response:
        """
        Fetch URL with automatic ETag caching.
        
        Returns cached response with 304 handling, or fresh response.
        """
        # Get conditional headers for 304 check
        conditional_headers = self.get_conditional_headers(url, method, headers)
        request_headers = {**(headers or {}), **conditional_headers}
        
        # Make request
        response = await client.request(method, url, headers=request_headers)
        
        # Handle 304 Not Modified
        if response.status_code == 304:
            logger.debug("Cache 304 - returning cached response", url=url)
            cached = self.get(url, method, headers)
            if cached:
                # Return cached response with 200 status
                return httpx.Response(
                    status_code=200,
                    content=cached.body,
                    headers=cached.headers,
                    request=response.request,
                )
        
        # Cache fresh response (if cacheable)
        if response.status_code == 200 and method in ("GET", "HEAD"):
            self.set(url, response, method, headers)
        
        return response
    
    async def fetch_with_cache_playwright(
        self,
        page: Page,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
    ) -> PlaywrightResponse:
        """
        Fetch with cache using Playwright (for JS-heavy pages).
        """
        # Note: Playwright doesn't easily support conditional requests
        # This is a simplified version - full implementation would need
        # to intercept requests via page.route
        response = await page.goto(url, wait_until="domcontentloaded")
        
        if response.status == 200:
            # Convert Playwright response to cacheable format
            body = await response.body()
            self.set(
                url,
                httpx.Response(
                    status_code=response.status,
                    content=body,
                    headers=dict(response.headers),
                )
            )
        
        return response
    
    def clear(self, pattern: Optional[str] = None) -> int:
        """Clear cache entries matching pattern."""
        count = 0
        if pattern:
            # Pattern matching on disk cache keys
            for key in list(self._disk_cache.iterkeys()):
                if pattern in key:
                    self._disk_cache.delete(key)
                    self._memory_cache.pop(key, None)
                    count += 1
        else:
            # Clear all
            count = len(self._disk_cache)
            self._disk_cache.clear()
            self._memory_cache.clear()
        
        logger.info("Cache cleared", entries=count)
        return count
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "memory_entries": len(self._memory_cache),
            "disk_entries": len(self._disk_cache),
            "cache_dir": self.cache_dir,
            "default_ttl": self.default_ttl,
        }
    
    def close(self) -> None:
        """Close cache and flush to disk."""
        self._disk_cache.close()


# Global HTTP cache instance
http_cache = HTTPCache()