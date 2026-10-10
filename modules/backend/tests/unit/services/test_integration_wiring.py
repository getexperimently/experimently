"""The integration pages say nothing in the platform calls Jira, Salesforce or GitHub.

`docs/api/integrations.md`, `docs/integrations/github.md`,
`docs/integrations/salesforce.md` and the FAQ say so, and that an authenticated
webhook delivery changes nothing in the platform. Both are true of the code:

* the Jira, Salesforce and GitHub service classes have methods that would call
  the service (create an issue, update an opportunity, sync an experiment, ...),
  but nothing outside their own package refers to any of them: not a call, not
  a method passed on to run later (``add_task(service.sync_experiment, ...)``),
  not a name looked up with ``getattr``. The API, the modules and both Lambda
  trees are read. The webhook routes use only ``from_config``, a secret check
  and ``parse_webhook_event``, which reads the body and returns a dict that
  nothing keeps;
* nothing the three webhook handlers run, their helpers and the service
  methods they reach included, adds, changes or deletes a database row.

This test holds both, so the day a call is wired it fails, and the pages (and
the sentences ``backend/tests/unit/docs/test_integrations_docs_claims.py``
allows) change with it. Each check is also run against planted code of every
shape it looks for, so a scanner that has stopped seeing one fails here instead
of passing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import pytest

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[5]
SERVICES = REPO_ROOT / "modules" / "backend" / "app" / "services" / "integrations"
SERVICE_FILES = ("jira_service.py", "salesforce_service.py", "github_service.py")
ENDPOINTS = REPO_ROOT.joinpath(
    "modules", "backend", "app", "api", "v1", "endpoints", "integrations.py"
)
#: Everything that could call a service: the API, the modules and both Lambda
#: trees.
CODE_TREES = (
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "modules" / "backend" / "app",
    REPO_ROOT / "backend" / "lambda",
    REPO_ROOT / "modules" / "lambda",
)
WEBHOOK_HANDLERS = ("jira_webhook", "salesforce_webhook", "github_webhook")

#: The service methods application code may use: building the client,
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

#: Session methods that write a row, and the names a session goes by. A
#: parameter annotated ``Session`` is a session whatever its name.
WRITES = {
    "add",
    "add_all",
    "commit",
    "delete",
    "merge",
    "flush",
    "execute",
    "bulk_save_objects",
}
SESSION_NAMES = {"db", "session"}


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


def outbound_references(source: str, methods: Set[str]) -> List[str]:
    """Every reference in *source* to a method in *methods*.

    An attribute of that name, called or not (``s.sync_experiment(...)``,
    ``add_task(s.sync_experiment, ...)``), and a string that is the name
    (``getattr(s, "sync_experiment")``).
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in methods:
            found.append(f"line {node.lineno}: .{node.attr}")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in methods
        ):
            found.append(f"line {node.lineno}: {node.value!r}")
    return found


def code_sources() -> Iterable[Path]:
    """Every source file of ``CODE_TREES`` outside the integration services."""
    for tree in CODE_TREES:
        for path in sorted(tree.rglob("*.py")):
            if SERVICES not in path.parents:
                yield path


Function = ast.FunctionDef | ast.AsyncFunctionDef


def _functions(label: str, tree: ast.Module) -> Dict[str, List[tuple]]:
    """Module-level functions and class methods of *tree*, by name."""
    index: Dict[str, List[tuple]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            index.setdefault(node.name, []).append((f"{label}:{node.name}", node))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    index.setdefault(item.name, []).append(
                        (f"{label}:{node.name}.{item.name}", item)
                    )
    return index


def _sessions(fn: Function) -> Set[str]:
    names = set(SESSION_NAMES)
    args = fn.args
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        if arg.annotation is not None and "Session" in ast.unparse(arg.annotation):
            names.add(arg.arg)
    return names


def _is_session(node: ast.AST, names: Set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names
    return isinstance(node, ast.Attribute) and node.attr in SESSION_NAMES


def _reach(sources: Dict[str, str]) -> Tuple[List[str], Set[str]]:
    """Every session write the webhook handlers in *sources* can reach.

    *sources* maps a label to a module's text. From each handler, every name
    and attribute that is a function or method of one of those modules is
    followed (a helper called or passed on, ``service.parse_webhook_event``,
    ``webhook_auth.verify_webhook``), and every function reached is searched
    for a write on a session: ``db.add``, ``self.session.commit``, a
    ``Session``-annotated parameter's ``merge``, called or passed on.
    """
    index: Dict[str, List[tuple]] = {}
    for label, source in sources.items():
        for name, entries in _functions(label, ast.parse(source)).items():
            index.setdefault(name, []).extend(entries)
    queue = [entry for name in WEBHOOK_HANDLERS for entry in index.get(name, [])]
    assert queue, "no webhook handler found: the search is broken, not clean"
    seen: Set[str] = set()
    found: List[str] = []
    while queue:
        label, fn = queue.pop()
        if label in seen:
            continue
        seen.add(label)
        sessions = _sessions(fn)
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Attribute)
                and node.attr in WRITES
                and _is_session(node.value, sessions)
            ):
                found.append(f"{label}: .{node.attr}")
            name = (
                node.id
                if isinstance(node, ast.Name)
                else node.attr
                if isinstance(node, ast.Attribute)
                else None
            )
            if name in index:
                queue.extend(index[name])
    return sorted(set(found)), seen


