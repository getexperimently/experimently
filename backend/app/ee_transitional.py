"""
TRANSITIONAL -- the Enterprise registration entry point, while the Enterprise
modules still live in this tree.

This file has exactly the shape ``ee/backend/app/register.py`` will have after
the physical move (issue #89): one ``register(hooks)`` that installs the audit
signer, the routers, the model modules, the OpenAPI tags and the capabilities.
The only difference is where its imports point.  ``ee_loader.load_enterprise()``
falls back to it when the ``ee`` package exposes no ``register`` -- which is
the state of this tree, where ``ee/`` holds a LICENSE and nothing else.

It exists so that the three places that consume the seam agree *today*:

* ``db/bootstrap.py`` on a fresh database creates the Enterprise tables that
  the still-mounted Enterprise routers need (without this, ``make dev`` on an
  empty database served ``/api/v1/workspaces`` against no ``workspaces``
  table);
* every real process signs compliance audit events, not only the test suite
  (``hooks.audit_signer`` was the null signer everywhere except ``conftest``);
* every Enterprise route is behind ``require_feature`` and every Enterprise
  capability behind ``check_feature``, so the dashboard's feature gating and
  the API's refusals describe the same edition.

It is listed in ``ee-manifest.txt`` and deleted whole with everything it names.
A Community build therefore has neither ``ee.register`` nor this module, and
``load_enterprise()`` reports Community edition.

Nothing outside ``ee_loader`` may import this module.
"""

from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Callable

from backend.app.core.license import (
    READ_METHODS,
    check_feature,
    current_license_state,
    require_feature,
)

logger = logging.getLogger(__name__)

#: SQLAlchemy model modules whose tables belong to the Enterprise edition.
#: Kept in step with the EE TABLES section of ``ee-manifest.txt``.
ENTERPRISE_MODEL_MODULES: tuple[str, ...] = (
    "backend.app.models.baa_config",
    "backend.app.models.custom_role",
    "backend.app.models.integration_config",
    "backend.app.models.phi_audit_log",
    "backend.app.models.sso_config",
    "backend.app.models.warehouse_connection",
    "backend.app.models.workspace",
)

ENTERPRISE_TAGS: list[dict[str, str]] = [
    {
        "name": "RBAC",
        "description": "Operations for managing custom roles, permission delegation, and effective permission resolution",
    },
    {
        "name": "Real-time Counters",
        "description": "Real-time DynamoDB atomic counters for experiment assignments, events, and conversions",
    },
    {
        "name": "ETL",
        "description": "Operations for managing AWS Glue ETL jobs, Athena queries, S3 partitions, and Glue crawlers",
    },
    {
        "name": "Warehouse",
        "description": (
            "Warehouse-Native Analytics: manage Snowflake, BigQuery, and Redshift "
            "connections, generate experiment analysis SQL, and sync results directly "
            "from customer data warehouses. Credentials stored encrypted."
        ),
    },
    {
        "name": "Integrations",
        "description": "Jira, Salesforce and GitHub integration configuration and webhooks",
    },
    {
        "name": "SSO",
        "description": "SAML 2.0 and OIDC single sign-on with just-in-time provisioning",
    },
    {
        "name": "Workspaces",
        "description": (
            "EP-057: Multi-Tenant Team Workspaces — create isolated project namespaces, "
            "manage team memberships with role-based access (OWNER/ADMIN/DEVELOPER/ANALYST/VIEWER), "
            "send and accept email invites, and issue scoped workspace API keys."
        ),
    },
    {
        "name": "HIPAA",
        "description": (
            "EP-050: HIPAA Compliance — PHI audit logging, Business Associate Agreement (BAA) "
            "management, PHI field encryption/decryption, data residency validation, "
            "and HIPAA readiness status reporting. All endpoints require ADMIN role."
        ),
    },
]


#: Enterprise routes that are reads despite being ``POST``: a query against a
#: warehouse, a connection test, an Athena ``SELECT``, decrypting a PHI field
#: to read it.  The read-only window exists so a customer whose licence has
#: lapsed can still *read their data*; classifying by verb alone would let
#: them list their warehouse connections and refuse them every metric.
#: Matched as path suffixes under the router's prefix.
READ_POST_SUFFIXES: dict[str, tuple[str, ...]] = {
    "warehouse": ("/query", "/test-connection", "/connections/test"),
    "etl": ("/query",),
    "hipaa": ("/decrypt",),
}


def _write_predicate(feature: str) -> Callable[[Any], bool]:
    """Is this request a write, for the ``expired`` read-only window?"""
    read_posts = READ_POST_SUFFIXES.get(feature, ())

    def is_write(request: Any) -> bool:
        if request.method.upper() in READ_METHODS:
            return False
        return not request.url.path.endswith(read_posts)

    return is_write


