#!/usr/bin/env python3
"""
Dump the FastAPI application's OpenAPI document to a JSON file.

The frontend guard test ``frontend/src/tests/services/url-literals.test.ts``
checks every ``/api/v1/...`` literal in the dashboard against the paths (and
methods) in ``frontend/src/tests/fixtures/openapi.json``. Regenerate that
fixture whenever a route is added, moved or removed:

    source venv/bin/activate
    python -m backend.scripts.dump_openapi frontend/src/tests/fixtures/openapi.json
    # or, from ``frontend/``: npm run openapi:dump

By default only the parts the guard needs are written (``paths`` reduced to
``{method: {operationId, summary}}``), keeping the fixture small and stable.
Pass ``--full`` for the complete ``app.openapi()`` document.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# The app is imported for its routes only; never touch a real database or
# start background schedulers while generating the document.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("TESTING", "true")

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


def build_document(full: bool = False) -> Dict[str, Any]:
    """Return the OpenAPI document (complete, or reduced to paths and methods)."""
    from backend.app.main import app  # imported lazily so ``--help`` stays fast

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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "output",
        nargs="?",
        default="frontend/src/tests/fixtures/openapi.json",
        help="Destination file (default: frontend/src/tests/fixtures/openapi.json)",
    )
    parser.add_argument("--full", action="store_true", help="Write the complete OpenAPI document")
    args = parser.parse_args(argv)

    document = build_document(full=args.full)

    output = Path(args.output)
    if not output.is_absolute():
        output = PROJECT_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")

    print(f"Wrote {len(document['paths'])} paths to {output.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
