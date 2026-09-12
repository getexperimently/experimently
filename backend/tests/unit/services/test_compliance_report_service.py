"""
Unit tests for ComplianceReportService.

Tests cover:
- generate_report() returns a ComplianceReport with correct period fields
- generate_report() counts total events in the period
- generate_report() breaks down events by action
- generate_report() breaks down events by outcome
- generate_report() breaks down events by resource_type
- generate_report() performs HMAC integrity checks
- generate_report() flags tampered events
- SOC 2 default period is 365 days
- ISO 27001 default period is 730 days
- generated_at is a recent UTC datetime
- Empty period yields zero counts
- export_events() returns JSON
- export_events() returns CSV
- CSV has the correct column headers
- export_events() filters by date range
- Exported events include hmac_signature
"""

import csv
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from backend.app.models.compliance_audit_event import (
    AuditAction,
    AuditOutcome,
    ComplianceAuditEvent,
)
from backend.app.services.compliance_report_service import (
    ComplianceReport,
    ComplianceReportService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_event(
    action=AuditAction.CREATE,
    outcome=AuditOutcome.SUCCESS,
    resource_type="feature_flag",
    resource_id=None,
    actor_id=None,
    hmac_signature="a" * 64,
    timestamp=None,
):
    """Create a mock ComplianceAuditEvent with sensible defaults."""
    event = MagicMock(spec=ComplianceAuditEvent)
    event.id = uuid.uuid4()
    event.action = action
    event.outcome = outcome
    event.resource_type = resource_type
    event.resource_id = str(resource_id or uuid.uuid4())
    event.actor_id = actor_id or uuid.uuid4()
    event.hmac_signature = hmac_signature
    event.timestamp = timestamp or datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    return event


def make_mock_db_with_events(events):
    """Return a mock SQLAlchemy Session whose query returns the given events."""
    db = MagicMock()
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.all.return_value = events
    mock_query.count.return_value = len(events)
    db.query.return_value = mock_query
    return db


# ---------------------------------------------------------------------------
# TestGenerateSoc2Report
# ---------------------------------------------------------------------------


class TestGenerateSoc2Report:
    """Tests for ComplianceReportService.generate_report()."""

    def test_report_includes_period(self):
        """Report has period_start and period_end fields."""
        db = make_mock_db_with_events([])
        service = ComplianceReportService(db)
        report = service.generate_report(standard="soc2")

        assert hasattr(report, "period_start")
        assert hasattr(report, "period_end")
        assert report.period_start is not None
        assert report.period_end is not None
        assert isinstance(report.period_start, datetime)
        assert isinstance(report.period_end, datetime)

    def test_report_includes_event_count(self):
        """total_events matches the number of events in period."""
        events = [make_mock_event() for _ in range(5)]
        db = make_mock_db_with_events(events)
        service = ComplianceReportService(db)
        report = service.generate_report(standard="soc2")

        assert report.total_events == 5

    def test_report_breaks_down_by_action(self):
        """events_by_action counts events for each action type."""
        events = [
            make_mock_event(action=AuditAction.CREATE),
            make_mock_event(action=AuditAction.CREATE),
            make_mock_event(action=AuditAction.UPDATE),
            make_mock_event(action=AuditAction.DELETE),
        ]
        db = make_mock_db_with_events(events)
        service = ComplianceReportService(db)
        report = service.generate_report(standard="soc2")

        assert report.events_by_action["CREATE"] == 2
        assert report.events_by_action["UPDATE"] == 1
        assert report.events_by_action["DELETE"] == 1

    def test_report_breaks_down_by_outcome(self):
        """events_by_outcome counts SUCCESS, FAILURE, DENIED."""
        events = [
            make_mock_event(outcome=AuditOutcome.SUCCESS),
            make_mock_event(outcome=AuditOutcome.SUCCESS),
            make_mock_event(outcome=AuditOutcome.FAILURE),
            make_mock_event(outcome=AuditOutcome.DENIED),
        ]
        db = make_mock_db_with_events(events)
        service = ComplianceReportService(db)
        report = service.generate_report(standard="soc2")

        assert report.events_by_outcome["SUCCESS"] == 2
        assert report.events_by_outcome["FAILURE"] == 1
        assert report.events_by_outcome["DENIED"] == 1

    def test_report_breaks_down_by_resource_type(self):
        """events_by_resource_type groups events by resource_type."""
        events = [
            make_mock_event(resource_type="feature_flag"),
            make_mock_event(resource_type="feature_flag"),
            make_mock_event(resource_type="experiment"),
        ]
        db = make_mock_db_with_events(events)
        service = ComplianceReportService(db)
        report = service.generate_report(standard="soc2")

        assert report.events_by_resource_type["feature_flag"] == 2
        assert report.events_by_resource_type["experiment"] == 1

    def test_report_includes_integrity_check_count(self):
        """integrity_checks counts events that have an hmac_signature."""
        events = [
            make_mock_event(hmac_signature="a" * 64),
            make_mock_event(hmac_signature="b" * 64),
            make_mock_event(hmac_signature=None),  # No signature — not checked
        ]
        db = make_mock_db_with_events(events)
        service = ComplianceReportService(db)

        with patch("backend.app.core.hooks.audit_signer") as mock_signer:
            mock_signer.verify.return_value = True
            report = service.generate_report(standard="soc2")

        assert report.integrity_checks == 2

    def test_report_flags_tampered_events(self):
        """tampered_events > 0 when HMAC verification fails for some events."""
        events = [
            make_mock_event(hmac_signature="a" * 64),
            make_mock_event(hmac_signature="b" * 64),
        ]
        db = make_mock_db_with_events(events)
        service = ComplianceReportService(db)

        # First verify passes, second fails (tampered)
        with patch("backend.app.core.hooks.audit_signer") as mock_signer:
            mock_signer.verify.side_effect = [True, False]
            report = service.generate_report(standard="soc2")

        assert report.tampered_events == 1

    def test_soc2_report_covers_365_days_by_default(self):
        """SOC 2 default period is the last 365 days."""
        db = make_mock_db_with_events([])
        service = ComplianceReportService(db)
        now = datetime.now(timezone.utc)

        report = service.generate_report(standard="soc2")

        delta = report.period_end - report.period_start
        assert 364 <= delta.days <= 366  # Allow ±1 day for timing

    def test_iso27001_report_covers_730_days_by_default(self):
        """ISO 27001 default period is the last 730 days."""
        db = make_mock_db_with_events([])
        service = ComplianceReportService(db)

        report = service.generate_report(standard="iso27001")

        delta = report.period_end - report.period_start
        assert 729 <= delta.days <= 731  # Allow ±1 day for timing

    def test_report_has_generated_at_timestamp(self):
        """report.generated_at is a recent UTC datetime."""
        db = make_mock_db_with_events([])
        service = ComplianceReportService(db)
        before = datetime.now(timezone.utc)

        report = service.generate_report(standard="soc2")

        after = datetime.now(timezone.utc)
        assert before <= report.generated_at <= after
        assert report.generated_at.tzinfo is not None

    def test_empty_period_report_has_zero_counts(self):
        """No events in period → total_events and all breakdowns are zero/empty."""
        db = make_mock_db_with_events([])
        service = ComplianceReportService(db)
        report = service.generate_report(standard="soc2")

        assert report.total_events == 0
        assert report.events_by_action == {}
        assert report.events_by_outcome == {}
        assert report.events_by_resource_type == {}
        assert report.integrity_checks == 0
        assert report.tampered_events == 0

    def test_report_standard_field_matches_input(self):
        """report.standard reflects the requested standard."""
        db = make_mock_db_with_events([])
        service = ComplianceReportService(db)

        soc2_report = service.generate_report(standard="soc2")
        iso_report = service.generate_report(standard="iso27001")

        assert soc2_report.standard == "soc2"
        assert iso_report.standard == "iso27001"

    def test_custom_date_range_overrides_defaults(self):
        """Providing explicit start_time/end_time overrides default period."""
        db = make_mock_db_with_events([])
        service = ComplianceReportService(db)
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 6, 30, tzinfo=timezone.utc)

        report = service.generate_report(
            standard="soc2", start_time=start, end_time=end
        )

        assert report.period_start == start
        assert report.period_end == end

    def test_integrity_pass_rate_is_1_when_all_pass(self):
        """integrity_pass_rate is 1.0 when all HMAC checks pass."""
        events = [make_mock_event(hmac_signature="a" * 64) for _ in range(3)]
        db = make_mock_db_with_events(events)
        service = ComplianceReportService(db)

        with patch("backend.app.core.hooks.audit_signer") as mock_signer:
            mock_signer.verify.return_value = True
            report = service.generate_report(standard="soc2")

        assert report.integrity_pass_rate == 1.0

    def test_integrity_pass_rate_is_0_when_all_tampered(self):
        """integrity_pass_rate is 0.0 when all HMAC checks fail."""
        events = [make_mock_event(hmac_signature="a" * 64) for _ in range(2)]
        db = make_mock_db_with_events(events)
        service = ComplianceReportService(db)

        with patch("backend.app.core.hooks.audit_signer") as mock_signer:
            mock_signer.verify.return_value = False
            report = service.generate_report(standard="soc2")

        assert report.integrity_pass_rate == 0.0

    def test_events_without_hmac_not_counted_in_integrity_checks(self):
        """Events with no hmac_signature are excluded from integrity_checks count."""
        events = [
            make_mock_event(hmac_signature=None),
            make_mock_event(hmac_signature=""),
        ]
        db = make_mock_db_with_events(events)
        service = ComplianceReportService(db)
        report = service.generate_report(standard="soc2")

        assert report.integrity_checks == 0