def _authenticated_then_gated(feature: str) -> list:
    """``dependencies=`` for an Enterprise router whose every route needs a user.

    Authentication first, then the licence: an anonymous request gets the 401
    it always got, not a 403 that names the feature and the licence state --
    which would let an unauthenticated probe enumerate what is installed.
    Dependencies resolve in order, and the user dependency is cached per
    request, so the route's own ``get_current_active_user`` does not run twice.
    """
    from fastapi import Depends

    from backend.app.api import deps

    return [
        Depends(deps.get_current_active_user),
        Depends(require_feature(feature, write=_write_predicate(feature))),
    ]


def _gated_only(
    feature: str, *, write: bool | Callable[[Any], bool] | None = None
) -> list:
    """``dependencies=`` for routes that are public by design (webhooks, the
    SSO login flow, the invite preview): the licence gate alone."""
    from fastapi import Depends

    if write is None:
        write = _write_predicate(feature)
    return [Depends(require_feature(feature, write=write))]


def mount_routers(router: Any) -> None:
    """Mount every Enterprise router on the v1 router, each behind its feature.

    Routers whose every route needs a user are mounted behind authentication
    and then the gate.  The three modules that also serve public routes --
    inbound webhooks, the SSO login flow, the invite preview -- expose them on
    a separate ``public_router`` that is mounted behind the gate only.  The
    SSO login flow is mounted read-only: signing in is not a data write in
    the licence sense, and refusing it in the read-only window would lock
    every SSO-only user out of the reads that window exists to allow.
    """
    modules = _endpoint_modules()
    etl = modules["etl"]
    hipaa = modules["hipaa"]
    integrations = modules["integrations"]
    rbac = modules["rbac"]
    realtime_counters = modules["realtime_counters"]
    sso = modules["sso"]
    warehouse = modules["warehouse"]
    warehouse_clickhouse = modules["warehouse_clickhouse"]
    warehouse_databricks = modules["warehouse_databricks"]
    warehouse_mysql = modules["warehouse_mysql"]
    workspaces = modules["workspaces"]

    # P2-A: RBAC Post-MVP Enhancements
    router.include_router(
        rbac.router,
        prefix="/rbac",
        tags=["RBAC"],
        dependencies=_authenticated_then_gated("rbac"),
    )
    # P2-B: Real-time Counters in DynamoDB
    router.include_router(
        realtime_counters.router,
        prefix="/counters",
        tags=["Real-time Counters"],
        dependencies=_authenticated_then_gated("counters"),
    )
    # P3-A: ETL & Glue Jobs for S3 Data Lake
    router.include_router(
        etl.router,
        prefix="/etl",
        tags=["ETL"],
        dependencies=_authenticated_then_gated("etl"),
    )
    # Issue #26 / EP-041 / EP-048: warehouse-native analytics and its connectors
    for module, prefix in (
        (warehouse, "/warehouse"),
        (warehouse_databricks, "/warehouse/databricks"),
        (warehouse_clickhouse, "/warehouse/clickhouse"),
        (warehouse_mysql, "/warehouse/mysql"),
    ):
        router.include_router(
            module.router,
            prefix=prefix,
            tags=["Warehouse"],
            dependencies=_authenticated_then_gated("warehouse"),
        )
    # EP-034: Integration Config Management (Salesforce / Jira / GitHub)
    router.include_router(
        integrations.router,
        prefix="/integrations",
        tags=["Integrations"],
        dependencies=_authenticated_then_gated("integrations"),
    )
    # The inbound webhooks read the integration's config and parse the event;
    # they persist nothing today, so they are reads for the read-only window:
    # refusing them would only make Jira, Salesforce and GitHub record a month
    # of failed deliveries (and possibly disable the hook) for no data gained.
    router.include_router(
        integrations.public_router,
        prefix="/integrations",
        tags=["Integrations"],
        dependencies=_gated_only("integrations", write=False),
    )
    # EP-037: SSO/SAML & OIDC Enterprise Authentication
    router.include_router(
        sso.router,
        prefix="/auth/sso",
        tags=["SSO"],
        dependencies=_authenticated_then_gated("sso"),
    )
    router.include_router(
        sso.public_router,
        prefix="/auth/sso",
        tags=["SSO"],
        dependencies=_gated_only("sso", write=False),
    )
    # EP-057: Multi-Tenant Team Workspaces
    router.include_router(
        workspaces.router,
        prefix="/workspaces",
        tags=["Workspaces"],
        dependencies=_authenticated_then_gated("workspaces"),
    )
    router.include_router(
        workspaces.public_router,
        prefix="/workspaces",
        tags=["Workspaces"],
        dependencies=_gated_only("workspaces"),
    )
    # EP-050: HIPAA Compliance
    router.include_router(
        hipaa.router,
        prefix="/hipaa",
        tags=["HIPAA"],
        dependencies=_authenticated_then_gated("hipaa"),
    )


