"""
HMAC-SHA256 signing and verification for ComplianceAuditEvent records.
Uses a secret key from settings (AUDIT_HMAC_KEY).
Signing makes audit records tamper-evident.
"""

import hashlib
import hmac as hmac_lib
import json
import logging
from typing import TYPE_CHECKING

from backend.app.core.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_CANONICAL_FIELDS = [
    "id",
    "timestamp",
    "action",
    "resource_type",
    "resource_id",
    "actor_id",
    "outcome",
]


class AuditSigningService:
    """Signs and verifies ComplianceAuditEvent records with HMAC-SHA256."""

    #: The ``hooks.AuditSigner`` protocol's name; "null" is the Community signer.
    name = "hmac-sha256"

    def __init__(self):
        key = getattr(settings, "AUDIT_HMAC_KEY", "dev-audit-key-change-in-production")
        self._key = key.encode() if isinstance(key, str) else key

    def _canonical_string(self, event) -> bytes:
        """Build a deterministic canonical byte string from the event's key fields."""
        parts = {f: str(getattr(event, f, "") or "") for f in _CANONICAL_FIELDS}
        return json.dumps(parts, sort_keys=True).encode()

    def sign(self, event) -> str:
        """
        Compute an HMAC-SHA256 signature for the event.

        Returns the hex digest (64 characters).
        The signature is computed over the canonical representation of the
        event's key fields, ensuring that any change to those fields
        invalidates the signature.
        """
        canonical = self._canonical_string(event)
        signature = hmac_lib.new(self._key, canonical, hashlib.sha256).hexdigest()
        return signature

    def verify(self, event) -> bool:
        """
        Verify the HMAC-SHA256 signature of the event.

        Returns True if the stored hmac_signature matches the recomputed
        signature, False otherwise (including if hmac_signature is None/empty).
        Uses constant-time comparison to prevent timing attacks.
        """
        if not event.hmac_signature:
            return False
        try:
            expected = self.sign(event)
            return hmac_lib.compare_digest(expected, event.hmac_signature)
        except Exception as exc:
            logger.warning("HMAC verification error: %s", exc)
            return False
