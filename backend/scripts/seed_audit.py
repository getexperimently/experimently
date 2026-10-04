"""Audit entries for the demo seeds, written the way the platform writes them (#221).

Every seeded entry goes through ``AuditService.record``, the platform's own
writer, with values built by the same helpers the routes use
(``audit_snapshot``, ``audit_identity``, ``audit_changes``, ``role_value``).
Only the timestamp is moved into the past, so the demo has a history.

A seed may write only an action the platform writes: ``seeded_entry``
refuses anything outside ``WRITTEN_ACTION_TYPES``. Safety rollbacks are never
seeded; StreamPulse's ``rollout_story.py --auto`` produces a real one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from backend.app.models.audit_log import ActionType, AuditLog, EntityType
from backend.app.services.audit_service import (
    AUDIT_NAME_ONLY_FIELDS,
    AUDIT_VALUE_FIELDS,
    WRITTEN_ACTION_TYPES,
    AuditService,
    audit_changes,
    audit_identity,
    audit_snapshot,
)

#: Actions a seed must never write, even though the platform writes them:
#: a safety rollback comes only from a real rollback.
NEVER_SEEDED = frozenset({ActionType.SAFETY_ROLLBACK})


class UnwrittenActionError(ValueError):
    """A seed tried to write an action the platform does not write."""


def seeded_entry(db, *, at: datetime, **entry: Any) -> AuditLog:
    """Add one entry with ``AuditService.record``'s arguments, dated ``at``.

    Raises ``UnwrittenActionError`` for an action outside
    ``WRITTEN_ACTION_TYPES`` or in ``NEVER_SEEDED``.
    """
    action = ActionType(entry["action"])
    if action not in WRITTEN_ACTION_TYPES or action in NEVER_SEEDED:
        raise UnwrittenActionError(
            f"a seed may not write {action.value}: the platform does not write it "
            "or it comes only from a real change"
        )
    row = AuditService.record(db, **entry)
    row.timestamp = at
    return row


def snapshot(entity_type: EntityType, source: Any, **overrides: Any) -> Dict[str, Any]:
    """``audit_snapshot`` of ``source`` with some fields replaced.

    ``overrides`` stand in for what the row held before a seeded change; a
    name-only field (``description``) is compared, never stored.
    """
    names = AUDIT_VALUE_FIELDS[entity_type] + AUDIT_NAME_ONLY_FIELDS[entity_type]
    fields = {name: getattr(source, name, None) for name in names}
    fields.update(overrides)
    return audit_snapshot(entity_type, fields)


def identity(entity_type: EntityType, source: Any, **overrides: Any):
    """What a create records: the identity fields."""
    return audit_identity(snapshot(entity_type, source, **overrides))


def changes(
    entity_type: EntityType,
    source: Any,
    before: Dict[str, Any],
    after: Optional[Dict[str, Any]] = None,
):
    """(old, new) for a seeded update, as the routes compute it."""
    return audit_changes(
        snapshot(entity_type, source, **before),
        snapshot(entity_type, source, **(after or {})),
    )
