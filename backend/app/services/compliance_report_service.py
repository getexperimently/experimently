"""
Compliance report generation service.

Generates SOC 2 Type 2 and ISO 27001 compliance reports from the audit event
log. Reports include event breakdowns by action, outcome, and resource type,
as well as HMAC integrity verification statistics.

Also supports exporting audit events as JSON or CSV for chain-of-custody.
"""

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from backend.app.core import hooks
from backend.app.core.config import settings
from backend.app.models.compliance_audit_event import (
    ComplianceAuditEvent,
)

# Verified through the seam, with whatever signer the Enterprise registration
# installed: signer and verifier must be the same object, or a signer with a
# different key would report every event it signed as tampered.


@dataclass
class ComplianceReport:
    """Result of a compliance report generation run.

    Attributes:
        standard: The compliance standard used ('soc2' or 'iso27001').
        period_start: Start of the audit period covered by this report.
        period_end: End of the audit period covered by this report.
        generated_at: UTC datetime when the report was generated.
        total_events: Total number of audit events in the period.
        events_by_action: Breakdown of event counts keyed by AuditAction value.
        events_by_outcome: Breakdown of event counts keyed by AuditOutcome value.
        events_by_resource_type: Breakdown of event counts keyed by resource_type.
        integrity_checks: Number of events that carried an HMAC signature (checked).
        tampered_events: Number of events whose HMAC signature failed verification.
        integrity_pass_rate: Fraction of checked events that passed (0.0–1.0).
        unsigned_events: Events that carried no signature and so could not be
            checked at all. Unsigned rows are a reachable state -- the
            Community signer writes none, and a process whose Enterprise
            registration failed falls back to it -- so a report that counted
            only signed rows showed a 1.0 pass rate over a period with no
            integrity at all. This is that number, and ``integrity_coverage``
            is the fraction of the period it leaves verified.
        integrity_coverage: Fraction of all events that were checked (0.0–1.0).
            1.0 only when every row in the period carried a signature.
        signing_enabled: Whether the signer installed in this process signs
            new events. False means every event written from now on is
            unsigned, whatever the period above shows.
    """

    standard: str
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    total_events: int
    events_by_action: Dict[str, int] = field(default_factory=dict)
    events_by_outcome: Dict[str, int] = field(default_factory=dict)
    events_by_resource_type: Dict[str, int] = field(default_factory=dict)
    integrity_checks: int = 0
    tampered_events: int = 0
    integrity_pass_rate: float = 1.0
    unsigned_events: int = 0
    integrity_coverage: float = 1.0
    signing_enabled: bool = True


