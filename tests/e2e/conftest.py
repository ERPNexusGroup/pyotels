"""
E2E test configuration - uses real HTTP client against local API.
Requires running API server (docker compose up or local).
"""
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from otelms.api.main import app


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for E2E tests - can be overridden via E2E_BASE_URL env var."""
    return os.getenv("E2E_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def api_key() -> str:
    """API key for authenticated requests."""
    return os.getenv("E2E_API_KEY", "changeme-secure-api-key-here")


@pytest_asyncio.fixture(scope="function")
async def async_client(base_url: str) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for API testing."""
    if base_url == "http://localhost:8000":
        # Use ASGI transport for local testing without running server
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=base_url) as client:
            yield client
    else:
        # Test against running server
        async with AsyncClient(base_url=base_url) as client:
            yield client


@pytest_asyncio.fixture(scope="function")
async def auth_client(async_client: AsyncClient, api_key: str) -> AsyncClient:
    """Pre-configured client with API key header."""
    from otelms.config.settings import settings as _settings
    prev = {
        "read": _settings.api_enable_read_public,
        "internal": _settings.api_enable_internal_sync,
        "write": _settings.api_enable_write_actions,
        "admin": _settings.api_enable_admin_routes,
        "legacy": _settings.api_enable_legacy_routes,
    }
    _settings.api_enable_read_public = True
    _settings.api_enable_internal_sync = True
    _settings.api_enable_write_actions = True
    _settings.api_enable_admin_routes = True
    _settings.api_enable_legacy_routes = True
    async_client.headers.update({"X-API-Key": api_key})
    try:
        yield async_client
    finally:
        _settings.api_enable_read_public = prev["read"]
        _settings.api_enable_internal_sync = prev["internal"]
        _settings.api_enable_write_actions = prev["write"]
        _settings.api_enable_admin_routes = prev["admin"]
        _settings.api_enable_legacy_routes = prev["legacy"]