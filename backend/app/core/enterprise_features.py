"""
Community-side accessors for optional (Enterprise) capabilities.

Community code must never import an Enterprise module directly.  Where a
Community route or service needs to *reach* an Enterprise capability when one
happens to be installed, it asks this module, which looks the capability up in
``backend.app.core.hooks`` by key.  Every accessor returns ``None`` in a build
that has not registered the capability, and each caller answers that with an
explicit HTTP 501 -- never with silence.

The keys are the contract with ``ee.register(hooks)`` (and, until the
Enterprise modules move, with ``backend/app/ee_transitional.py``):

``split_url.routing``
    A **provider**: a zero-argument callable answering the routing function,
    or ``None`` when unlicensed.  Read through
    :func:`split_url_routing_available`, which gates *creation* of
    ``experiment_type=split_url`` -- without routing, a Community user could
    store a split-URL experiment that nothing ever routes.

``split_url.preview``
    The body of ``GET /experiments/{id}/split-url/preview``.

``compliance.report`` / ``compliance.export``
    The bodies of ``GET /compliance/reports/{standard}`` and
    ``GET /compliance/export``.  ``GET /compliance/audit-events`` is Community
    and is NOT brokered here.

``counters.service``
    A **provider** answering ``DynamoDBCounterService`` -- the first of
    ``BanditScheduler``'s four stats sources -- or ``None``.  A provider rather
    than the class because the scheduler runs for days and the licence can
    lapse under it; absent, it simply falls through to PostgreSQL.

Route bodies carry their own licence check (the Enterprise registration wraps
them), so a registered-but-unlicensed call answers 403 ``feature_not_licensed``
rather than the 501 an uninstalled one gets.  The distinction is deliberate:
501 means "this build does not have it", 403 means "it is here and needs a
licence".
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from backend.app.core import hooks

# Detail strings used by the Community 501 responses.  Kept here so the wording
# stays identical everywhere a capability is refused.
SPLIT_URL_UNAVAILABLE_DETAIL = (
    "Split URL testing is not available in this edition. "
    "experiment_type='split_url' requires the Enterprise split-URL router."
)
COMPLIANCE_REPORTING_UNAVAILABLE_DETAIL = (
    "Compliance report generation and audit export are not available in this "
    "edition. The compliance audit event log (GET /compliance/audit-events) is "
    "available in all editions."
)


def _provided(capability: str) -> Optional[Any]:
    """Resolve a provider-style capability: call it, return what it answers."""
    provider = hooks.get_capability(capability)
    if provider is None:
        return None
    return provider()


def split_url_routing_available() -> bool:
    """True when Enterprise split-URL routing can serve a split-URL experiment."""
    return _provided("split_url.routing") is not None


def split_url_routing_installed() -> bool:
    """True when the routing capability is *registered*, licensed or not.

    Lets a Community route tell "this build does not have it" (501) from
    "it is here and the licence does not cover it" (403).
    """
    return hooks.get_capability("split_url.routing") is not None


def split_url_preview_handler() -> Optional[Callable[..., Any]]:
    """The Enterprise handler for the split-URL preview route, or ``None``."""
    return hooks.get_capability("split_url.preview")


def compliance_report_handler() -> Optional[Callable[..., Any]]:
    """The Enterprise handler for compliance report generation, or ``None``."""
    return hooks.get_capability("compliance.report")


def compliance_export_handler() -> Optional[Callable[..., Any]]:
    """The Enterprise handler for the audit export route, or ``None``."""
    return hooks.get_capability("compliance.export")


def realtime_counter_service() -> Optional[type]:
    """The Enterprise ``DynamoDBCounterService`` class, or ``None``."""
    return _provided("counters.service")
