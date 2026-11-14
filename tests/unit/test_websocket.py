"""
Test for WebSocket sync progress.
"""
import pytest
from fastapi.testclient import TestClient

from otelms.api.main import app
from otelms.config.settings import settings


def test_websocket_endpoint_exists():
    """Test that WebSocket endpoint is registered."""
    prev = settings.api_key_required
    settings.api_key_required = False
    try:
        client = TestClient(app)
        with client.websocket_connect("/ws/sync-progress?hotel_id=test_hotel") as websocket:
            # Just verify connection works
            assert websocket is not None
    finally:
        settings.api_key_required = prev


def test_websocket_sync_progress():
    """Test WebSocket sync progress messages."""
    prev = settings.api_key_required
    settings.api_key_required = False
    try:
        client = TestClient(app)
        with client.websocket_connect("/ws/sync-progress?hotel_id=test_hotel") as websocket:
            # Should receive welcome message
            data = websocket.receive_json()
            assert data["type"] == "connected"
            assert "message" in data
    finally:
        settings.api_key_required = prev


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
