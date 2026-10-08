"""The integration pages say nothing in the platform calls Jira, Salesforce or GitHub.

`docs/api/integrations.md`, `docs/integrations/github.md`,
`docs/integrations/salesforce.md` and the FAQ say so, and that an authenticated
webhook delivery changes nothing in the platform. Both are true of the code:

* the Jira, Salesforce and GitHub service classes have methods that would call
  the service (create an issue, update an opportunity, sync an experiment, ...),
  but no application code outside their own package calls any of them. The
  webhook routes call only ``from_config``, a secret check and
  ``parse_webhook_event``, which reads the body and returns a dict that
  nothing keeps;
* the three webhook handlers never add, change or delete a database row.

This test holds both, so the day a call is wired it fails, and the pages (and
the phrases ``backend/tests/unit/docs/test_integrations_docs_claims.py``
requires) change with it. Each check is also run against a planted call, so a
scanner that has stopped seeing calls fails here instead of passing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, List, Set

import pytest

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[5]
SERVICES = REPO_ROOT / "modules" / "backend" / "app" / "services" / "integrations"
SERVICE_FILES = ("jira_service.py", "salesforce_service.py", "github_service.py")
ENDPOINTS = REPO_ROOT.joinpath(
    "modules", "backend", "app", "api", "v1", "endpoints", "integrations.py"
)
APP_TREES = (REPO_ROOT / "backend" / "app", REPO_ROOT / "modules" / "backend" / "app")
WEBHOOK_HANDLERS = ("jira_webhook", "salesforce_webhook", "github_webhook")

#: The service methods application code may call: building the client,
#: checking a webhook's secret and reading its body, none of which reaches the
#: service. Every other public method would call it. (The routes check the
#: secret with ``webhook_auth.verify_webhook``, which shares a name with the
#: services' own checks.)
ALLOWED = {
    "from_config",
    "parse_webhook_event",
    "verify_webhook",
    "verify_webhook_signature",
}

#: Session methods that write a row.
WRITES = {"add", "add_all", "commit", "delete", "merge", "flush", "bulk_save_objects"}


def outbound_methods() -> Set[str]:
    """The public methods of the three service classes, less ``ALLOWED``."""
    names: Set[str] = set()
    for name in SERVICE_FILES:
        tree = ast.parse((SERVICES / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Service"):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not item.name.startswith("_"):
                            names.add(item.name)
    return names - ALLOWED


def calls_to(source: str, methods: Set[str]) -> List[str]:
    """Every ``<expr>.<method>(...)`` in *source* whose method is in *methods*."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in methods
        ):
            found.append(f"line {node.lineno}: .{node.func.attr}(")
    return found


def app_sources() -> Iterable[Path]:
    """Every application source file outside the integration services package."""
    for tree in APP_TREES:
        for path in sorted(tree.rglob("*.py")):
            if SERVICES not in path.parents:
                yield path


def handler_writes(source: str) -> List[str]:
    """Every session write inside the three webhook handlers of *source*."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in WEBHOOK_HANDLERS
        ):
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in WRITES
                ):
                    found.append(f"{node.name}: .{call.func.attr}(")
    return found


def test_the_services_have_outbound_methods_to_look_for():
    methods = outbound_methods()
    for expected in ("create_issue", "sync_experiment", "create_experiment_issue"):
        assert expected in methods, f"{expected} is no longer a service method"


def test_no_application_code_calls_jira_salesforce_or_github():
    methods = outbound_methods()
    sources = list(app_sources())
    assert ENDPOINTS in sources
    hits = []
    for path in sources:
        for hit in calls_to(path.read_text(encoding="utf-8"), methods):
            hits.append(f"{path.relative_to(REPO_ROOT)}: {hit}")
    assert not hits, (
        "an outbound integration call is wired; the integration pages say none is:\n"
        + "\n".join(hits)
    )


def test_a_webhook_delivery_writes_no_row():
    found = handler_writes(ENDPOINTS.read_text(encoding="utf-8"))
    assert not found, (
        "a webhook handler writes to the database; the integration pages say a"
        " delivery changes nothing:\n" + "\n".join(found)
    )


def test_a_planted_call_and_a_planted_write_are_seen():
    planted_call = "def on_complete(service):\n    service.sync_experiment(1, 'x')\n"
    assert calls_to(planted_call, outbound_methods()) == ["line 2: .sync_experiment("]
    planted_write = (
        "async def github_webhook(request, db):\n"
        "    db.add(object())\n"
        "    db.commit()\n"
    )
    assert handler_writes(planted_write) == [
        "github_webhook: .add(",
        "github_webhook: .commit(",
    ]