# ---------------------------------------------------------------------------
# TestExportAuditEvents
# ---------------------------------------------------------------------------


class TestUnsignedRowsAreReported:
    """Unsigned rows are a reachable state now, and the report must say so.

    The Community signer writes no signature, and a process whose Enterprise
    registration failed falls back to it; counting only signed rows showed a
    1.0 pass rate over a period with no integrity at all.
    """

    @pytest.mark.regression
    def test_unsigned_events_and_coverage_are_counted(self):
        from backend.app.core import hooks

        events = [
            make_mock_event(hmac_signature="a" * 64),
            make_mock_event(hmac_signature="b" * 64),
            make_mock_event(hmac_signature=None),
            make_mock_event(hmac_signature=None),
            make_mock_event(hmac_signature=None),
            make_mock_event(hmac_signature=None),
        ]
        service = ComplianceReportService(make_mock_db_with_events(events))
        with patch("backend.app.core.hooks.audit_signer") as mock_signer:
            mock_signer.verify.return_value = True
            mock_signer.name = "hmac-sha256"
            report = service.generate_report(standard="soc2")

        assert report.integrity_checks == 2
        assert report.unsigned_events == 4
        # The pass rate is still over *checked* rows...
        assert report.integrity_pass_rate == 1.0
        # ...but coverage says two of six were verifiable.
        assert report.integrity_coverage == pytest.approx(2 / 6)
        assert report.signing_enabled is True
        assert isinstance(hooks.audit_signer.name, str)

    def test_signing_disabled_is_reported_when_the_null_signer_is_installed(self):
        from backend.app.core import hooks

        service = ComplianceReportService(make_mock_db_with_events([]))
        previous = hooks.set_audit_signer(hooks.NullAuditSigner())
        try:
            report = service.generate_report(standard="soc2")
        finally:
            hooks.set_audit_signer(previous)
        assert report.signing_enabled is False
        assert report.integrity_coverage == 1.0  # no events, nothing unverified


