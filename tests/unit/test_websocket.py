"""
Test for WebSocket sync progress.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from otelms.api.main import app
from otelms.domain.entities import ApiKey


async def mock_verify_api_key():
    return ApiKey(id="test_key", name="Test Key", key_hash="hash", is_active=True, rate_limit=60)


# Override dependencies for testing
app.dependency_overrides = {}
# We'll override in each test as needed


def test_websocket_endpoint_exists():
    """Test that WebSocket endpoint is registered."""
    # Override auth for this test
    from otelms.api.dependencies import verify_api_key
    app.dependency_overrides[verify_api_key] = mock_verify_api_key
    
    client = TestClient(app)
    with client.websocket_connect("/ws/sync-progress?hotel_id=test_hotel", headers={"X-API-Key": "test"}) as websocket:
        # Just verify connection works
        assert websocket is not None
    
    # Cleanup
    app.dependency_overrides.clear()


def test_websocket_sync_progress():
    """Test WebSocket sync progress messages."""
    from otelms.api.dependencies import verify_api_key
    app.dependency_overrides[verify_api_key] = mock_verify_api_key
    
    client = TestClient(app)
    with client.websocket_connect("/ws/sync-progress?hotel_id=test_hotel", headers={"X-API-Key": "test"}) as websocket:
        # Should receive welcome message
        data = websocket.receive_json()
        assert data["type"] == "connected"
        assert "message" in data
    
    # Cleanup
    app.dependency_overrides.clear()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])