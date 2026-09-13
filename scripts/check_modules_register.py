#!/usr/bin/env python3
"""Assert that the optional modules register in *this* interpreter.

The dependency contract is not obvious and has broken twice.  Three files
describe overlapping Python environments:

* ``backend/requirements.txt`` -- what every CI job and every developer venv
  installs.  It is the superset: runtime plus test, lint and tooling pins.
* ``backend/requirements/runtime.txt`` (+ ``.lock``) -- the subset the core API
  image installs.
* ``modules/requirements.txt`` (+ ``.lock``) -- what the ``full`` image adds on
  top: python3-saml, authlib, the warehouse drivers.

The modules import a handful of packages *unguarded* (``defusedxml`` in
``sso_service``, deliberately -- an XXE-safe parser has no safe fallback), so a
full checkout whose environment came from ``backend/requirements.txt`` alone
must still be able to register them.  When that stopped being true the symptom
was not an error anyone could read: ``backend/tests/conftest.py`` called
``require_modules_or_absent()``, which raised during collection, and every
pytest job exited 3 having collected zero tests.  A developer could not
reproduce it either -- their venv has every package.

This check is that environment, stated once and asserted directly::

    python scripts/check_modules_register.py

It imports ``backend.app.main`` the way the server does (so the loader runs on
the real path, not a synthetic one), then requires that the registration
actually took: ``modules_failure()`` empty, every name in
``hooks.KNOWN_MODULES`` installed, a real audit signer in place of
``NullAuditSigner``, and -- last, because it is the only one of the four an
operator can observe -- a route mounted on ``backend.app.main.app`` for every
prefix in :data:`MODULE_ROUTE_PREFIXES`.

That last check is the point of the job.  The registries are filled by
``modules.register(hooks)``; *mounting* what they hold happens afterwards, in
``modules_loader.mount_module_routers``, and it can fail on its own (an
endpoint module with no ``public_router``, a router FastAPI refuses).  The
loader is built to survive that -- the core API keeps serving -- so nothing
downstream raises: ``modules_failure()`` is set, but ``abort_if_modules_broken``
only logs under ``APP_ENV=test``, which is what this script runs under, and
every registry still answers as if the modules were serving.  Only the route
table knows.

Exit status 0 when the modules registered, 1 otherwise.  A checkout with no
``modules/`` directory is also 1: this check exists to prove the *full*
profile stands up, and a core checkout cannot answer the question.
"""

from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import the application for its wiring only: no database, no schedulers.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("TESTING", "true")

#: One URL prefix per router ``modules.backend.app.register.mount_routers``
#: mounts.  A full-profile API that does not serve these is not serving the
#: modules, whatever ``hooks.installed_modules()`` says -- so this is checked
#: against the route table of the application object itself.  Keep it in step
#: with ``mount_routers``; a prefix that is dropped there and left here fails
#: this check, which is the right way round.
MODULE_ROUTE_PREFIXES: tuple[str, ...] = (
    "/api/v1/rbac",
    "/api/v1/counters",
    "/api/v1/etl",
    "/api/v1/warehouse",
    "/api/v1/integrations",
    "/api/v1/auth/sso",
    "/api/v1/workspaces",
    "/api/v1/hipaa",
)


def iter_route_paths(app: object):
    """Yield the path of every HTTP route *app* serves.

    FastAPI >= 0.141 does not flatten ``include_router`` into ``app.routes``:
    it keeps a lazy entry whose ``effective_route_contexts`` carry the fully
    prefixed paths.  Older versions expose plain routes with a ``.path``.
    Both shapes are handled, the same way
    ``backend/tests/smoke/test_wiring.py`` handles them.
    """
    for route in getattr(app, "routes", ()):
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            contexts = contexts() if callable(contexts) else contexts
            for context in contexts:
                path = getattr(context, "path", None)
                if path:
                    yield path
        else:
            path = getattr(route, "path", None)
            if path:
                yield path


