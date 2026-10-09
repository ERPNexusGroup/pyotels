"""
E2E tests for hotel endpoints.
"""
import pytest
from httpx import AsyncClient


class TestHotelEndpoints:
    """E2E tests for hotel management endpoints."""

    @pytest.mark.asyncio
    async def test_list_hotels(self, auth_client: AsyncClient):
        """Test GET /hotels returns list of hotels."""
        response = await auth_client.get("/hotels")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_create_hotel(self, auth_client: AsyncClient):
        """Test POST /hotels creates a new hotel."""
        hotel_data = {
            "id": "test_hotel_e2e_new",
            "name": "E2E Test Hotel",
            "domain": "otelms.com",
            "username": "test@test.com",
            "password": "testpass",
            "is_active": True,
        }
        response = await auth_client.post("/hotels", json=hotel_data)
        # May fail if hotel exists - both 201 (created) and 409 (conflict) are acceptable
        assert response.status_code in (201, 409)

    @pytest.mark.asyncio
    async def test_get_hotel_not_found(self, auth_client: AsyncClient):
        """Test GET /hotels/{id} returns 404 for non-existent hotel."""
        response = await auth_client.get("/hotels/nonexistent_hotel")
        assert response.status_code == 404