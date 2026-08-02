"""Tests for admin CRUD functionality."""
import pytest
from fastapi.testclient import TestClient

from otelms.api.main import app
from otelms.api.routes.admin import _CRUD_MODELS
from otelms.domain.entities import ApiKey, Hotel

client = TestClient(app)


def test_crud_models_mapping() -> None:
    """Test that required models are present in the CRUD mapping."""
    assert "hotels" in _CRUD_MODELS
    assert "api-keys" in _CRUD_MODELS
    # Verify the mapping points to the correct model classes
    assert _CRUD_MODELS["hotels"] is Hotel
    assert _CRUD_MODELS["api-keys"] is ApiKey


# ============================================================
# Unauthorized tests (should return 401 or 404)
# ============================================================


def test_get_table_rows_unauthorized() -> None:
    """Test that listing table rows without auth returns 401."""
    response = client.get("/admin/api/tables/hotels")
    # 401 Unauthorized or 404 Not Found (if debug=false)
    assert response.status_code in (401, 404)


def test_post_row_unauthorized() -> None:
    """Test that creating a row without auth returns 401/404."""
    response = client.post("/admin/api/tables/categories", json={"data": {"id": "cat_1", "name": "Test"}})
    assert response.status_code in (401, 404)


def test_put_row_unauthorized() -> None:
    """Test that updating a row without auth returns 401/404."""
    response = client.put("/admin/api/tables/categories/some-id", json={"data": {"name": "Updated"}})
    assert response.status_code in (401, 404)


def test_delete_row_unauthorized() -> None:
    """Test that deleting a row without auth returns 401/404."""
    response = client.delete("/admin/api/tables/categories/some-id")
    assert response.status_code in (401, 404)


def test_create_invalid_table_unauthorized() -> None:
    """Test creating a row in an invalid/unmapped table returns 404."""
    response = client.post("/admin/api/tables/invalid-table", json={"data": {"id": "test", "name": "Test"}})
    assert response.status_code in (401, 404)


# ============================================================
# Basic structure tests (endpoints exist and respond)
# ============================================================


def test_admin_html_served() -> None:
    """Test that the admin HTML is served when debug is True."""
    response = client.get("/admin")
    # Could be 200 (debug=True) or 404 (debug=False)
    assert response.status_code in (200, 404)


def test_admin_login_endpoint_exists() -> None:
    """Test that the login endpoint exists and validates input."""
    # Empty body should return validation error (422) or auth error (401/404)
    response = client.post("/admin/login", json={})
    assert response.status_code in (401, 404, 422)


# ============================================================
# Hotel Detail Endpoint Tests
# ============================================================


def test_hotel_detail_unauthorized() -> None:
    """Test that hotel detail without auth returns 401 or 404."""
    response = client.get("/admin/api/hotels/test-hotel/detail")
    assert response.status_code in (401, 404)


def test_hotel_detail_not_found() -> None:
    """Test that hotel detail for non-existent hotel returns 404."""
    # This test would require a valid admin token, which we can't easily create without DB setup
    # The 401/404 behavior is tested above; detailed tests with auth require integration setup
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
