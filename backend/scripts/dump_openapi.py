#!/usr/bin/env python3
"""
Dump the FastAPI application's OpenAPI document to a JSON file.

The frontend guard test ``frontend/src/tests/services/url-literals.test.ts``
checks every ``/api/v1/...`` literal in the dashboard against the paths (and
methods) in ``frontend/src/tests/fixtures/openapi.json``. Regenerate that
fixture whenever a route is added, moved or removed:

    source venv/bin/activate
    python -m backend.scripts.dump_openapi --profile full frontend/src/tests/fixtures/openapi.json
    # or, from ``frontend/``: npm run openapi:dump

``--profile full`` is not optional there: the guard test subtracts
``openapi.module-paths.json`` from this fixture for a core run, so a fixture
dumped from a core checkout would have the modules' paths removed twice.

By default only the parts the guard needs are written (``paths`` reduced to
``{method: {operationId, summary}}``), keeping the fixture small and stable.
Pass ``--full`` for the complete ``app.openapi()`` document.

``--profile`` picks the profile the document describes, whatever the checkout
contains.  ``core`` hides the ``modules`` package from the import system
before the application is imported, so the modules loader finds nothing and
the document is the core one -- the same document a tree with ``modules/``
deleted produces (``scripts/core_build.sh``).  ``full`` requires the modules'
registration to load and fails otherwise.  The two stable snapshots under
``docs/api/`` are written this way::

    python -m backend.scripts.dump_openapi --profile core --full docs/api/openapi-v1.stable.json
    python -m backend.scripts.dump_openapi --profile full --full docs/api/openapi-v1.full.json
    # or: make openapi (all three fixtures)

``backend/tests/smoke/test_openapi_snapshot.py`` regenerates both in a
subprocess and fails on any change to a stable path.
"""

from __future__ import annotations

import argparse
import importlib.abc
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# The app is imported for its routes only; never touch a real database or
# start background schedulers while generating the document.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("TESTING", "true")

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


class _HideModules(importlib.abc.MetaPathFinder):
    """Make ``import modules`` fail as if the package were not there.

    Raising ``ModuleNotFoundError`` with ``name="modules"`` from the finder is
    what a missing package looks like to ``backend.app.modules_loader`` --
    which then runs the core profile -- as opposed to a *broken* one, which
    it would report and refuse to build a schema from.
    """

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname == "modules" or fullname.startswith("modules."):
            raise ModuleNotFoundError(
                f"No module named {fullname!r} (hidden by --profile core)",
                name=fullname,
            )
        return None


def select_profile(profile: Optional[str]) -> None:
    """Prepare the import system for *profile*; must run before the app import."""
    if profile == "core":
        if "modules" in sys.modules or any(
            m.startswith("modules.") for m in sys.modules
        ):
            raise RuntimeError(
                "the modules package is already imported; --profile core must "
                "run in a fresh process"
            )
        sys.meta_path.insert(0, _HideModules())


def build_document(full: bool = False, profile: Optional[str] = None) -> Dict[str, Any]:
    """Return the OpenAPI document (complete, or reduced to paths and methods)."""
    select_profile(profile)
    from backend.app.main import app  # imported lazily so ``--help`` stays fast
    from backend.app.modules_loader import load_modules, modules_failure

    loaded = load_modules()
    failure = modules_failure()
    if profile == "core" and loaded:
        raise RuntimeError("--profile core, but the modules' registration loaded")
    if profile == "full" and not loaded:
        raise RuntimeError(
            "--profile full, but the modules' registration did not load: "
            + (failure or "no modules package on the path")
        )
    # A registration can succeed and its routers still fail to mount, which
    # leaves `loaded` True and a document with no module path in it (see
    # `modules_loader.mount_module_routers`).  Publishing that as the full
    # profile's API is exactly the silence this script exists to prevent.
    if profile == "full" and failure is not None:
        raise RuntimeError(
            "--profile full, but the modules did not install fully, so this "
            "document would be missing their routes: " + failure
        )

    spec = app.openapi()
    if full:
        return spec

    paths: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for path, operations in spec.get("paths", {}).items():
        paths[path] = {
            method: {
                "operationId": op.get("operationId"),
                "summary": op.get("summary"),
            }
            for method, op in operations.items()
            if method in HTTP_METHODS
        }

    info = spec.get("info", {})
    return {
        "openapi": spec.get("openapi"),
        "info": {"title": info.get("title"), "version": info.get("version")},
        "paths": paths,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "output",
        nargs="?",
        default="frontend/src/tests/fixtures/openapi.json",
        help="Destination file, or - for stdout (default: frontend/src/tests/fixtures/openapi.json)",
    )
    parser.add_argument(
        "--full", action="store_true", help="Write the complete OpenAPI document"
    )
    parser.add_argument(
        "--profile",
        choices=("core", "full"),
        default=None,
        help=(
            "core: hide the modules package so the document is the core one; "
            "full: require the modules' registration to load; "
            "default: whatever the checkout loads"
        ),
    )
    args = parser.parse_args(argv)

    document = build_document(full=args.full, profile=args.profile)
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"

    if args.output == "-":
        sys.stdout.write(text)
        return 0

    output = Path(args.output)
    if not output.is_absolute():
        output = PROJECT_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)

    profile = f" ({args.profile})" if args.profile else ""
    shown = (
        output.relative_to(PROJECT_ROOT)
        if output.is_relative_to(PROJECT_ROOT)
        else output
    )
    print(f"Wrote {len(document['paths'])} paths{profile} to {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
