"""The seam between the core and the optional modules.

Core code (``backend/``) never imports the ``modules`` package.  Where the core
needs behaviour that only a module provides, it calls through a hook defined
here.  Every hook ships a core default that is a no-op or a null
implementation, so a build with no ``modules`` package -- the core profile --
behaves exactly as the open-source product is meant to;
:mod:`backend.app.modules_loader` installs the module implementations at
start-up when the ``modules`` package is importable (the full profile).

Hooks
-----
``audit_signer``
    Signs :class:`ComplianceAuditEvent` rows.  Core default writes no signature.
``register_router`` / ``apply_routers``
    Extra API routers to mount on the v1 router.
``register_model_module`` / ``import_registered_models``
    Extra SQLAlchemy model modules to import so their tables join
    ``Base.metadata``.
``register_tags`` / ``extra_tags_metadata``
    Extra OpenAPI tag metadata.
``register_capability`` / ``get_capability``
    Named implementations a core call site asks for by key -- the body of a
    route whose URL exists in every profile, or a service class a scheduler
    prefers when it is installed.  ``get_capability`` returns ``None`` for
    anything nobody registered, and the caller answers that with an explicit
    refusal (HTTP 501) or a fallback, never with silence.  The keys are the
    contract; ``core/optional_modules.py`` names them.
``register_modules`` / ``installed_modules``
    The names of the modules the registration provides, validated against
    :data:`KNOWN_MODULES`.  ``GET /api/v1/modules`` reports them and the
    dashboard decides what to render from the same list.

There is deliberately no ``register_scheduler``: all five schedulers started in
``main.py``'s lifespan are core, and no module needs one today
(established when the boundary was mapped before the move).  Add it when P5's PHI purge job
actually needs it, not before.
"""

from __future__ import annotations

import importlib
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "KNOWN_MODULES",
    "AuditSigner",
    "NullAuditSigner",
    "apply_routers",
    "audit_signer",
    "capability_names",
    "extra_tags_metadata",
    "get_capability",
    "import_registered_models",
    "installed_modules",
    "register_capability",
    "register_model_module",
    "register_modules",
    "register_router",
    "register_tags",
    "reset",
    "reset_audit_signer",
    "set_audit_signer",
]

#: The module names a registration may claim -- one per group in
#: ``modules-manifest.txt``, in the same order.  This tuple is the contract
#: between three places that have no other way to agree:
#:
#: * ``modules.register(hooks)``, which passes the names it provides to
#:   :func:`register_modules`,
#: * ``GET /api/v1/modules``, which reports :func:`installed_modules`,
#: * ``frontend/src/services/modules.ts``'s ``MODULES``, which the dashboard
#:   passes to ``useModule()`` to decide what chrome to render.
#:
#: A typo in any of them is silent -- the dashboard simply hides a tab the
#: deployment has.  :func:`register_modules` rejects an unknown name, and
#: ``backend/tests/unit/core/test_module_names.py`` pins the dashboard's copy
#: against this one.
KNOWN_MODULES: Tuple[str, ...] = (
    "workspaces",
    "hipaa",
    "compliance",
    "sso",
    "rbac",
    "warehouse",
    "integrations",
    "counters",
    "etl",
    "split_url",
)


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
    """Core default: audit events are recorded, but not signed.

    Tamper-evidence (HMAC-SHA256, EP-033) is the ``compliance`` module's.
    Writing ``None`` is safe on the hot path because
    ``compliance_audit_events.hmac_signature`` is nullable in both the model
    (``models/compliance_audit_event.py:90``) and the migration that created it
    (``ep033_add_compliance_audit_events.py:97``) — the six core call sites that
    log on every experiment and feature-flag mutation keep working unchanged.

    ``verify`` reports True for an unsigned row: absence of a signature is the
    documented core state, not evidence of tampering.  A row that *does* carry a
    signature cannot be checked without the key, so it is reported as unverified.
    """

    name = "null"

    def sign(self, event: Any) -> Optional[str]:
        return None

    def verify(self, event: Any) -> bool:
        return getattr(event, "hmac_signature", None) is None


#: The active signer.  Look this up through the module (``hooks.audit_signer``)
#: rather than importing the name, so that :func:`set_audit_signer` is visible
#: to callers that were imported before the modules loader ran.
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
    """Restore the core default (used by tests)."""
    set_audit_signer(_DEFAULT_AUDIT_SIGNER)


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

_lock = threading.RLock()
_router_registrars: List[Callable[[Any], None]] = []
_model_modules: List[str] = []
_tags_metadata: List[Dict[str, Any]] = []
_capabilities: Dict[str, Any] = {}
_installed_modules: List[str] = []


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

    A registrar is module code and may raise.  This function does not catch
    that -- the seam is a registry, and what a failure *means* belongs to the
    loader -- so the API build calls it through
    ``modules_loader.mount_module_routers``, which runs it against a staging
    router inside the loader's guard.  Calling it directly from a router build
    is what once turned a missing ``public_router`` into an AttributeError out
    of ``import backend.app.api.api`` and a process that never bound a port.
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


def register_modules(names: Sequence[str]) -> None:
    """Record the modules the registration provides.

    Every name must be one of :data:`KNOWN_MODULES`; an unknown one is a
    ``ValueError`` raised while the registration runs, so a typo is a
    start-up failure the loader reports rather than a module the dashboard
    never shows.  Registering a name twice is a no-op.
    """
    unknown = [name for name in names if name not in KNOWN_MODULES]
    if unknown:
        raise ValueError(
            f"unknown module name(s) {unknown!r}; add them to KNOWN_MODULES (and "
            f"to frontend/src/services/modules.ts) first. Known: "
            f"{', '.join(KNOWN_MODULES)}"
        )
    with _lock:
        for name in names:
            if name not in _installed_modules:
                _installed_modules.append(name)


def installed_modules() -> Tuple[str, ...]:
    """The module names registered so far, in :data:`KNOWN_MODULES` order."""
    with _lock:
        return tuple(name for name in KNOWN_MODULES if name in _installed_modules)


def reset() -> None:
    """Clear every registry and restore the core signer (tests only)."""
    with _lock:
        _router_registrars.clear()
        _model_modules.clear()
        _tags_metadata.clear()
        _capabilities.clear()
        _installed_modules.clear()
    reset_audit_signer()