def main() -> int:
    if not (REPO_ROOT / "modules").is_dir():
        print(
            "no modules/ directory: this check proves the FULL profile "
            "registers, so it needs a full checkout",
            file=sys.stderr,
        )
        return 1

    # Capture what the loader logs while the application is imported: the
    # success line is the one an operator greps for in a deployment.  The
    # handler goes on the module's own logger object rather than on
    # `logging.getLogger(name)` -- the test suite patches `getLogger`, and the
    # two are then not the same object, so the capture would come back empty.
    from backend.app import modules_loader

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    loader_log = modules_loader.logger
    loader_log.addHandler(handler)
    loader_log.setLevel(logging.INFO)
    # A `dictConfig(disable_existing_loggers=True)` anywhere earlier in the
    # process leaves this logger disabled; re-enable it for the duration
    # rather than silently capturing nothing.
    was_disabled, loader_log.disabled = loader_log.disabled, False

    try:
        # The real path first: main.py calls load_modules() and then
        # abort_if_modules_broken(), which exits the process on a broken
        # package -- exactly what a deployment would do.
        import backend.app.main as app_main

        # Read the recorded failure HERE, before anything can re-run the
        # loader.  `_load()` opens with `_failure = None`, so a forced
        # registration wipes whatever the import recorded -- and a mount
        # failure cannot be recorded a second time, because a forced
        # `load_modules()` re-runs `register()` and never re-runs
        # `mount_module_routers`.  Forcing first is how this check came to
        # exit 0 on a build serving no module route at all.
        failure = modules_loader.modules_failure()
        loaded = modules_loader.load_modules()

        # Something may have imported the application before this script did
        # (it is importable from a test), in which case the loader's result
        # line was emitted before the handler above existed.  Force one more
        # registration to get it -- but only from a clean state, so that the
        # failure just read is not erased.  The registries de-duplicate.
        if failure is None and "Modules loaded" not in stream.getvalue():
            loaded = modules_loader.load_modules(force=True)
            failure = modules_loader.modules_failure()
    # BaseException, not Exception: main.py's abort_if_modules_broken() raises
    # SystemExit on a broken package, and that is a result to report, not a
    # crash to propagate.
    except BaseException as exc:
        print(f"importing backend.app.main failed: {exc!r}", file=sys.stderr)
        return 1
    finally:
        loader_log.removeHandler(handler)
        loader_log.disabled = was_disabled

    from backend.app.core import hooks

    if failure:
        print(f"the modules package is present but did not load: {failure}")
        return 1

    if not loaded:
        print("load_modules() is False with no recorded failure")
        return 1

    installed = hooks.installed_modules()
    missing = [name for name in hooks.KNOWN_MODULES if name not in installed]
    if missing:
        print(f"registered, but these modules are missing: {missing}")
        return 1

    signer = type(hooks.audit_signer).__name__
    if signer == "NullAuditSigner":
        print(
            "the modules registered but the audit signer is NullAuditSigner: "
            "compliance events would be written with hmac_signature = NULL"
        )
        return 1

    logged = stream.getvalue()
    if "Modules loaded" not in logged:
        print(f"the loader never logged a successful load; it said: {logged!r}")
        return 1

    # The registries above are what the registration *claimed*; this is what
    # the process serves.  Checked on the application object the import built,
    # not on a router assembled here: mounting happens once, during that
    # import, and nothing re-runs it.
    paths = sorted(set(iter_route_paths(app_main.app)))
    unmounted = [
        prefix
        for prefix in MODULE_ROUTE_PREFIXES
        if not any(path.startswith(prefix) for path in paths)
    ]
    if unmounted:
        print(
            "the modules registered but the application serves no route under "
            f"{unmounted}: mounting them failed, so every module route 404s "
            "(see modules_loader.mount_module_routers)"
        )
        return 1

    print(f"modules registered: {', '.join(installed)}")
    print(f"audit signer: {signer}")
    print(f"module routes mounted: {len(MODULE_ROUTE_PREFIXES)} prefixes served")
    print(f"loader said: {logged.strip().splitlines()[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
