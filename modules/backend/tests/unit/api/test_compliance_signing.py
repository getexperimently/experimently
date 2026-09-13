"""
The compliance module: ``AuditLogService.log()`` signs events (HMAC-SHA256, EP-033).

Split out of ``test_compliance_api.py``, which now tests only what a core
build does.  These assertions hold because the modules' registration
installs ``AuditSigningService`` through ``hooks.audit_signer``; under the
core ``NullAuditSigner`` the signature is ``None`` by design.
"""

from unittest.mock import MagicMock


class TestAuditEventSignature:
    def test_audit_event_has_hmac_signature(self):
        """AuditLogService.log() produces events with a non-empty hmac_signature."""
        from backend.app.models.compliance_audit_event import AuditAction, AuditOutcome
        from backend.app.services.audit_log_service import AuditLogService

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        service = AuditLogService(db)

        event = service.log(
            action=AuditAction.CREATE,
            resource_type="feature_flag",
            outcome=AuditOutcome.SUCCESS,
            new_value={"key": "my-flag"},
        )
        assert event.hmac_signature is not None
        assert len(event.hmac_signature) == 64

    def test_audit_event_hmac_is_64_hex_chars(self):
        """HMAC signature is exactly 64 hex characters (SHA-256)."""
        from backend.app.models.compliance_audit_event import AuditAction, AuditOutcome
        from backend.app.services.audit_log_service import AuditLogService

        db = MagicMock()
        db.add = MagicMock()
        db.flush = MagicMock()
        service = AuditLogService(db)

        event = service.log(
            action=AuditAction.LOGIN,
            resource_type="session",
            outcome=AuditOutcome.SUCCESS,
        )
        sig = event.hmac_signature
        assert len(sig) == 64
        # Must be valid hex
        int(sig, 16)
