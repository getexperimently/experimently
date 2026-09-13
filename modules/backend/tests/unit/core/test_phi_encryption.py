"""
Unit tests for EP-050: PHI Encryption (modules/backend/app/core/phi_encryption.py).

Tests cover:
  - Key generation
  - Encrypt / decrypt round-trip
  - IV randomisation (same plaintext → different ciphertext)
  - Unicode and edge-case strings
  - Large payloads
  - Error handling (invalid key, invalid ciphertext)

Run with:
    source venv/bin/activate
    python -m pytest modules/backend/tests/unit/core/test_phi_encryption.py -v
"""

import pytest

from modules.backend.app.core.phi_encryption import PHIEncryption

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_key() -> str:
    """Generate a fresh valid Fernet key for testing."""
    return PHIEncryption.generate_key()


@pytest.fixture
def enc(valid_key: str) -> PHIEncryption:
    """PHIEncryption instance initialised with a freshly generated key."""
    return PHIEncryption(key=valid_key)


# ---------------------------------------------------------------------------
# Key generation tests
# ---------------------------------------------------------------------------


class TestGenerateKey:
    """Tests for PHIEncryption.generate_key()."""

    def test_generate_key_returns_string(self):
        """generate_key() returns a string."""
        key = PHIEncryption.generate_key()
        assert isinstance(key, str)

    def test_generate_key_length(self):
        """A Fernet key is 44 characters long (32 bytes base64url-encoded)."""
        key = PHIEncryption.generate_key()
        # Fernet keys are exactly 44 characters
        assert len(key) == 44

    def test_generate_key_base64_decodable(self):
        """The generated key must be valid base64url."""
        import base64

        key = PHIEncryption.generate_key()
        # Should not raise
        decoded = base64.urlsafe_b64decode(key)
        assert len(decoded) == 32

    def test_generate_key_is_unique(self):
        """Two calls to generate_key() return different keys."""
        key1 = PHIEncryption.generate_key()
        key2 = PHIEncryption.generate_key()
        assert key1 != key2

    def test_generate_key_produces_usable_key(self):
        """A key returned by generate_key() can be used to create PHIEncryption."""
        key = PHIEncryption.generate_key()
        enc = PHIEncryption(key=key)
        assert enc is not None

    def test_multiple_keys_are_different(self):
        """Generate 10 keys — they should all be unique."""
        keys = {PHIEncryption.generate_key() for _ in range(10)}
        assert len(keys) == 10


# ---------------------------------------------------------------------------
# Initialisation / key validation tests
# ---------------------------------------------------------------------------


class TestInitialisation:
    """Tests for PHIEncryption.__init__()."""

    def test_valid_key_creates_instance(self, valid_key):
        """A valid Fernet key creates a PHIEncryption instance successfully."""
        enc = PHIEncryption(key=valid_key)
        assert enc is not None

    def test_invalid_key_raises_runtime_error(self):
        """An invalid key raises RuntimeError with a descriptive message."""
        with pytest.raises(RuntimeError, match="not a valid Fernet key"):
            PHIEncryption(key="not-a-valid-fernet-key")

    def test_empty_key_raises_runtime_error(self):
        """An empty key raises RuntimeError."""
        with pytest.raises(RuntimeError):
            PHIEncryption(key="")

    def test_none_key_without_settings_raises_runtime_error(self, monkeypatch):
        """None key without settings.PHI_ENCRYPTION_KEY raises RuntimeError."""
        # Ensure settings.PHI_ENCRYPTION_KEY is None/empty
        monkeypatch.setattr(
            "modules.backend.app.core.phi_encryption.Fernet",
            lambda k: (_ for _ in ()).throw(Exception("should not be reached")),
        )
        # Override the settings import so PHI_ENCRYPTION_KEY is None
        # Patch at settings level
        import unittest.mock as mock

        import modules.backend.app.core.phi_encryption as phi_module

        with mock.patch("modules.backend.app.settings.load_modules_settings") as load:
            mock_settings = load.return_value
            mock_settings.PHI_ENCRYPTION_KEY = None
            with pytest.raises(
                RuntimeError, match="PHI_ENCRYPTION_KEY is not configured"
            ):
                PHIEncryption(key=None)

    def test_short_string_key_raises_runtime_error(self):
        """A string that is too short to be a valid Fernet key raises RuntimeError."""
        with pytest.raises(RuntimeError):
            PHIEncryption(key="tooshort")


# ---------------------------------------------------------------------------
# Encryption tests
# ---------------------------------------------------------------------------


