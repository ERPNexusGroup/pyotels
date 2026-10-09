"""
E2E tests for API authentication and authorization.
"""
import pytest
from httpx import AsyncClient


class TestAPIAuthentication:
    """E2E tests for API key authentication."""

    @pytest.mark.asyncio
    async def test_protected_endpoint_requires_auth(self, async_client: AsyncClient):
        """Test that protected endpoints return 422 without API key (FastAPI validates required header)."""
        response = await async_client.get("/hotels")
        assert response.status_code == 422  # FastAPI validates required header before dependency

    @pytest.mark.asyncio
    async def test_protected_endpoint_accepts_valid_key(self, auth_client: AsyncClient):
        """Test that valid API key allows access."""
        response = await auth_client.get("/hotels")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limit_not_broken(self, auth_client: AsyncClient):
        """Test that rate limiting middleware doesn't break requests."""
        response = await auth_client.get("/hotels")
        assert response.status_code == 200