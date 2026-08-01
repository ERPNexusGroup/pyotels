"""
Contract tests for API endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock
from contextlib import asynccontextmanager

from otelms.api.main import app
from otelms.api.schemas import HotelResponse, ReservationListResponse, GuestResponse
from otelms.api.dependencies import get_db, verify_api_key
from otelms.domain.entities import ApiKey


async def mock_verify_api_key():
    return ApiKey(id="test_key", name="Test Key", key_hash="hash", is_active=True, rate_limit=60)


@asynccontextmanager
async def mock_get_db():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    # Mock the scalars() and all() methods for get_active()
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result
    yield mock_session


# Override dependencies for testing
app.dependency_overrides[verify_api_key] = mock_verify_api_key
app.dependency_overrides[get_db] = mock_get_db


client = TestClient(app)


class TestHealthEndpoints:
    """Contract tests for health endpoints."""

    def test_health_check(self):
        """Test GET /health returns healthy status."""
        # Simple test - just verify the endpoint responds
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "checks" in data
        # database check should be present (may be false in test env)
        assert "database" in data["checks"]

    def test_readiness_check(self):
        """Test GET /health/ready."""
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["ready"] is True

    def test_liveness_check(self):
        """Test GET /health/live."""
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["alive"] is True


class TestHotelEndpoints:
    """Contract tests for hotel endpoints."""

    def test_list_hotels_unauthorized(self):
        """Test GET /hotels without API key returns 401."""
        response = client.get("/hotels")
        assert response.status_code == 401

    def test_list_hotels_with_invalid_key(self):
        """Test GET /hotels with invalid API key returns 401."""
        response = client.get("/hotels", headers={"X-API-Key": "invalid"})
        assert response.status_code == 401


class TestReservationEndpoints:
    """Contract tests for reservation endpoints."""

    def test_list_reservations_requires_hotel_id(self):
        """Test GET /reservations requires hotel_id query param."""
        with patch("otelms.api.dependencies.verify_api_key", return_value=MagicMock()):
            response = client.get("/reservations")
            assert response.status_code == 422  # Missing required query param

    def test_get_reservation_requires_hotel_id(self):
        """Test GET /reservations/{id} requires hotel_id query param."""
        with patch("otelms.api.dependencies.verify_api_key", return_value=MagicMock()):
            response = client.get("/reservations/res_1")
            assert response.status_code == 422


class TestGuestEndpoints:
    """Contract tests for guest endpoints."""

    def test_list_guests_requires_hotel_id(self):
        """Test GET /guests requires hotel_id query param."""
        with patch("otelms.api.dependencies.verify_api_key", return_value=MagicMock()):
            response = client.get("/guests")
            assert response.status_code == 422


class TestCategoryEndpoints:
    """Contract tests for category endpoints."""

    def test_list_categories_requires_hotel_id(self):
        """Test GET /categories requires hotel_id query param."""
        with patch("otelms.api.dependencies.verify_api_key", return_value=MagicMock()):
            response = client.get("/categories")
            assert response.status_code == 422


class TestAPIResponseSchemas:
    """Test that API responses match expected schemas."""

    def test_health_response_schema(self):
        """Test HealthResponse schema validation."""
        from otelms.api.schemas import HealthResponse
        from datetime import datetime

        health = HealthResponse(
            status="healthy",
            checks={"database": True, "cache": True},
        )
        assert health.status == "healthy"
        assert health.checks["database"] is True
        assert isinstance(health.timestamp, datetime)

    def test_hotel_response_schema(self):
        """Test HotelResponse schema validation."""
        from otelms.api.schemas import HotelResponse
        from datetime import datetime

        hotel = HotelResponse(
            id="hotel_1",
            name="Test Hotel",
            domain="otelms.com",
            is_active=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert hotel.id == "hotel_1"
        assert hotel.name == "Test Hotel"

    def test_reservation_list_response_schema(self):
        """Test ReservationListResponse schema validation."""
        from otelms.api.schemas import ReservationListResponse, ReservationResponse
        from datetime import datetime
        from decimal import Decimal

        reservation = ReservationResponse(
            id="res_1",
            hotel_id="hotel_1",
            room_id="room_1",
            check_in=datetime.now(),
            check_out=datetime.now(),
            status=1,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            last_synced_at=datetime.now(),
        )

        resp = ReservationListResponse(
            items=[reservation],
            total=1,
            page=1,
            page_size=50,
            total_pages=1,
        )
        assert len(resp.items) == 1
        assert resp.total == 1

    def test_guest_response_schema(self):
        """Test GuestResponse schema validation."""
        from otelms.api.schemas import GuestResponse
        from datetime import datetime

        guest = GuestResponse(
            id="guest_1",
            first_name="John",
            last_name="Doe",
            full_name="John Doe",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert guest.full_name == "John Doe"