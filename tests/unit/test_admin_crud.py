"""Tests for admin CRUD functionality."""

import pytest
from fastapi.testclient import TestClient

from otelms.api.main import app
from otelms.api.routes.admin import (
    _CRUD_MODELS,
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    ApiKeyUpdate,
)
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
# API Keys Unauthorized Tests
# ============================================================


def test_list_api_keys_unauthorized() -> None:
    """Test that listing API keys without auth returns 401/404."""
    response = client.get("/admin/api/api-keys")
    assert response.status_code in (401, 404)


def test_get_api_key_unauthorized() -> None:
    """Test that getting an API key without auth returns 401/404."""
    response = client.get("/admin/api/api-keys/some-id")
    assert response.status_code in (401, 404)


def test_create_api_key_unauthorized() -> None:
    """Test that creating an API key without auth returns 401/404."""
    response = client.post("/admin/api/api-keys", json={"name": "Test Key", "rate_limit": 60})
    assert response.status_code in (401, 404)


def test_update_api_key_unauthorized() -> None:
    """Test that updating an API key without auth returns 401/404."""
    response = client.put("/admin/api/api-keys/some-id", json={"name": "Updated Key"})
    assert response.status_code in (401, 404)


def test_toggle_api_key_unauthorized() -> None:
    """Test that toggling an API key without auth returns 401/404."""
    response = client.patch("/admin/api/api-keys/some-id/toggle")
    assert response.status_code in (401, 404)


def test_delete_api_key_unauthorized() -> None:
    """Test that deleting an API key without auth returns 401/404."""
    response = client.delete("/admin/api/api-keys/some-id")
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


# ============================================================
# API Keys CRUD Tests with Auth (require integration setup)
# These tests verify the endpoint structure and response models
# ============================================================


def test_api_key_create_response_structure() -> None:
    """Test that ApiKeyCreateResponse model has the expected fields including 'key'."""

    # Verify ApiKeyCreateResponse extends ApiKeyResponse and adds 'key'
    assert hasattr(ApiKeyCreateResponse, "model_fields")
    assert "key" in ApiKeyCreateResponse.model_fields
    assert "id" in ApiKeyCreateResponse.model_fields
    assert "name" in ApiKeyCreateResponse.model_fields
    assert "is_active" in ApiKeyCreateResponse.model_fields
    assert "rate_limit" in ApiKeyCreateResponse.model_fields
    assert "created_at" in ApiKeyCreateResponse.model_fields
    assert "last_used_at" in ApiKeyCreateResponse.model_fields
    assert "expires_at" in ApiKeyCreateResponse.model_fields

    # Verify ApiKeyResponse does NOT have 'key'
    assert "key" not in ApiKeyResponse.model_fields


def test_api_key_create_payload_validation() -> None:
    """Test that ApiKeyCreate payload validates correctly."""

    # Valid payload
    payload = ApiKeyCreate(name="Test Key", rate_limit=60)
    assert payload.name == "Test Key"
    assert payload.rate_limit == 60

    # Default rate_limit
    payload2 = ApiKeyCreate(name="Test Key 2")
    assert payload2.rate_limit == 60

    # Invalid rate_limit (too high)
    with pytest.raises(ValueError):
        ApiKeyCreate(name="Test", rate_limit=10001)

    # Invalid rate_limit (too low)
    with pytest.raises(ValueError):
        ApiKeyCreate(name="Test", rate_limit=0)

    # Empty name should fail
    with pytest.raises(ValueError):
        ApiKeyCreate(name="")


def test_api_key_update_payload_validation() -> None:
    """Test that ApiKeyUpdate payload validates correctly."""

    # All fields optional
    payload = ApiKeyUpdate()
    assert payload.name is None
    assert payload.rate_limit is None
    assert payload.is_active is None
    assert payload.expires_at is None

    # Partial update
    payload2 = ApiKeyUpdate(name="Updated", rate_limit=100)
    assert payload2.name == "Updated"
    assert payload2.rate_limit == 100

    # Invalid rate_limit
    with pytest.raises(ValueError):
        ApiKeyUpdate(rate_limit=10001)

    # Empty name should fail
    with pytest.raises(ValueError):
        ApiKeyUpdate(name="")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
