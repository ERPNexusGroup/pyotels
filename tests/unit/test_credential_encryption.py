"""
Test for credential encryption and rotation.
"""
import pytest
from otelms.utils.crypto import CredentialEncryption


def test_credential_encryption_encrypt_decrypt():
    """Test that encryption and decryption round-trip correctly."""
    encryption = CredentialEncryption()
    
    plaintext = "my_secret_password_123"
    encrypted = encryption.encrypt(plaintext)
    decrypted = encryption.decrypt(encrypted)
    
    assert encrypted != plaintext
    assert decrypted == plaintext


def test_credential_encryption_empty_string():
    """Test that empty strings are handled correctly."""
    encryption = CredentialEncryption()
    
    assert encryption.encrypt("") == ""
    assert encryption.decrypt("") == ""


def test_credential_encryption_different_values():
    """Test that different values produce different encrypted output."""
    encryption = CredentialEncryption()
    
    encrypted1 = encryption.encrypt("password1")
    encrypted2 = encryption.encrypt("password2")
    
    assert encrypted1 != encrypted2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])