class ComplianceReportService:
    """Service for generating compliance reports and exporting audit events.

    Usage::

        service = ComplianceReportService(db)

        # On-demand SOC 2 report
        report = service.generate_report(standard="soc2")

        # Export last year's events as CSV
        csv_str = service.export_events(format="csv")
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_report(
        self,
        standard: str = "soc2",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> ComplianceReport:
        """Generate a compliance audit report for the given standard and period.

        If *start_time* is not provided the default look-back window is used:
        - SOC 2: ``settings.AUDIT_RETENTION_DAYS_SOC2`` days (default 365)
        - ISO 27001: ``settings.AUDIT_RETENTION_DAYS_ISO27001`` days (default 730)

        Args:
            standard: 'soc2' (default) or 'iso27001'.
            start_time: Optional explicit start of the reporting period (UTC).
            end_time: Optional explicit end of the reporting period (UTC).
                Defaults to now.

        Returns:
            A :class:`ComplianceReport` dataclass instance.
        """
        end_time = end_time or datetime.now(timezone.utc)

        if start_time is None:
            if standard == "iso27001":
                days = settings.AUDIT_RETENTION_DAYS_ISO27001
            else:
                days = settings.AUDIT_RETENTION_DAYS_SOC2
            start_time = end_time - timedelta(days=days)

        query = self._db.query(ComplianceAuditEvent).filter(
            ComplianceAuditEvent.timestamp >= start_time,
            ComplianceAuditEvent.timestamp <= end_time,
        )

        events = query.all()
        total = len(events)

        by_action: Dict[str, int] = {}
        by_outcome: Dict[str, int] = {}
        by_resource: Dict[str, int] = {}
        integrity_checks = 0
        unsigned = 0
        tampered = 0

        for event in events:
            # --- by_action ---
            action_key = (
                event.action.value
                if hasattr(event.action, "value")
                else str(event.action)
            )
            by_action[action_key] = by_action.get(action_key, 0) + 1

            # --- by_outcome ---
            outcome_key = (
                event.outcome.value
                if hasattr(event.outcome, "value")
                else str(event.outcome)
            )
            by_outcome[outcome_key] = by_outcome.get(outcome_key, 0) + 1

            # --- by_resource_type ---
            if event.resource_type:
                by_resource[event.resource_type] = (
                    by_resource.get(event.resource_type, 0) + 1
                )

            # --- HMAC integrity check ---
            if event.hmac_signature:
                integrity_checks += 1
                if not hooks.audit_signer.verify(event):
                    tampered += 1
            else:
                unsigned += 1

        pass_rate: float = 1.0
        if integrity_checks > 0:
            pass_rate = (integrity_checks - tampered) / integrity_checks
        coverage: float = 1.0 if total == 0 else integrity_checks / total

        return ComplianceReport(
            standard=standard,
            period_start=start_time,
            period_end=end_time,
            generated_at=datetime.now(timezone.utc),
            total_events=total,
            events_by_action=by_action,
            events_by_outcome=by_outcome,
            events_by_resource_type=by_resource,
            integrity_checks=integrity_checks,
            tampered_events=tampered,
            integrity_pass_rate=pass_rate,
            unsigned_events=unsigned,
            integrity_coverage=coverage,
            signing_enabled=getattr(hooks.audit_signer, "name", "") != "null",
        )

    # ------------------------------------------------------------------
    # Audit event export
    # ------------------------------------------------------------------

    def export_events(
        self,
        format: str = "json",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> str:
        """Export audit events as a JSON or CSV string.

        The export includes the HMAC signature for each event to support
        chain-of-custody verification by auditors.

        Args:
            format: 'json' (default) or 'csv'.
            start_time: Only include events at or after this UTC datetime.
            end_time: Only include events at or before this UTC datetime.

        Returns:
            A string containing the serialised events.
        """
        query = self._db.query(ComplianceAuditEvent)

        if start_time:
            query = query.filter(ComplianceAuditEvent.timestamp >= start_time)
        if end_time:
            query = query.filter(ComplianceAuditEvent.timestamp <= end_time)

        events = query.order_by(ComplianceAuditEvent.timestamp.asc()).all()

        if format == "csv":
            return self._to_csv(events)
        return self._to_json(events)

    # ------------------------------------------------------------------
    # Private serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _event_to_dict(event) -> dict:
        """Convert a ComplianceAuditEvent (or mock) to a plain dict."""
        return {
            "id": str(event.id),
            "timestamp": (event.timestamp.isoformat() if event.timestamp else None),
            "action": (
                event.action.value
                if hasattr(event.action, "value")
                else str(event.action)
            ),
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "actor_id": str(event.actor_id) if event.actor_id else None,
            "outcome": (
                event.outcome.value
                if hasattr(event.outcome, "value")
                else str(event.outcome)
            ),
            "hmac_signature": event.hmac_signature,
        }

    def _to_json(self, events) -> str:
        rows = [self._event_to_dict(e) for e in events]
        return json.dumps(rows, indent=2)

    def _to_csv(self, events) -> str:
        output = io.StringIO()
        fieldnames = [
            "id",
            "timestamp",
            "action",
            "resource_type",
            "resource_id",
            "actor_id",
            "outcome",
            "hmac_signature",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for e in events:
            row = self._event_to_dict(e)
            # Replace None values with empty strings for CSV cleanliness
            writer.writerow({k: (v if v is not None else "") for k, v in row.items()})
        return output.getvalue()
