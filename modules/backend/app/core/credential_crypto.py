"""Encrypt stored credentials with operator-provided keys.

The keys come from ``WAREHOUSE_CREDENTIALS_KEYS``
(``modules.backend.app.settings``): a comma-separated list of Fernet keys,
newest first.  They are used through :class:`cryptography.fernet.MultiFernet`,
so the first key encrypts and every key decrypts.  Rotating a key is:

1. put the new key in front (``NEW,OLD``) and deploy;
2. call :func:`rotate` on every stored token, which re-encrypts it under
   ``NEW`` (a token already under ``NEW`` is re-encrypted too, harmlessly);
3. remove ``OLD`` (``NEW``) and deploy.  A token still under ``OLD`` then
   raises :class:`CredentialUndecryptable`.

There is no fallback.  Without keys every call raises
:class:`CredentialKeysUnavailable`; a token no key opens raises
:class:`CredentialUndecryptable`.  Nothing here ever stores, returns or
accepts a plaintext or merely encoded credential in place of a token.  No
message raised here contains a key, a token or a plaintext.

The keys are read on every call, not cached, so the settings instance is the
one source of truth (``load_modules_settings(force=True)`` picks up a change).
"""

from __future__ import annotations

from typing import List, Optional, Union

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from backend.app.core.settings_rules import (
    CREDENTIAL_KEYS_SETTING,
    credential_keys_error,
    split_key_list,
)

Token = Union[bytes, str]


class CredentialCryptoError(Exception):
    """Base class: a stored credential cannot be encrypted or decrypted."""


class CredentialKeysUnavailable(CredentialCryptoError):
    """No usable ``WAREHOUSE_CREDENTIALS_KEYS``: unset, or not valid keys.

    A caller serving a request maps this to 503: the deployment is not
    configured for the feature, and nothing the client sends can change that.
    """


class CredentialUndecryptable(CredentialCryptoError):
    """A token that none of the configured keys can open.

    Either it was encrypted under a key that has since been removed, or it is
    not a token at all.
    """


_NOT_CONFIGURED = (
    f"{CREDENTIAL_KEYS_SETTING} is not set, so stored credentials cannot be "
    "encrypted or decrypted. Set it to one or more Fernet keys, comma-separated."
)

_UNDECRYPTABLE = (
    "The stored credential cannot be decrypted with any key in "
    f"{CREDENTIAL_KEYS_SETTING}. It was encrypted under a key that is no longer "
    "configured, or it is not an encrypted credential."
)


def _configured_keys() -> Optional[str]:
    from modules.backend.app.settings import settings

    return settings.WAREHOUSE_CREDENTIALS_KEYS


def _cipher(keys: Optional[str]) -> MultiFernet:
    """A MultiFernet over *keys* (the setting when ``None``), or the typed error."""
    raw = _configured_keys() if keys is None else keys
    entries: List[str] = split_key_list(raw)
    if not entries:
        raise CredentialKeysUnavailable(_NOT_CONFIGURED)
    error = credential_keys_error(raw)
    if error:
        # The rule's message names the position of the bad entry, never a key.
        raise CredentialKeysUnavailable(error)
    try:
        return MultiFernet([Fernet(entry.encode("ascii")) for entry in entries])
    except (ValueError, TypeError):  # pragma: no cover - the rule is stricter
        raise CredentialKeysUnavailable(
            f"{CREDENTIAL_KEYS_SETTING} does not hold valid Fernet keys."
        ) from None


def _token_bytes(token: Token) -> bytes:
    if isinstance(token, str):
        try:
            return token.encode("ascii")
        except UnicodeEncodeError:
            raise CredentialUndecryptable(_UNDECRYPTABLE) from None
    if isinstance(token, bytes):
        return token
    raise TypeError("a credential token is bytes or str")


def encrypt(plaintext: bytes, *, keys: Optional[str] = None) -> bytes:
    """Encrypt *plaintext* under the first configured key; returns a Fernet token.

    *keys* overrides the setting (a comma-separated key list), for callers and
    tests that hold the keys themselves.
    """
    if not isinstance(plaintext, bytes):
        raise TypeError("encrypt() takes bytes; encode the credential first")
    return _cipher(keys).encrypt(plaintext)


def decrypt(token: Token, *, keys: Optional[str] = None) -> bytes:
    """The plaintext of *token*, trying every configured key."""
    cipher = _cipher(keys)
    data = _token_bytes(token)
    try:
        return cipher.decrypt(data)
    except InvalidToken:
        raise CredentialUndecryptable(_UNDECRYPTABLE) from None


def rotate(token: Token, *, keys: Optional[str] = None) -> bytes:
    """*token* re-encrypted under the first configured key.

    Raises :class:`CredentialUndecryptable` when no configured key opens it.
    """
    cipher = _cipher(keys)
    data = _token_bytes(token)
    try:
        return cipher.rotate(data)
    except InvalidToken:
        raise CredentialUndecryptable(_UNDECRYPTABLE) from None


__all__ = [
    "CredentialCryptoError",
    "CredentialKeysUnavailable",
    "CredentialUndecryptable",
    "decrypt",
    "encrypt",
    "rotate",
]
