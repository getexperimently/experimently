"""
PHI Encryption for EP-050: HIPAA Compliance.

Provides symmetric encryption for Protected Health Information (PHI)
using Fernet (AES-128-CBC with HMAC-SHA256) from the cryptography library.

Key lifecycle:
  - Generate a key once with PHIEncryption.generate_key()
  - Store the key securely (AWS Secrets Manager, environment variable)
  - Configure via settings.PHI_ENCRYPTION_KEY

Usage:
    enc = PHIEncryption()
    ciphertext = enc.encrypt("John Smith")
    plaintext  = enc.decrypt(ciphertext)
"""

from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class PHIEncryption:
    """
    Symmetric encryption wrapper for PHI values using Fernet.

    Fernet guarantees:
      - AES-128-CBC encryption with PKCS7 padding
      - HMAC-SHA256 authentication
      - IV randomisation on every encrypt() call (same plaintext → different ciphertext)
      - Timestamp in the token (can be used for key rotation in future)
    """

    def __init__(self, key: Optional[str] = None) -> None:
        """
        Initialise with an explicit key string or fall back to settings.

        Args:
            key: A URL-safe base64-encoded 32-byte Fernet key (44 characters).
                 If None, the key is read from settings.PHI_ENCRYPTION_KEY.

        Raises:
            RuntimeError: If no key is provided and settings.PHI_ENCRYPTION_KEY is not set,
                          or if the provided key is not a valid Fernet key.
        """
        resolved_key = key
        if resolved_key is None:
            try:
                from modules.backend.app.settings import settings

                resolved_key = settings.PHI_ENCRYPTION_KEY
            except Exception:
                resolved_key = None

        if not resolved_key:
            raise RuntimeError(
                "PHI_ENCRYPTION_KEY is not configured. "
                "Generate one with PHIEncryption.generate_key() and set it in your "
                "environment / AWS Secrets Manager before handling PHI data."
            )

        try:
            self._fernet = Fernet(
                resolved_key.encode() if isinstance(resolved_key, str) else resolved_key
            )
        except Exception as exc:
            raise RuntimeError(
                f"PHI_ENCRYPTION_KEY is not a valid Fernet key: {exc}. "
                "Generate a valid key with PHIEncryption.generate_key()."
            ) from exc

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext PHI string.

        Each call produces a distinct ciphertext because Fernet uses a
        random IV internally.

        Args:
            plaintext: The PHI value to encrypt (e.g. patient name, DOB).

        Returns:
            URL-safe base64-encoded Fernet token string.
        """
        token: bytes = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a Fernet token produced by encrypt().

        Args:
            ciphertext: A Fernet token string previously returned by encrypt().

        Returns:
            The original plaintext string.

        Raises:
            ValueError: If the ciphertext is invalid, tampered, or encrypted
                        with a different key.
        """
        try:
            token_bytes = (
                ciphertext.encode("utf-8")
                if isinstance(ciphertext, str)
                else ciphertext
            )
            plaintext_bytes: bytes = self._fernet.decrypt(token_bytes)
            return plaintext_bytes.decode("utf-8")
        except (InvalidToken, Exception) as exc:
            raise ValueError(
                "Failed to decrypt PHI ciphertext. "
                "The value may be corrupt, tampered, or encrypted with a different key."
            ) from exc

    # ------------------------------------------------------------------
    # Class-level helpers
    # ------------------------------------------------------------------

    @classmethod
    def generate_key(cls) -> str:
        """
        Generate a new cryptographically secure Fernet key.

        Returns:
            A URL-safe base64-encoded 32-byte key string (44 characters).
            Store this securely — losing it means losing access to all
            PHI data encrypted with it.

        Example:
            key = PHIEncryption.generate_key()
            # => e.g. "zxABCDEF1234567890abcdefghijklmnopqrstuvwxyz1234="
        """
        return Fernet.generate_key().decode("utf-8")
