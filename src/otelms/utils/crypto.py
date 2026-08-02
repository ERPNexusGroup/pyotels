"""
Credential encryption utilities using Fernet symmetric encryption.
"""
import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from otelms.config.settings import settings
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


class CredentialEncryption:
    """
    Handles encryption/decryption of sensitive credentials (passwords, API keys)
    using Fernet symmetric encryption with PBKDF2 key derivation.
    """

    def __init__(self):
        self._cipher: Fernet | None = None
        self._initialize_cipher()

    def _initialize_cipher(self) -> None:
        """Initialize Fernet cipher from environment or generate new key."""
        # Try to get encryption key from settings
        key = getattr(settings, 'credential_encryption_key', None)

        if key:
            # Use existing key
            if isinstance(key, str):
                key = key.encode()
            self._cipher = Fernet(key)
            logger.info("Credential encryption initialized with existing key")
        else:
            # Generate new key from master secret
            master_secret = getattr(settings, 'jwt_secret_key', None) or settings.secret_key
            if not master_secret:
                raise ValueError("No master secret available for credential encryption")

            # Derive key using PBKDF2
            salt = b'otelms_credential_salt'  # Fixed salt for deterministic key derivation
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(master_secret.encode()))
            self._cipher = Fernet(key)
            logger.info("Credential encryption initialized with derived key")

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.
        
        Args:
            plaintext: The string to encrypt
            
        Returns:
            Base64-encoded encrypted string
        """
        if not plaintext:
            return ""

        if not self._cipher:
            raise RuntimeError("Cipher not initialized")

        encrypted = self._cipher.encrypt(plaintext.encode())
        return encrypted.decode()

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt an encrypted string.
        
        Args:
            ciphertext: Base64-encoded encrypted string
            
        Returns:
            Decrypted plaintext string
        """
        if not ciphertext:
            return ""

        if not self._cipher:
            raise RuntimeError("Cipher not initialized")

        try:
            decrypted = self._cipher.decrypt(ciphertext.encode())
            return decrypted.decode()
        except Exception as e:
            logger.error("Failed to decrypt credential", error=str(e))
            raise ValueError("Failed to decrypt credential - invalid or corrupted data") from e


# Global instance
credential_encryption = CredentialEncryption()
