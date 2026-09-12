"""The open-core seam: extension points Community code calls, Enterprise fills.

Community Edition (CE) code never imports Enterprise Edition (EE) code.  Where
CE needs behaviour that only EE provides, it calls through a hook defined here.
Every hook ships a Community default that is a no-op or a null implementation,
so a build with no ``ee`` package behaves exactly as the open-source product is
meant to; :mod:`backend.app.ee_loader` installs the EE implementations at
start-up when the ``ee`` package is importable.

Hooks
-----
``audit_signer``
    Signs :class:`ComplianceAuditEvent` rows.  CE default writes no signature.
``register_router`` / ``apply_routers``
    Extra API routers to mount on the v1 router.
``register_model_module`` / ``import_registered_models``
    Extra SQLAlchemy model modules to import so their tables join
    ``Base.metadata``.
``register_tags`` / ``extra_tags_metadata``
    Extra OpenAPI tag metadata.
``register_capability`` / ``get_capability``
    Named implementations a Community call site asks for by key -- the body
    of a route whose URL exists in every edition, or a service class a
    scheduler prefers when it is installed.  ``get_capability`` returns
    ``None`` for anything nobody registered, and the caller answers that with
    an explicit refusal (HTTP 501) or a fallback, never with silence.  The
    keys are the contract; ``core/enterprise_features.py`` names them.

There is deliberately no ``register_scheduler``: all five schedulers started in
``main.py``'s lifespan are Community, and no Enterprise module needs one today
(``docs/planning/ee-coupling-report.md`` §5).  Add it when P5's PHI purge job
actually needs it, not before.
"""

from __future__ import annotations

import importlib
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "AuditSigner",
    "NullAuditSigner",
    "apply_routers",
    "audit_signer",
    "capability_names",
    "extra_tags_metadata",
    "get_capability",
    "import_registered_models",
    "register_capability",
    "register_model_module",
    "register_router",
    "register_tags",
    "reset",
    "reset_audit_signer",
    "set_audit_signer",
]


# ---------------------------------------------------------------------------
# Audit signing
# ---------------------------------------------------------------------------


class AuditSigner(Protocol):
    """What ``AuditLogService`` needs from a signer."""

    def sign(self, event: Any) -> Optional[str]:
        """Return a signature for *event*, or ``None`` when unsigned."""
        ...

    def verify(self, event: Any) -> bool:
        """Return True when *event*'s stored signature is intact."""
        ...


class NullAuditSigner:
    """Community default: audit events are recorded, but not signed.

    Tamper-evidence (HMAC-SHA256, EP-033) is an Enterprise feature.  Writing
    ``None`` is safe on the hot path because
    ``compliance_audit_events.hmac_signature`` is nullable in both the model
    (``models/compliance_audit_event.py:90``) and the migration that created it
    (``ep033_add_compliance_audit_events.py:97``) — the six CE call sites that
    log on every experiment and feature-flag mutation keep working unchanged.

    ``verify`` reports True for an unsigned row: absence of a signature is the
    documented CE state, not evidence of tampering.  A row that *does* carry a
    signature cannot be checked without the key, so it is reported as unverified.
    """

    name = "null"

    def sign(self, event: Any) -> Optional[str]:
        return None

    def verify(self, event: Any) -> bool:
        return getattr(event, "hmac_signature", None) is None


#: The active signer.  Look this up through the module (``hooks.audit_signer``)
#: rather than importing the name, so that :func:`set_audit_signer` is visible
#: to callers that were imported before the Enterprise loader ran.
audit_signer: AuditSigner = NullAuditSigner()

_DEFAULT_AUDIT_SIGNER: AuditSigner = audit_signer


def set_audit_signer(signer: AuditSigner) -> AuditSigner:
    """Install *signer*; returns the one it replaced."""
    global audit_signer
    previous = audit_signer
    audit_signer = signer
    logger.debug("audit_signer set to %s", type(signer).__name__)
    return previous


def reset_audit_signer() -> None:
    """Restore the Community default (used by tests)."""
    set_audit_signer(_DEFAULT_AUDIT_SIGNER)


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

_lock = threading.RLock()
_router_registrars: List[Callable[[Any], None]] = []
_model_modules: List[str] = []
_tags_metadata: List[Dict[str, Any]] = []
_capabilities: Dict[str, Any] = {}


def register_router(registrar: Callable[[Any], None]) -> None:
    """Register a callable that mounts routers on the v1 ``APIRouter``.

    The callable receives the router and is expected to call
    ``include_router`` on it.  Registering the same callable twice is a no-op,
    so a loader that runs again (a second ``import backend.app.main`` in one
    process, say) cannot mount a route twice.
    """
    with _lock:
        if registrar not in _router_registrars:
            _router_registrars.append(registrar)


def apply_routers(router: Any) -> int:
    """Run every registered router registrar against *router*.

    Returns the number of registrars applied.
    """
    with _lock:
        registrars = list(_router_registrars)
    for registrar in registrars:
        registrar(router)
    return len(registrars)


def register_model_module(module_path: str) -> None:
    """Register a dotted module path holding SQLAlchemy models.

    The module is imported by :func:`import_registered_models`, which is what
    puts its tables on ``Base.metadata`` for ``create_all`` and for alembic's
    autogenerate.
    """
    with _lock:
        if module_path not in _model_modules:
            _model_modules.append(module_path)


def import_registered_models() -> Tuple[str, ...]:
    """Import every registered model module; returns the paths imported."""
    with _lock:
        modules = tuple(_model_modules)
    for module_path in modules:
        importlib.import_module(module_path)
    return modules


def register_tags(tags: Sequence[Dict[str, Any]]) -> None:
    """Register OpenAPI tag metadata entries, skipping duplicate names."""
    with _lock:
        known = {tag.get("name") for tag in _tags_metadata}
        for tag in tags:
            if tag.get("name") not in known:
                _tags_metadata.append(dict(tag))
                known.add(tag.get("name"))


def extra_tags_metadata() -> List[Dict[str, Any]]:
    """Tag metadata contributed through the seam, in registration order."""
    with _lock:
        return [dict(tag) for tag in _tags_metadata]


def register_capability(name: str, implementation: Any) -> None:
    """Register *implementation* under *name*, replacing any earlier one.

    Replacement, not first-wins: a test that installs a fake for one key must
    be able to do so after the loader has run.  What an implementation *is*
    depends on the key -- a route body, a class, a zero-argument provider --
    and is documented next to the accessor that reads it.
    """
    with _lock:
        _capabilities[name] = implementation


def get_capability(name: str) -> Optional[Any]:
    """The implementation registered under *name*, or ``None``."""
    with _lock:
        return _capabilities.get(name)


def capability_names() -> Tuple[str, ...]:
    """Every registered capability key, sorted (diagnostics and tests)."""
    with _lock:
        return tuple(sorted(_capabilities))


def reset() -> None:
    """Clear every registry and restore the Community signer (tests only)."""
    with _lock:
        _router_registrars.clear()
        _model_modules.clear()
        _tags_metadata.clear()
        _capabilities.clear()
    reset_audit_signer()