class TestVerifierIsTheInstalledSigner:
    """Signer and verifier must be the same object.

    The report used to verify with a module-level ``AuditSigningService()`` of
    its own while ``AuditLogService`` signed through ``hooks.audit_signer``, so
    a signer installed through the seam with a different key would have had
    every event it signed reported as tampered.
    """

    @pytest.mark.regression
    def test_report_verifies_through_hooks_audit_signer(self):
        from backend.app.core import hooks

        class CountingSigner:
            name = "counting"
            calls = 0

            def sign(self, event):
                return "x" * 64

            def verify(self, event):
                CountingSigner.calls += 1
                return True

        events = [make_mock_event(hmac_signature="a" * 64)]
        service = ComplianceReportService(make_mock_db_with_events(events))
        previous = hooks.set_audit_signer(CountingSigner())
        try:
            report = service.generate_report(standard="soc2")
        finally:
            hooks.set_audit_signer(previous)

        assert CountingSigner.calls == 1
        assert report.integrity_checks == 1
        assert report.tampered_events == 0


class TestExportAuditEvents:
    """Tests for ComplianceReportService.export_events()."""

    def _make_event_obj(self, **kwargs):
        """Create a mock event with serialisable fields."""
        event = MagicMock(spec=ComplianceAuditEvent)
        event.id = uuid.uuid4()
        event.timestamp = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        event.action = kwargs.get("action", AuditAction.CREATE)
        event.resource_type = kwargs.get("resource_type", "feature_flag")
        event.resource_id = kwargs.get("resource_id", str(uuid.uuid4()))
        event.actor_id = kwargs.get("actor_id", uuid.uuid4())
        event.outcome = kwargs.get("outcome", AuditOutcome.SUCCESS)
        event.hmac_signature = kwargs.get("hmac_signature", "a" * 64)
        return event

    def _build_service_with_events(self, events):
        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = events
        db.query.return_value = mock_query
        return ComplianceReportService(db)

    def test_export_as_json(self):
        """export_events() without format arg returns a valid JSON string."""
        event = self._make_event_obj()
        service = self._build_service_with_events([event])

        result = service.export_events(format="json")

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_export_as_csv(self):
        """export_events(format='csv') returns a CSV string."""
        event = self._make_event_obj()
        service = self._build_service_with_events([event])

        result = service.export_events(format="csv")

        assert isinstance(result, str)
        # CSV must have at least a header line and one data line
        lines = [line for line in result.strip().splitlines() if line]
        assert len(lines) >= 2

    def test_csv_has_correct_headers(self):
        """CSV output has the expected column headers."""
        service = self._build_service_with_events([])

        result = service.export_events(format="csv")

        reader = csv.DictReader(io.StringIO(result))
        fieldnames = reader.fieldnames or []
        required_headers = {
            "id",
            "timestamp",
            "action",
            "resource_type",
            "resource_id",
            "actor_id",
            "outcome",
            "hmac_signature",
        }
        for header in required_headers:
            assert header in fieldnames, f"Missing CSV header: {header}"

    def test_export_filters_by_date_range(self):
        """export_events(start_time, end_time) passes filter args to DB query."""
        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []
        db.query.return_value = mock_query
        service = ComplianceReportService(db)

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 6, 30, tzinfo=timezone.utc)
        service.export_events(format="json", start_time=start, end_time=end)

        # filter() should have been called (at least once) because start/end were provided
        assert mock_query.filter.call_count >= 1

    def test_export_includes_hmac_signature(self):
        """Exported JSON events include the hmac_signature field."""
        event = self._make_event_obj(hmac_signature="deadbeef" * 8)
        service = self._build_service_with_events([event])

        result = service.export_events(format="json")

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert "hmac_signature" in parsed[0]
        assert parsed[0]["hmac_signature"] == "deadbeef" * 8

    def test_export_json_includes_all_required_fields(self):
        """Each JSON record has id, timestamp, action, resource_type, resource_id, actor_id, outcome."""
        event = self._make_event_obj()
        service = self._build_service_with_events([event])

        result = service.export_events(format="json")
        parsed = json.loads(result)
        record = parsed[0]

        required_keys = {
            "id",
            "timestamp",
            "action",
            "resource_type",
            "resource_id",
            "actor_id",
            "outcome",
            "hmac_signature",
        }
        for key in required_keys:
            assert key in record, f"Missing key in JSON export: {key}"

    def test_export_empty_dataset_returns_empty_json_array(self):
        """export_events() with no events returns '[]'."""
        service = self._build_service_with_events([])

        result = service.export_events(format="json")

        parsed = json.loads(result)
        assert parsed == []

    def test_export_empty_dataset_returns_csv_with_headers_only(self):
        """export_events(format='csv') with no events returns just the header row."""
        service = self._build_service_with_events([])

        result = service.export_events(format="csv")

        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows == []
        assert reader.fieldnames is not None and len(reader.fieldnames) > 0

    def test_export_multiple_events_as_json(self):
        """export_events() with multiple events returns all as a list."""
        events = [self._make_event_obj() for _ in range(3)]
        service = self._build_service_with_events(events)

        result = service.export_events(format="json")
        parsed = json.loads(result)

        assert len(parsed) == 3

    def test_export_multiple_events_as_csv(self):
        """export_events(format='csv') with multiple events returns multiple data rows."""
        events = [self._make_event_obj() for _ in range(3)]
        service = self._build_service_with_events(events)

        result = service.export_events(format="csv")
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)

        assert len(rows) == 3
