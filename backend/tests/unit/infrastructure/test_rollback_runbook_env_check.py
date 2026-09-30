"""The runbook's "does this revision migrate on start?" command answers (#298).

``docs/deployment/rollback-runbook.md`` tells an operator to check a rollback
target with ``aws ecs describe-task-definition --query ... --output text`` and
says what it prints. Its first version projected over the container list and
filtered again, which yields a list of lists: the JMESPath evaluated to ``[]``
whether ``RUN_MIGRATIONS=false`` was there or not, so ``--output text`` printed
nothing in both cases and the prose ("It prints `false`") was never true.

This takes the ``--query`` out of the runbook's own fence and evaluates it with
``jmespath`` -- the library the AWS CLI evaluates ``--query`` with -- against
describe-task-definition responses with and without the variable, and checks
the prose names what the operator sees in each case. The CLI's text output
prints a missing value (``null``) as ``None``; that part is the CLI's, and the
prose is pinned to say it.
"""

from __future__ import annotations

import re
from pathlib import Path

import jmespath
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNBOOK = REPO_ROOT / "docs" / "deployment" / "rollback-runbook.md"
HEADING = "### The rolled-back API runs against the current schema"

pytestmark = pytest.mark.skipif(
    not RUNBOOK.is_file(), reason="this tree has no docs/deployment"
)


def _section() -> str:
    text = RUNBOOK.read_text()
    start = text.index(HEADING + "\n")
    end = min(
        i
        for i in (text.find("\n## ", start + 1), text.find("\n### ", start + 1))
        if i >= 0
    )
    return text[start:end]


def _query() -> str:
    """The ``--query`` of the one describe-task-definition fence in the section."""
    fences = re.findall(r"```bash\n(.*?)```", _section(), flags=re.DOTALL)
    commands = [f for f in fences if "describe-task-definition" in f]
    assert len(commands) == 1, (
        f"expected one describe-task-definition fence, got {commands}"
    )
    (query,) = re.findall(r'--query "([^"]+)"', commands[0])
    assert "--output text" in commands[0]
    return query


def _response(environment: list[dict] | None) -> dict:
    backend = {"name": "backend", "image": "repo@sha256:0"}
    if environment is not None:
        backend["environment"] = environment
    return {
        "taskDefinition": {
            "family": "experimentation-backend-staging",
            "revision": 7,
            "containerDefinitions": [
                # Another container first: the filter must pick `backend`, not [0].
                {
                    "name": "log-router",
                    "environment": [{"name": "RUN_MIGRATIONS", "value": "true"}],
                },
                backend,
            ],
        }
    }


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        (
            [
                {"name": "APP_ENV", "value": "staging"},
                {"name": "RUN_MIGRATIONS", "value": "false"},
                {"name": "SEED", "value": ""},
            ],
            "false",
        ),
        ([{"name": "RUN_MIGRATIONS", "value": "true"}], "true"),
        ([{"name": "APP_ENV", "value": "staging"}], None),
        (None, None),
    ],
    ids=["set-false", "set-true", "absent", "no-environment"],
)
def test_the_runbook_query_returns_the_backend_containers_value(environment, expected):
    assert jmespath.search(_query(), _response(environment)) == expected


@pytest.mark.unit
@pytest.mark.regression
def test_the_prose_names_what_the_operator_sees():
    flat = " ".join(_section().split())
    assert "It prints `false` for a revision that does not migrate on start." in flat
    assert "prints `None`" in flat
    assert "prints `true`" in flat