class TestEncrypt:
    """Tests for PHIEncryption.encrypt()."""

    def test_encrypt_returns_string(self, enc):
        """encrypt() returns a string."""
        result = enc.encrypt("John Smith")
        assert isinstance(result, str)

    def test_encrypt_produces_non_empty_output(self, enc):
        """Encrypted output is non-empty."""
        result = enc.encrypt("some PHI value")
        assert len(result) > 0

    def test_encrypt_differs_from_plaintext(self, enc):
        """Ciphertext is not the same as plaintext."""
        plaintext = "Jane Doe DOB 1990-01-01"
        ciphertext = enc.encrypt(plaintext)
        assert ciphertext != plaintext

    def test_encrypt_same_value_twice_produces_different_ciphertext(self, enc):
        """Same plaintext encrypted twice yields different ciphertexts (IV randomisation)."""
        plaintext = "John Smith"
        ct1 = enc.encrypt(plaintext)
        ct2 = enc.encrypt(plaintext)
        assert ct1 != ct2, "Fernet should randomise the IV on each encrypt() call"

    def test_encrypt_empty_string(self, enc):
        """encrypt() works on an empty string."""
        result = enc.encrypt("")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_encrypt_unicode_string(self, enc):
        """encrypt() handles Unicode characters correctly."""
        plaintext = "Ünïcödé pàtïënt nàmé: 山田太郎"
        result = enc.encrypt(plaintext)
        assert isinstance(result, str)
        assert result != plaintext

    def test_encrypt_large_string(self, enc):
        """encrypt() handles a 10 KB string."""
        large_plaintext = "A" * 10_240
        result = enc.encrypt(large_plaintext)
        assert isinstance(result, str)
        assert len(result) > 10_240  # Ciphertext is larger than plaintext

    def test_encrypt_newlines_and_special_chars(self, enc):
        """encrypt() handles strings with newlines and special characters."""
        plaintext = "Name: John\nDOB: 1990-01-01\nDiagnosis: ICD-10 J45.20"
        result = enc.encrypt(plaintext)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Decryption tests
# ---------------------------------------------------------------------------


class TestDecrypt:
    """Tests for PHIEncryption.decrypt()."""

    def test_decrypt_restores_original_value(self, enc):
        """decrypt(encrypt(v)) == v."""
        plaintext = "John Smith"
        ciphertext = enc.encrypt(plaintext)
        assert enc.decrypt(ciphertext) == plaintext

    def test_decrypt_empty_string_round_trip(self, enc):
        """Empty string survives encrypt/decrypt round-trip."""
        plaintext = ""
        ciphertext = enc.encrypt(plaintext)
        assert enc.decrypt(ciphertext) == plaintext

    def test_decrypt_unicode_round_trip(self, enc):
        """Unicode string survives encrypt/decrypt round-trip."""
        plaintext = "Ünïcödé pàtïënt nàmé: 山田太郎"
        ciphertext = enc.encrypt(plaintext)
        assert enc.decrypt(ciphertext) == plaintext

    def test_decrypt_large_string_round_trip(self, enc):
        """10 KB string survives encrypt/decrypt round-trip."""
        plaintext = "B" * 10_240
        ciphertext = enc.encrypt(plaintext)
        assert enc.decrypt(ciphertext) == plaintext

    def test_decrypt_invalid_ciphertext_raises_value_error(self, enc):
        """decrypt() raises ValueError on an invalid ciphertext."""
        with pytest.raises(ValueError, match="Failed to decrypt PHI ciphertext"):
            enc.decrypt("this-is-not-valid-fernet-token")

    def test_decrypt_wrong_key_raises_value_error(self, valid_key):
        """decrypt() raises ValueError when a different key is used."""
        enc1 = PHIEncryption(key=valid_key)
        enc2 = PHIEncryption(key=PHIEncryption.generate_key())

        ciphertext = enc1.encrypt("secret data")
        with pytest.raises(ValueError):
            enc2.decrypt(ciphertext)

    def test_decrypt_tampered_ciphertext_raises_value_error(self, enc):
        """decrypt() raises ValueError when the ciphertext is tampered."""
        ciphertext = enc.encrypt("important PHI")
        # Tamper by flipping a character
        tampered = ciphertext[:-1] + ("A" if ciphertext[-1] != "A" else "B")
        with pytest.raises(ValueError):
            enc.decrypt(tampered)

    def test_decrypt_empty_string_ciphertext_raises_value_error(self, enc):
        """decrypt() raises ValueError on an empty ciphertext."""
        with pytest.raises(ValueError):
            enc.decrypt("")

    def test_multiple_values_round_trip(self, enc):
        """Multiple different PHI values all round-trip correctly."""
        phi_values = [
            "Alice Johnson",
            "DOB: 1985-06-15",
            "Diagnosis: Hypertension",
            "Insurance: Blue Cross #12345",
            "SSN: 123-45-6789",
        ]
        for value in phi_values:
            ciphertext = enc.encrypt(value)
            assert enc.decrypt(ciphertext) == value

    def test_same_plaintext_different_ciphertext_both_decrypt(self, enc):
        """Two different ciphertexts of the same plaintext both decrypt correctly."""
        plaintext = "consistent PHI"
        ct1 = enc.encrypt(plaintext)
        ct2 = enc.encrypt(plaintext)
        assert ct1 != ct2
        assert enc.decrypt(ct1) == plaintext
        assert enc.decrypt(ct2) == plaintext
