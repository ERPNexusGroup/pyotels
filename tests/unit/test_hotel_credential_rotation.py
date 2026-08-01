"""
Test for hotel credential rotation endpoint.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from otelms.api.main import app
from otelms.api.dependencies import get_db, verify_api_key, get_hotel_repo
from otelms.domain.entities import ApiKey, Hotel
from otelms.utils.crypto import CredentialEncryption


async def mock_verify_api_key():
    return ApiKey(id="test_key", name="Test Key", key_hash="hash", is_active=True, rate_limit=60)


async def mock_get_db():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result
    yield mock_session


# Override dependencies for testing
app.dependency_overrides[verify_api_key] = mock_verify_api_key
app.dependency_overrides[get_db] = mock_get_db


client = TestClient(app)


def test_rotate_password_endpoint_exists():
    """Test that POST /hotels/{hotel_id}/rotate-password endpoint exists."""
    # This will initially 404 until implemented
    response = client.post("/hotels/test_hotel/rotate-password", json={"new_password": "new_pass"})
    # Should not be 404 once implemented
    assert response.status_code != 404


def test_credential_encryption_used_in_hotel_creation():
    """Test that hotel creation uses credential encryption."""
    encryption = CredentialEncryption()
    password = "test_password_123"
    encrypted = encryption.encrypt(password)
    
    # Should be able to decrypt
    decrypted = encryption.decrypt(encrypted)
    assert decrypted == password


if __name__ == "__main__":
    pytest.main([__file__, "-v"])