def licensed(
    feature: str, implementation: Callable[..., Any], *, write: bool = True
) -> Callable[..., Any]:
    """Wrap a capability so that calling it checks the licence first.

    The *route* that reaches a capability is Community -- its URL exists in
    every edition and answers 501 when nothing is registered -- so the licence
    check has to travel with the implementation.  A refused call raises the
    same 403 as ``require_feature``.
    """
    if inspect.iscoroutinefunction(implementation):

        @functools.wraps(implementation)
        async def _async_guard(*args: Any, **kwargs: Any) -> Any:
            check_feature(feature, write=write)
            return await implementation(*args, **kwargs)

        return _async_guard

    @functools.wraps(implementation)
    def _guard(*args: Any, **kwargs: Any) -> Any:
        check_feature(feature, write=write)
        return implementation(*args, **kwargs)

    return _guard


#: The Enterprise endpoint modules, by name under ``backend.app.api.v1.endpoints``.
ENTERPRISE_ENDPOINT_MODULES: tuple[str, ...] = (
    "etl",
    "hipaa",
    "integrations",
    "rbac",
    "realtime_counters",
    "sso",
    "warehouse",
    "warehouse_clickhouse",
    "warehouse_databricks",
    "warehouse_mysql",
    "workspaces",
)


def _endpoint_modules() -> dict[str, Any]:
    """Import (or fetch, once imported) every Enterprise endpoint module."""
    import importlib

    return {
        name: importlib.import_module(f"backend.app.api.v1.endpoints.{name}")
        for name in ENTERPRISE_ENDPOINT_MODULES
    }


def _import_endpoint_modules() -> None:
    """Import every Enterprise endpoint module now, under the loader's guard.

    ``mount_routers`` runs later, from ``hooks.apply_routers`` inside the
    router build, *outside* the loader's try/except.  An endpoint module that
    fails to import there would take the whole API down after "Enterprise
    edition loaded" had already been logged; importing here means the failure
    is caught by the loader, the registration is rolled back, and the process
    starts as Community.
    """
    _endpoint_modules()


def register(hooks: Any) -> None:
    """Install the Enterprise edition into *hooks*.  Idempotent.

    Models first, then everything that needs the API graph: the schema
    builders (bootstrap, alembic, the test conftest) call this too, and the
    seven model modules are cheap and self-contained, while the endpoint
    modules pull in the whole service layer.  Ordering them this way keeps the
    part a schema tool needs ahead of the part most likely to fail on an
    endpoint-only dependency.
    """
    for module_path in ENTERPRISE_MODEL_MODULES:
        hooks.register_model_module(module_path)

    _import_endpoint_modules()

    from backend.app.api.v1.endpoints.compliance_reports import (
        export_audit_events,
        generate_compliance_report,
    )
    from backend.app.api.v1.endpoints.experiments_split_url import (
        preview_split_url_assignment,
    )
    from backend.app.services.audit_signing_service import AuditSigningService
    from backend.app.services.split_url_service import get_url_variant

    # Tamper-evidence for compliance audit events (EP-033).
    hooks.set_audit_signer(AuditSigningService())

    hooks.register_router(mount_routers)
    hooks.register_tags(ENTERPRISE_TAGS)

    # Capabilities: the keys are the contract with core/enterprise_features.py.
    # Route bodies are wrapped so a call checks the licence; availability
    # probes are *providers* that answer None when unlicensed, because the
    # Community caller only ever asks "is this here?" and has its own fallback.
    def routing_provider() -> Callable[..., Any] | None:
        # Asked when a split-URL experiment is about to be *stored*, which is
        # a write: in the read-only window the answer is None and the
        # Community route refuses, the same as every other Enterprise write.
        if current_license_state().allows("split_url", write=True):
            return get_url_variant
        return None

    hooks.register_capability("split_url.routing", routing_provider)
    hooks.register_capability(
        "split_url.preview",
        licensed("split_url", preview_split_url_assignment, write=False),
    )
    hooks.register_capability(
        "compliance.report",
        licensed("compliance", generate_compliance_report, write=False),
    )
    hooks.register_capability(
        "compliance.export", licensed("compliance", export_audit_events, write=False)
    )

    # A *provider*, not the class: the bandit scheduler runs for days and the
    # licence can lapse under it, so the decision is made at each call rather
    # than once at registration.  Unlicensed answers None and the scheduler
    # falls through to PostgreSQL, which is the documented degraded state.
    def counter_service_provider() -> type | None:
        # Reading counters for bandit statistics is a read, so the read-only
        # window keeps the DynamoDB source; only past it does the scheduler
        # fall through to PostgreSQL.
        if not current_license_state().allows("counters", write=False):
            return None
        # Resolved at each call rather than captured at registration, so the
        # class is whatever the service module holds *now* -- which is also
        # what lets a test patch it at its definition site.
        from backend.app.services import dynamodb_counter_service

        return dynamodb_counter_service.DynamoDBCounterService

    hooks.register_capability("counters.service", counter_service_provider)
    logger.debug("Enterprise edition registered from the transitional in-tree module")
