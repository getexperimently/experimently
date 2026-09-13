"""
Unit tests for AuditSigningService.

Tests cover:
- Service instantiation with no args
- sign() returns non-empty hex string
- sign() is deterministic (same event → same signature)
- verify() returns True for freshly signed event
- verify() returns False if any canonical field is tampered
- verify() returns False if hmac_signature is None
- sign() includes all canonical fields
- verify() uses constant-time comparison (hmac.compare_digest)
- Signature changes when any canonical field changes
"""

import hashlib
import hmac as hmac_lib
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.app.models.compliance_audit_event import (
    AuditAction,
    AuditOutcome,
    ComplianceAuditEvent,
)
from modules.backend.app.services.audit_signing_service import AuditSigningService


def make_event(**kwargs):
    """Helper: create a ComplianceAuditEvent with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "timestamp": datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "action": AuditAction.CREATE,
        "resource_type": "feature_flag",
        "resource_id": "flag_001",
        "actor_id": uuid.uuid4(),
        "outcome": AuditOutcome.SUCCESS,
        "hmac_signature": None,
    }
    defaults.update(kwargs)
    event = ComplianceAuditEvent()
    for k, v in defaults.items():
        setattr(event, k, v)
    return event


class TestAuditSigningServiceInstantiation:
    """Tests for AuditSigningService construction."""

    def test_service_can_be_instantiated_with_no_args(self):
        """AuditSigningService() works with no constructor arguments."""
        svc = AuditSigningService()
        assert svc is not None

    def test_service_reads_key_from_settings(self):
        """Service reads AUDIT_HMAC_KEY from settings on construction."""
        with patch(
            "modules.backend.app.services.audit_signing_service.settings"
        ) as mock_settings:
            mock_settings.AUDIT_HMAC_KEY = "test-key-for-unit-test"
            svc = AuditSigningService()
            assert svc._key == b"test-key-for-unit-test"

    def test_service_accepts_bytes_key(self):
        """Service accepts a bytes AUDIT_HMAC_KEY."""
        with patch(
            "modules.backend.app.services.audit_signing_service.settings"
        ) as mock_settings:
            mock_settings.AUDIT_HMAC_KEY = b"bytes-key"
            svc = AuditSigningService()
            assert svc._key == b"bytes-key"


class TestAuditSigningServiceSign:
    """Tests for AuditSigningService.sign()."""

    def setup_method(self):
        self.svc = AuditSigningService()

    def test_sign_returns_non_empty_string(self):
        """sign() returns a non-empty string."""
        event = make_event()
        sig = self.svc.sign(event)
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_sign_returns_hex_string(self):
        """sign() returns a hex string (SHA-256 digest = 64 hex chars)."""
        event = make_event()
        sig = self.svc.sign(event)
        # SHA-256 hex digest is exactly 64 characters
        assert len(sig) == 64
        # Must be valid hex
        int(sig, 16)

    def test_sign_is_deterministic(self):
        """Same event fields always produce the same signature."""
        fixed_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        fixed_actor = uuid.UUID("aaaabbbb-aaaa-bbbb-aaaa-bbbbaaaabbbb")
        fixed_ts = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

        event1 = make_event(
            id=fixed_id,
            timestamp=fixed_ts,
            action=AuditAction.LOGIN,
            resource_type="session",
            resource_id=None,
            actor_id=fixed_actor,
            outcome=AuditOutcome.SUCCESS,
        )
        event2 = make_event(
            id=fixed_id,
            timestamp=fixed_ts,
            action=AuditAction.LOGIN,
            resource_type="session",
            resource_id=None,
            actor_id=fixed_actor,
            outcome=AuditOutcome.SUCCESS,
        )

        assert self.svc.sign(event1) == self.svc.sign(event2)

    def test_sign_changes_when_id_changes(self):
        """Changing the event id changes the signature."""
        event1 = make_event(id=uuid.UUID("11111111-1111-1111-1111-111111111111"))
        event2 = make_event(id=uuid.UUID("22222222-2222-2222-2222-222222222222"))
        # Copy all other fields from event1
        for field in [
            "timestamp",
            "action",
            "resource_type",
            "resource_id",
            "actor_id",
            "outcome",
        ]:
            setattr(event2, field, getattr(event1, field))
        assert self.svc.sign(event1) != self.svc.sign(event2)

    def test_sign_changes_when_action_changes(self):
        """Changing the action changes the signature."""
        event1 = make_event(action=AuditAction.CREATE)
        event2 = make_event(action=AuditAction.DELETE)
        for field in [
            "id",
            "timestamp",
            "resource_type",
            "resource_id",
            "actor_id",
            "outcome",
        ]:
            setattr(event2, field, getattr(event1, field))
        assert self.svc.sign(event1) != self.svc.sign(event2)

    def test_sign_changes_when_resource_type_changes(self):
        """Changing resource_type changes the signature."""
        event1 = make_event(resource_type="feature_flag")
        event2 = make_event(resource_type="experiment")
        for field in [
            "id",
            "timestamp",
            "action",
            "resource_id",
            "actor_id",
            "outcome",
        ]:
            setattr(event2, field, getattr(event1, field))
        assert self.svc.sign(event1) != self.svc.sign(event2)

    def test_sign_changes_when_resource_id_changes(self):
        """Changing resource_id changes the signature."""
        event1 = make_event(resource_id="res_001")
        event2 = make_event(resource_id="res_002")
        for field in [
            "id",
            "timestamp",
            "action",
            "resource_type",
            "actor_id",
            "outcome",
        ]:
            setattr(event2, field, getattr(event1, field))
        assert self.svc.sign(event1) != self.svc.sign(event2)

    def test_sign_changes_when_actor_id_changes(self):
        """Changing actor_id changes the signature."""
        event1 = make_event(actor_id=uuid.UUID("aaaa0000-0000-0000-0000-000000000001"))
        event2 = make_event(actor_id=uuid.UUID("bbbb0000-0000-0000-0000-000000000002"))
        for field in [
            "id",
            "timestamp",
            "action",
            "resource_type",
            "resource_id",
            "outcome",
        ]:
            setattr(event2, field, getattr(event1, field))
        assert self.svc.sign(event1) != self.svc.sign(event2)

    def test_sign_changes_when_outcome_changes(self):
        """Changing outcome changes the signature."""
        event1 = make_event(outcome=AuditOutcome.SUCCESS)
        event2 = make_event(outcome=AuditOutcome.DENIED)
        for field in [
            "id",
            "timestamp",
            "action",
            "resource_type",
            "resource_id",
            "actor_id",
        ]:
            setattr(event2, field, getattr(event1, field))
        assert self.svc.sign(event1) != self.svc.sign(event2)

    def test_sign_changes_when_timestamp_changes(self):
        """Changing timestamp changes the signature."""
        event1 = make_event(timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc))
        event2 = make_event(timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc))
        for field in [
            "id",
            "action",
            "resource_type",
            "resource_id",
            "actor_id",
            "outcome",
        ]:
            setattr(event2, field, getattr(event1, field))
        assert self.svc.sign(event1) != self.svc.sign(event2)

    def test_sign_includes_all_canonical_fields(self):
        """sign() canonical string includes all 7 required fields."""
        from modules.backend.app.services.audit_signing_service import _CANONICAL_FIELDS

        expected_fields = {
            "id",
            "timestamp",
            "action",
            "resource_type",
            "resource_id",
            "actor_id",
            "outcome",
        }
        assert expected_fields == set(_CANONICAL_FIELDS)

    def test_sign_handles_none_fields_gracefully(self):
        """sign() handles None values for nullable canonical fields."""
        event = make_event(resource_id=None, actor_id=None)
        sig = self.svc.sign(event)
        assert isinstance(sig, str)
        assert len(sig) == 64


class TestAuditSigningServiceVerify:
    """Tests for AuditSigningService.verify()."""

    def setup_method(self):
        self.svc = AuditSigningService()

    def test_verify_returns_true_for_freshly_signed_event(self):
        """verify() returns True when the event was just signed."""
        event = make_event()
        event.hmac_signature = self.svc.sign(event)
        assert self.svc.verify(event) is True

    def test_verify_returns_false_for_none_signature(self):
        """verify() returns False if hmac_signature is None."""
        event = make_event()
        event.hmac_signature = None
        assert self.svc.verify(event) is False

    def test_verify_returns_false_for_empty_signature(self):
        """verify() returns False if hmac_signature is empty string."""
        event = make_event()
        event.hmac_signature = ""
        assert self.svc.verify(event) is False

    def test_verify_returns_false_after_id_tampered(self):
        """verify() returns False if id is changed after signing."""
        event = make_event()
        event.hmac_signature = self.svc.sign(event)
        event.id = uuid.uuid4()  # tamper
        assert self.svc.verify(event) is False

    def test_verify_returns_false_after_action_tampered(self):
        """verify() returns False if action is changed after signing."""
        event = make_event(action=AuditAction.CREATE)
        event.hmac_signature = self.svc.sign(event)
        event.action = AuditAction.DELETE  # tamper
        assert self.svc.verify(event) is False

    def test_verify_returns_false_after_resource_type_tampered(self):
        """verify() returns False if resource_type is changed after signing."""
        event = make_event(resource_type="feature_flag")
        event.hmac_signature = self.svc.sign(event)
        event.resource_type = "experiment"  # tamper
        assert self.svc.verify(event) is False

    def test_verify_returns_false_after_resource_id_tampered(self):
        """verify() returns False if resource_id is changed after signing."""
        event = make_event(resource_id="res_001")
        event.hmac_signature = self.svc.sign(event)
        event.resource_id = "res_999"  # tamper
        assert self.svc.verify(event) is False

    def test_verify_returns_false_after_actor_id_tampered(self):
        """verify() returns False if actor_id is changed after signing."""
        event = make_event()
        event.hmac_signature = self.svc.sign(event)
        event.actor_id = uuid.uuid4()  # tamper
        assert self.svc.verify(event) is False

    def test_verify_returns_false_after_outcome_tampered(self):
        """verify() returns False if outcome is changed after signing."""
        event = make_event(outcome=AuditOutcome.SUCCESS)
        event.hmac_signature = self.svc.sign(event)
        event.outcome = AuditOutcome.DENIED  # tamper
        assert self.svc.verify(event) is False

    def test_verify_returns_false_after_timestamp_tampered(self):
        """verify() returns False if timestamp is changed after signing."""
        event = make_event(timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc))
        event.hmac_signature = self.svc.sign(event)
        event.timestamp = datetime(2024, 12, 31, tzinfo=timezone.utc)  # tamper
        assert self.svc.verify(event) is False

    def test_verify_uses_constant_time_comparison(self):
        """verify() uses hmac.compare_digest for constant-time comparison."""
        # We patch hmac.compare_digest to verify it's called
        event = make_event()
        event.hmac_signature = self.svc.sign(event)

        with patch(
            "modules.backend.app.services.audit_signing_service.hmac_lib.compare_digest",
            wraps=hmac_lib.compare_digest,
        ) as mock_cd:
            result = self.svc.verify(event)
            mock_cd.assert_called_once()
            assert result is True

    def test_verify_returns_false_for_garbage_signature(self):
        """verify() returns False for a random garbage signature string."""
        event = make_event()
        event.hmac_signature = "deadbeef" * 8  # 64 hex chars, but wrong
        assert self.svc.verify(event) is False

    def test_multiple_sign_verify_cycles(self):
        """Multiple consecutive sign→verify cycles all succeed."""
        for _ in range(5):
            event = make_event(
                id=uuid.uuid4(),
                action=AuditAction.UPDATE,
                resource_type="experiment",
                outcome=AuditOutcome.SUCCESS,
            )
            event.hmac_signature = self.svc.sign(event)
            assert self.svc.verify(event) is True
