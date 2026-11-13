"""
E2E tests for health endpoints.
"""
import pytest
from httpx import AsyncClient


class TestHealthEndpoints:
    """E2E tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_full(self, async_client: AsyncClient):
        """Test /health returns full health status including alive and ready."""
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "degraded")
        assert "checks" in data
        assert "database" in data["checks"]
        assert "cache" in data["checks"]
        assert "alive" in data["checks"]
        assert data["checks"]["alive"] is True
        assert "ready" in data["checks"]
        assert "version" in data
        assert data["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, async_client: AsyncClient):
        """Test /metrics returns Prometheus format."""
        response = await async_client.get("/metrics")
        assert response.status_code == 200
        assert "otelms_http_requests_total" in response.text
        assert response.headers["content-type"].startswith("text/plain")

    @pytest.mark.asyncio
    async def test_root_endpoint(self, async_client: AsyncClient):
        """Test root endpoint returns API info."""
        response = await async_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "OtelMS API"
        assert data["version"] == "1.0.0"
        assert "description" in data
        assert "docs" in data

