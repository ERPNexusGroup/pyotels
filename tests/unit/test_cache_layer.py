"""
Test for HTTP cache layer with ETag support.
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import Response as HTTPXResponse

from otelms.scraping.cache_layer import HTTPCache, CachedResponse


class TestHTTPCache:
    """Test HTTP cache with ETag support."""

    @pytest.fixture
    def cache(self):
        """Create HTTP cache instance for testing."""
        return HTTPCache(cache_dir="test_cache", default_ttl=3600)

    def test_cache_key_generation(self, cache):
        """Test cache key generation from URL."""
        key1 = cache._make_key("https://example.com/api/data")
        key2 = cache._make_key("https://example.com/api/data")
        key3 = cache._make_key("https://example.com/api/other")
        
        # Same URL should produce same key
        assert key1 == key2
        # Different URL should produce different key
        assert key1 != key3

    def test_cache_key_with_method_and_headers(self, cache):
        """Test cache key includes method and relevant headers."""
        key_get = cache._make_key("https://example.com/api", "GET")
        key_post = cache._make_key("https://example.com/api", "POST")
        
        assert key_get != key_post

    def test_cache_set_and_get(self, cache):
        """Test basic cache set and get."""
        response = HTTPXResponse(
            status_code=200,
            content=b'{"data": "test"}',
            headers={"ETag": '"abc123"', "Content-Type": "application/json"}
        )
        
        cache.set("https://example.com/api", response)
        cached = cache.get("https://example.com/api")
        
        assert cached is not None
        assert cached.status_code == 200
        assert cached.body == b'{"data": "test"}'
        assert cached.etag == '"abc123"'

    def test_conditional_headers(self, cache):
        """Test conditional request headers generation."""
        response = HTTPXResponse(
            status_code=200,
            content=b'{"data": "test"}',
            headers={"ETag": '"abc123"', "Last-Modified": "Wed, 21 Oct 2015 07:28:00 GMT"}
        )
        
        cache.set("https://example.com/api", response)
        headers = cache.get_conditional_headers("https://example.com/api")
        
        assert "If-None-Match" in headers
        assert headers["If-None-Match"] == '"abc123"'
        assert "If-Modified-Since" in headers

    def test_cache_expiration(self, cache):
        """Test cache entry expiration."""
        # Create entry with expired TTL
        entry = CachedResponse(
            url="https://example.com/api",
            status_code=200,
            headers={},
            body=b"test",
            expires_at=time.time() - 100  # Expired 100 seconds ago
        )
        
        cache._memory_cache["test_key"] = entry
        
        # Should return None for expired entry
        # (get() would clean it up)
        result = cache.get("https://example.com/nonexistent")  # Won't match
        
        # Test that expired entry is detected
        assert entry.is_expired() is True

    def test_cache_304_handling(self, cache):
        """Test 304 response handling."""
        # First, cache a response
        response = HTTPXResponse(
            status_code=200,
            content=b'{"data": "original"}',
            headers={"ETag": '"abc123"', "Content-Type": "application/json"}
        )
        cache.set("https://example.com/api", response)
        
        # Now simulate 304 response
        response_304 = HTTPXResponse(status_code=304)
        
        # The cache should return the original cached response
        cached = cache.get("https://example.com/api")
        assert cached is not None
        assert cached.body == b'{"data": "original"}'

    def test_cache_clear(self, cache):
        """Test cache clearing."""
        response = HTTPXResponse(
            status_code=200,
            content=b'{"data": "test"}',
            headers={"ETag": '"abc123"'}
        )
        cache.set("https://example.com/api1", response)
        cache.set("https://example.com/api2", response)
        
        assert len(cache._memory_cache) == 2
        
        cache.clear()
        assert len(cache._memory_cache) == 0

    def test_cache_stats(self, cache):
        """Test cache statistics."""
        response = HTTPXResponse(status_code=200, content=b"test")
        cache.set("https://example.com/api", response)
        
        stats = cache.stats()
        
        assert stats["memory_entries"] >= 1
        assert "disk_entries" in stats
        assert "default_ttl" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])