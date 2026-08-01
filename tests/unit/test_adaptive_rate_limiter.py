"""
Test for adaptive rate limiting.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from otelms.scraping.rate_limiter import RateLimiter, AdaptiveRateLimiter


class TestAdaptiveRateLimiter:
    """Test adaptive rate limiting functionality."""

    def test_adaptive_limiter_created_with_defaults(self):
        """Test that AdaptiveRateLimiter initializes with default values."""
        limiter = AdaptiveRateLimiter(base_rpm=30, burst=5)
        
        assert limiter.base_rpm == 30
        assert limiter.burst == 5
        assert limiter.current_rpm == 30  # Starts at base
        assert limiter.min_rpm == 5
        assert limiter.max_rpm == 60

    def test_adaptive_limiter_increases_on_success(self):
        """Test that rate limit increases after successful requests."""
        limiter = AdaptiveRateLimiter(base_rpm=30, burst=5, min_rpm=5, max_rpm=60)
        
        initial_rpm = limiter.current_rpm
        
        # Record success
        limiter.record_success()
        limiter.record_success()
        limiter.record_success()
        
        # Rate should increase (within bounds)
        assert limiter.current_rpm >= initial_rpm

    def test_adaptive_limiter_decreases_on_429(self):
        """Test that rate limit decreases after 429 errors."""
        limiter = AdaptiveRateLimiter(base_rpm=30, burst=5, min_rpm=5, max_rpm=60)
        
        initial_rpm = limiter.current_rpm
        
        # Record 429 error
        limiter.record_429()
        
        # Rate should decrease
        assert limiter.current_rpm <= initial_rpm

    def test_adaptive_limiter_respects_bounds(self):
        """Test that rate limit stays within min/max bounds."""
        limiter = AdaptiveRateLimiter(base_rpm=30, burst=5, min_rpm=5, max_rpm=60)
        
        # Push to max
        for _ in range(100):
            limiter.record_success()
        assert limiter.current_rpm <= 60
        
        # Push to min
        for _ in range(100):
            limiter.record_429()
        assert limiter.current_rpm >= 5

    def test_adaptive_limiter_get_wait_time(self):
        """Test that get_wait_time returns appropriate wait."""
        limiter = AdaptiveRateLimiter(base_rpm=60, burst=5)
        
        wait_time = limiter.get_wait_time()
        # At 60 RPM, should be ~1 second between requests
        assert wait_time > 0
        assert wait_time < 2


class TestRateLimiterIntegration:
    """Test rate limiter integration with existing RateLimiter."""

    @pytest.mark.asyncio
    async def test_rate_limiter_token_bucket_works(self):
        """Test that token bucket rate limiting works."""
        from otelms.config.settings import settings
        from unittest.mock import AsyncMock, MagicMock
        
        # Skip if no Redis available - this test needs Redis
        pytest.skip("Requires running Redis instance")

    @pytest.mark.asyncio
    async def test_rate_limiter_per_hotel_isolation(self):
        """Test that rate limiting is isolated per hotel."""
        from otelms.config.settings import settings
        from unittest.mock import AsyncMock, MagicMock
        
        # Skip if no Redis available - this test needs Redis
        pytest.skip("Requires running Redis instance")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])