"""Tests for admin CRUD functionality."""

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from otelms.api.main import app
from otelms.api.routes.admin import (
    _CRUD_MODELS,
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    ApiKeyUpdate,
)
from otelms.api.routes.admin.auth import _get_db
from otelms.config.settings import settings
from otelms.domain.entities import ApiKey, Hotel
from otelms.utils.crypto import credential_encryption

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


# ============================================================
# Hotel credential update tests (PUT /admin/api/config/hotels/{id})
# ============================================================


def _make_admin_token() -> str:
    """Genera un JWT de sesión admin válido (mismo esquema que _create_session_token)."""
    now = datetime.now(UTC)
    return jose_jwt.encode(
        {
            "sub": "test_key",
            "name": "Test Key",
            "role": "admin",
            "iat": now,
            "exp": now + timedelta(hours=12),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


@pytest.fixture(autouse=True)
async def _cleanup_cred_test_hotels(test_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Limpia hoteles de prueba antes y después (test.db persiste entre runs)."""
    await test_session.execute(
        delete(Hotel).where(Hotel.id.in_(["cred-test-hotel", "cred-test-hotel2"]))
    )
    await test_session.commit()
    yield
    await test_session.execute(
        delete(Hotel).where(Hotel.id.in_(["cred-test-hotel", "cred-test-hotel2"]))
    )
    await test_session.commit()


async def test_hotel_update_credentials(test_session: AsyncSession) -> None:
    """PUT /admin/api/config/hotels/{id} actualiza username y re-cifra password."""
    # Override _get_db para que el client use la sesión de test
    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_session

    app.dependency_overrides[_get_db] = _override_db

    old_hash = hashlib.sha256(b"old-pass-123").hexdigest()
    old_encrypted = credential_encryption.encrypt("old-pass-123")
    hotel = Hotel(
        id="cred-test-hotel",
        name="Cred Test",
        domain="otelms.com",
        username="old_user",
        password_hash=old_hash,
        encrypted_password=old_encrypted,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    test_session.add(hotel)
    await test_session.commit()

    # PUT con credenciales nuevas
    response = client.put(
        "/admin/api/config/hotels/cred-test-hotel",
        json={"username": "new_user", "password": "new-pass-456"},
        headers={"Authorization": f"Bearer {_make_admin_token()}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["username"] == "new_user"
    # La respuesta NO debe exponer la password
    assert "password" not in body
    assert "password_hash" not in body
    assert "encrypted_password" not in body

    # Verificar en DB: hash y Fernet actualizados
    await test_session.refresh(hotel)
    assert hotel.username == "new_user"
    assert hotel.password_hash != old_hash
    assert hotel.encrypted_password != old_encrypted
    # La nueva password descifra correctamente
    decrypted = credential_encryption.decrypt(hotel.encrypted_password)
    assert decrypted == "new-pass-456"


async def test_hotel_update_username_only_keeps_password(test_session: AsyncSession) -> None:
    """PUT solo con username NO debe tocar la password (hash + Fernet intactos)."""
    # Override _get_db para que el client use la sesión de test
    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_session

    app.dependency_overrides[_get_db] = _override_db

    old_hash = hashlib.sha256(b"keep-pass-789").hexdigest()
    old_encrypted = credential_encryption.encrypt("keep-pass-789")
    hotel = Hotel(
        id="cred-test-hotel2",
        name="Cred Test 2",
        domain="otelms.com",
        username="keep_user",
        password_hash=old_hash,
        encrypted_password=old_encrypted,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    test_session.add(hotel)
    await test_session.commit()

    response = client.put(
        "/admin/api/config/hotels/cred-test-hotel2",
        json={"username": "renamed_user"},
        headers={"Authorization": f"Bearer {_make_admin_token()}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["username"] == "renamed_user"

    await test_session.refresh(hotel)
    assert hotel.username == "renamed_user"
    # Password intacta
    assert hotel.password_hash == old_hash
    assert hotel.encrypted_password == old_encrypted
    assert credential_encryption.decrypt(hotel.encrypted_password) == "keep-pass-789"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
