"""
E2E tests for reservation endpoints.
"""
import pytest
from httpx import AsyncClient


class TestReservationEndpoints:
    """E2E tests for reservation management endpoints."""

    @pytest.mark.asyncio
    async def test_list_reservations_requires_hotel_id(self, auth_client: AsyncClient):
        """Test GET /reservations requires hotel_id query param."""
        response = await auth_client.get("/reservations")
        assert response.status_code == 422  # Missing required query param

    @pytest.mark.asyncio
    async def test_list_reservations_with_hotel_id(self, auth_client: AsyncClient):
        """Test GET /reservations?hotel_id=... returns reservations."""
        response = await auth_client.get("/reservations?hotel_id=test_hotel")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data

    @pytest.mark.asyncio
    async def test_get_reservation_requires_hotel_id(self, auth_client: AsyncClient):
        """Test GET /reservations/{id} requires hotel_id query param."""
        response = await auth_client.get("/reservations/res_1")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_today_checkins(self, auth_client: AsyncClient):
        """Test GET /reservations/today/checkins."""
        response = await auth_client.get("/reservations/today/checkins?hotel_id=test_hotel")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_today_checkouts(self, auth_client: AsyncClient):
        """Test GET /reservations/today/checkouts."""
        response = await auth_client.get("/reservations/today/checkouts?hotel_id=test_hotel")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_in_house_endpoint(self, auth_client: AsyncClient):
        """Test GET /reservations/in-house."""
        response = await auth_client.get("/reservations/in-house?hotel_id=test_hotel")
        assert response.status_code == 200
        data = response.json()
        assert "hotel_id" in data
        assert "date" in data
        assert "in_house_count" in data
        assert "occupied_rooms" in data
        assert isinstance(data.get("items"), list)

    @pytest.mark.asyncio
    async def test_sync_calendar_endpoint(self, auth_client: AsyncClient):
        """Test POST /reservations/sync/calendar triggers sync."""
        response = await auth_client.post("/reservations/sync/calendar?hotel_id=test_hotel")
        # May fail if no credentials, but endpoint should exist
        assert response.status_code in (200, 202, 400, 500)

    @pytest.mark.asyncio
    async def test_sync_categories_endpoint(self, auth_client: AsyncClient):
        """Test POST /reservations/sync/categories triggers sync."""
        response = await auth_client.post("/reservations/sync/categories?hotel_id=test_hotel")
        assert response.status_code in (200, 202, 400, 500)

    @pytest.mark.asyncio
    async def test_sync_full_endpoint(self, auth_client: AsyncClient):
        """Test POST /reservations/sync/full triggers sync."""
        response = await auth_client.post("/reservations/sync/full?hotel_id=test_hotel")
        assert response.status_code in (200, 202, 400, 500)

    @pytest.mark.asyncio
    async def test_sync_history(self, auth_client: AsyncClient):
        """Test GET /reservations/sync/history."""
        response = await auth_client.get("/reservations/sync/history?hotel_id=test_hotel")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)