def handler_writes(sources: Dict[str, str]) -> List[str]:
    """The session writes of :func:`_reach`."""
    return _reach(sources)[0]


def _real_sources() -> Dict[str, str]:
    paths = {
        "integrations.py": ENDPOINTS,
        "webhook_auth.py": SERVICES / "webhook_auth.py",
        **{name: SERVICES / name for name in SERVICE_FILES},
    }
    return {label: path.read_text(encoding="utf-8") for label, path in paths.items()}


def test_the_services_have_outbound_methods_to_look_for():
    methods = outbound_methods()
    for expected in ("create_issue", "sync_experiment", "create_experiment_issue"):
        assert expected in methods, f"{expected} is no longer a service method"


def test_nothing_calls_jira_salesforce_or_github():
    methods = outbound_methods()
    sources = list(code_sources())
    assert ENDPOINTS in sources
    for tree in CODE_TREES:
        assert any(tree in path.parents for path in sources), f"nothing read in {tree}"
    hits = []
    for path in sources:
        for hit in outbound_references(path.read_text(encoding="utf-8"), methods):
            hits.append(f"{path.relative_to(REPO_ROOT)}: {hit}")
    assert not hits, (
        "an outbound integration call is wired; the integration pages say none is:\n"
        + "\n".join(hits)
    )


def test_a_webhook_delivery_writes_no_row():
    found = handler_writes(_real_sources())
    assert not found, (
        "a webhook handler can write to the database; the integration pages say a"
        " delivery changes nothing:\n" + "\n".join(found)
    )


def test_the_search_reaches_the_helpers_and_the_services():
    """The real handlers reach their helpers and the service methods they use."""
    _found, reached = _reach(_real_sources())
    for label in (
        "integrations.py:_active_config",
        "integrations.py:_decode",
        "integrations.py:_parse_authenticated",
        "webhook_auth.py:verify_webhook",
        "webhook_auth.py:verify_signature",
        "jira_service.py:JiraService.from_config",
        "salesforce_service.py:SalesforceService.parse_webhook_event",
        "github_service.py:GitHubService.parse_webhook_event",
    ):
        assert label in reached, f"{label} was not reached from the webhook handlers"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f(s):\n    s.sync_experiment(1, 'x')\n", ["line 2: .sync_experiment"]),
        (
            "def f(bt, s):\n    bt.add_task(s.sync_experiment, 1)\n",
            ["line 2: .sync_experiment"],
        ),
        (
            "def f(s):\n    getattr(s, 'create_issue')('t', 'b')\n",
            ["line 2: 'create_issue'"],
        ),
    ],
    ids=["call", "passed-on", "getattr"],
)
def test_a_planted_reference_is_seen(source, expected):
    assert outbound_references(source, outbound_methods()) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "async def github_webhook(request, db):\n    db.add(object())\n",
            ["m:github_webhook: .add"],
        ),
        (
            "async def jira_webhook(request, db):\n    return _decode(b'')\n"
            "def _decode(body):\n    db.add(body)\n    return {}\n",
            ["m:_decode: .add"],
        ),
        (
            "async def salesforce_webhook(request, bt):\n"
            "    bt.add_task(Service.record, 1)\n"
            "class Service:\n"
            "    def record(self, store: Session):\n        store.merge(1)\n",
            ["m:Service.record: .merge"],
        ),
        (
            "async def github_webhook(request):\n    _later(lambda s: s.parse(1))\n"
            "def _later(fn):\n    _SEEN.add(fn)\n",
            [],
        ),
    ],
    ids=["in-handler", "in-helper", "service-passed-on", "a-set-is-not-a-session"],
)
def test_a_planted_write_is_seen(source, expected):
    assert handler_writes({"m": source}) == expected
