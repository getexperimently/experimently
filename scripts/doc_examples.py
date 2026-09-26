#!/usr/bin/env python3
"""The documentation's shell examples: tagged, counted, and rendered as code.

A document is *enrolled* in ``scripts/doc_examples.toml``.  In an enrolled
document every shell fence says whether it runs::

    ```{.bash exec}                      runs (timeout 120 s)
    ```{.bash exec timeout=1200}         runs, with its own timeout
    ```{.bash skip reason="..."}         does not run, and says why

and a block that runs may be followed, with no blank line, by the output the
page promises::

    <!-- expect: "healthy" -->

This file is the contract (docs/development/doc-examples.md explains it to
authors).  It checks, without running anything:

``--check``
    walks the repository for every in-scope Markdown page (the *universe*, which
    must equal ``[meta] universe`` exactly) and applies the rules to every page
    it finds: every fence names a language; no fence names a shell other than
    ``bash``; a page with a ``bash`` fence is exactly one of enrolled, exempt or
    pending.  In an enrolled document every shell fence is tagged in the one
    form superfences renders as code and GitHub shows cleanly; nothing a reader
    could not paste is in a block (a ``#`` comment breaks zsh, a masked
    ``$(...)`` hides a failure); every block passes ``bash -n``; a skip reason
    names a category; a block that runs installs nothing and reaches no AWS
    account; and the numbers of documents, run blocks, skipped blocks and
    expectations are exactly what the enrolment file says.  A *pending* page
    (the rollout; the list is frozen in this file and can only shrink) carries
    its residual counts of comments, unlabelled fences and ``bash -n`` failures,
    exactly, and each can only fall.  Every problem is reported in one run.

``--render SITE_DIR``
    after ``mkdocs build``: every enrolled page under ``docs/`` renders each of
    its fences as a code block, and no fence leaked into a paragraph.

``--run``
    runs each enrolled page's blocks, in order, in one ``bash`` session per page,
    under a compose project of the page's own, and checks each block exited 0 and
    printed its expectations.  Exit 0 all passed, 1 a page ran and failed, 2
    refused before running anything.  ``--shard PROFILE:K/N`` runs one shard of
    the plan (below) and ``--report FILE`` writes what it measured.

``--plan``
    the shards CI runs, as a GitHub Actions matrix: the pages that run, split by
    the image profile they need (``core``: ``bare`` and ``stack``; ``full``:
    ``stack-full``) and dealt, in path order, across as many shards as keep each
    one inside the budget (``PAGES_PER_SHARD``).  Computed from the enrolment,
    never listed by hand.

``--summarise DIR``
    after every shard: fails unless each page that runs appears in exactly one
    shard report, every block it has reached its end, and the blocks reached add
    up to ``[meta] exec``.  Zero reports is a failure.

Standard library only.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import html.parser
import json
import math
import os
import pathlib
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.request
from typing import Callable, Optional

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENROLMENT = ROOT / "scripts" / "doc_examples.toml"

SHELL = ("bash",)
# Shell-like languages the runner does not know.  A fence naming one of them is
# refused on every page the walk finds: it would render, and be pasted, while
# nothing checked it (a retag to ```zsh was how a block left the check).
OTHER_SHELLS = (
    "sh",
    "shell",
    "console",
    "zsh",
    "sh-session",
    "shell-session",
    "bash-session",
    "fish",
    "powershell",
    "ps1",
    "pwsh",
    "ksh",
    "csh",
    "tcsh",
    "bat",
    "batch",
    "cmd",
)
ENVIRONMENTS = ("bare", "stack", "stack-full", "local")
DEFAULT_TIMEOUT = 120
AUTHORING = "docs/development/doc-examples.md"

# The universe: every Markdown page under the repository root, found by a
# filesystem walk (no git: scripts/core_build.sh runs the unit tests in a copy
# with no .git).  Directories are pruned by NAME at any depth -- a root-prefix
# rule would count frontend/node_modules/**/README.md -- and so is every
# dot-directory except .github.  CLAUDE.md files and .claude/ are working
# instructions, not documentation (T1).
PRUNED_DIRS = ("node_modules", "venv", "site")
KEPT_DOT_DIRS = (".github",)

# Skip reasons begin with one of these, then ": " (``bug`` is ``bug #<n>: ``).
CATEGORIES = (
    "checkout",
    "dev",
    "server",
    "aws",
    "idp",
    "secret",
    "registry",
    "toolchain",
    "destructive",
    "demo",
    "fragment",
    "bug",
)

# The pages the rollout has not reached, frozen when the universe check landed.
# A page may leave this list (enrolled or exempted); none may join it, and its
# residual (comments, unlabelled fences, bash -n failures) may only fall below
# the numbers here.  The last enrolment batch deletes this and [pending].
PENDING_FROZEN: dict[str, tuple[int, int, int]] = {
    "CONTRIBUTING.md": (0, 2, 0),
    "README.md": (0, 0, 0),
    "backend/lambda/README.md": (0, 1, 0),
    "backend/lambda/event_processor/README.md": (5, 1, 0),
    "demo/DEMO_GUIDE.md": (5, 0, 0),
    "demo/shoplab/README.md": (12, 0, 0),
    "demo/streampulse/README.md": (15, 0, 0),
    "demo/streampulse/simulator/README.md": (4, 0, 0),
    "docs/api/README.md": (0, 0, 0),
    "docs/api/alerting.md": (0, 0, 0),
    "docs/api/audit-logging.md": (0, 1, 0),
    "docs/api/auth.md": (0, 0, 0),
    "docs/api/bayesian.md": (0, 1, 0),
    "docs/api/compliance.md": (2, 5, 0),
    "docs/api/cuped.md": (0, 1, 0),
    "docs/api/data-export.md": (7, 2, 0),
    "docs/api/dimensional-analysis.md": (0, 1, 0),
    "docs/api/endpoints.md": (24, 24, 1),
    "docs/api/integrations.md": (0, 8, 0),
    "docs/api/interaction-detection.md": (0, 1, 0),
    "docs/api/multi-armed-bandit.md": (0, 0, 0),
    "docs/api/mutual-exclusion-groups.md": (0, 0, 0),
    "docs/api/rbac.md": (5, 12, 0),
    "docs/api/sequential-testing.md": (0, 0, 0),
    "docs/api/split-url.md": (0, 3, 0),
    "docs/api/warehouse-analytics.md": (0, 0, 0),
    "docs/architecture/models.md": (2, 1, 1),
    "docs/architecture/technical-guide.md": (11, 5, 0),
    "docs/auth/auth-environment-variables.md": (0, 4, 0),
    "docs/auth/cognito-auth-testing.md": (0, 0, 0),
    "docs/auth/sso.md": (0, 0, 0),
    "docs/deployment/README.md": (13, 0, 0),
    "docs/deployment/deployment-guide.md": (10, 1, 3),
    "docs/deployment/disaster-recovery.md": (51, 0, 1),
    "docs/deployment/iam-permissions.md": (2, 1, 1),
    "docs/deployment/rollback-runbook.md": (106, 1, 0),
    "docs/deployment/secrets-management.md": (10, 1, 0),
    "docs/development/database/migrations.md": (18, 1, 1),
    "docs/development/guidelines.md": (3, 2, 0),
    "docs/development/testing-guide.md": (25, 0, 0),
    "docs/development/workflow-explanation.md": (5, 0, 0),
    "docs/feature-flags/rollouts.md": (0, 1, 0),
    "docs/feature-flags/safety.md": (0, 0, 0),
    "docs/getting-started/docker-compose-file.md": (4, 0, 0),
    "docs/getting-started/docker-guide.md": (0, 1, 1),
    "docs/getting-started/environment-setup.md": (3, 5, 0),
    "docs/getting-started/modules.md": (12, 0, 0),
    "docs/getting-started/pre-commit-hooks.md": (5, 0, 0),
    "docs/getting-started/python-virtual-env-setup.md": (6, 1, 0),
    "docs/getting-started/vscode-settings.md": (0, 0, 0),
    "docs/guides/experiment-wizard.md": (0, 1, 0),
    "docs/hipaa/overview.md": (4, 0, 1),
    "docs/infrastructure/aws-iam-setup.md": (0, 0, 0),
    "docs/infrastructure/cloudwatch-setup.md": (7, 4, 0),
    "docs/infrastructure/dynamodb-readme.md": (2, 0, 0),
    "docs/infrastructure/network-security-readme.md": (3, 0, 0),
    "docs/infrastructure/redis-summary.md": (2, 0, 0),
    "docs/infrastructure/vpc-stack-implementation.md": (0, 0, 0),
    "docs/integrations/aws.md": (4, 0, 0),
    "docs/integrations/github.md": (3, 4, 0),
    "docs/integrations/salesforce.md": (0, 1, 0),
    "docs/llm-evaluation/overview.md": (0, 2, 0),
    "docs/llm-evaluation/quickstart.md": (2, 1, 0),
    "docs/mcp-server.md": (2, 0, 0),
    "docs/monitoring/dashboard-reference.md": (0, 0, 0),
    "docs/monitoring/index.md": (0, 1, 0),
    "docs/monitoring/monitoring-guide.md": (2, 1, 0),
    "docs/monitoring/setup-guide.md": (7, 1, 0),
    "docs/monitoring/troubleshooting-guide.md": (3, 1, 0),
    "docs/performance/load-testing.md": (17, 3, 0),
    "docs/sdk-guide.md": (4, 0, 0),
    "docs/sdk/android.md": (1, 0, 0),
    "docs/sdk/dotnet.md": (3, 0, 0),
    "docs/sdk/edge.md": (6, 0, 0),
    "docs/sdk/elixir.md": (4, 0, 0),
    "docs/sdk/flutter.md": (2, 0, 0),
    "docs/sdk/go.md": (3, 0, 0),
    "docs/sdk/ios.md": (2, 0, 0),
    "docs/sdk/java.md": (2, 0, 0),
    "docs/sdk/javascript.md": (6, 1, 0),
    "docs/sdk/openfeature.md": (9, 2, 0),
    "docs/sdk/php.md": (4, 0, 0),
    "docs/sdk/python.md": (5, 0, 0),
    "docs/sdk/react-native.md": (6, 1, 0),
    "docs/sdk/react.md": (2, 0, 0),
    "docs/sdk/ruby.md": (3, 0, 0),
    "docs/security/api-keys.md": (4, 1, 0),
    "docs/self-hosting/cdk.md": (14, 1, 3),
    "docs/self-hosting/migrations.md": (12, 4, 1),
    "docs/self-hosting/monitoring.md": (5, 0, 0),
    "docs/self-hosting/releases.md": (1, 1, 0),
    "docs/statistics/fdr-correction.md": (0, 1, 0),
    "docs/warehouse/clickhouse.md": (1, 0, 0),
    "docs/warehouse/databricks.md": (0, 0, 0),
    "docs/warehouse/mysql.md": (1, 0, 0),
    "docs/websocket-streaming.md": (3, 2, 0),
    "frontend/README.md": (7, 1, 0),
    "sdk/android/README.md": (3, 0, 0),
    "sdk/dotnet/README.md": (2, 2, 0),
    "sdk/edge/README.md": (2, 0, 0),
    "sdk/elixir/README.md": (3, 1, 0),
    "sdk/flutter/README.md": (2, 0, 0),
    "sdk/go/README.md": (3, 0, 0),
    "sdk/ios/README.md": (2, 0, 0),
    "sdk/java/README.md": (2, 0, 0),
    "sdk/js/README.md": (2, 0, 0),
    "sdk/openfeature-python/README.md": (3, 0, 0),
    "sdk/openfeature/README.md": (2, 0, 0),
    "sdk/php/README.md": (4, 0, 0),
    "sdk/python/README.md": (4, 0, 0),
    "sdk/react/README.md": (3, 0, 0),
    "sdk/ruby/README.md": (3, 0, 0),
    "tests/sdk-contract/README.md": (3, 0, 0),
}

# The document a ``stack`` document's stack is started from, and the one command
# in it that starts the stack.  Coupled by assertion (``_check_stack``), not by
# a copy: a quick-start edit that changes the command fails here.
STACK_DOC = "docs/getting-started/quick-start.md"
STACK_UP = "docker compose up -d --wait"
# The same for ``stack-full``: the full profile's start, as the modules page
# gives it.  The prefix is inline, as a reader types it, so the page's blocks do
# not inherit EXPERIMENTLY_PROFILE.
STACK_FULL_DOC = "docs/getting-started/modules.md"
STACK_FULL_UP = "EXPERIMENTLY_PROFILE=full docker compose up -d --wait"
# Asked after the full stack starts: an image that silently built `core` would
# otherwise answer every module route 404, and a page that does not assert on
# its output would pass.
MODULES_URL = "http://localhost:8000/api/v1/modules"

# ---------------------------------------------------------------------------
# Shards (E0b).  Every page that runs costs about the same: one stack start
# (the runner's, or the page's own `docker compose up`) and its teardown.
# Measured on GitHub's runners with pre-built images, 2026-09-26: 55-79 s a
# page that starts a stack, across runs 36267027036 (#199, one job),
# 36269912546, 36270433347 and 36270972235 (sharded); a page that starts
# nothing takes under a second.  PAGE_SECONDS is the worst of those, rounded
# up; a shard holds as many pages as fit its run step in SHARD_BUDGET_SECONDS,
# which leaves the job's setup (~1.5 min) inside the 10-minute shard budget
# and well inside the job's timeout.  The summary warns when a page takes
# longer than PAGE_SECONDS: that is the signal to measure again, never a
# failure (no gate asserts a wall-clock time).
# ---------------------------------------------------------------------------
PAGE_SECONDS = 80
SHARD_BUDGET_SECONDS = 480
PAGES_PER_SHARD = SHARD_BUDGET_SECONDS // PAGE_SECONDS
# The image profile a page's stack needs.  Order is the plan's order.
PROFILES = ("core", "full")

# The run deadline: the job's own start and timeout, exported by the workflow
# (the timeout from the same expression as `timeout-minutes`).  The runner
# stops this long before GitHub would, so it can name the page and block,
# tear the stack down and write its report while the job is still alive.
DEADLINE_MARGIN_SECONDS = 120
REPORT_VERSION = 1


class Refused(Exception):
    """A document or the enrolment breaks the contract; nothing is run.

    Carries every problem found, one line each, so a contributor sees them all
    in one run.  Each line begins ``path[:line]: `` where it concerns a file.
    """

    def __init__(self, problems) -> None:
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("\n".join(self.problems))


@dataclasses.dataclass
class Fence:
    line: int  # 1-based line of the opening fence
    marker: str  # the backticks or tildes that open it
    info: str  # everything after the marker, stripped
    body: list[str]  # content lines, de-indented by the opener's indentation
    trailing: list[str] = dataclasses.field(
        default_factory=list
    )  # lines after the close


@dataclasses.dataclass
class Block:
    """A shell fence in an enrolled document."""

    line: int
    kind: str  # "exec" or "skip"
    lang: str
    body: str
    timeout: int = DEFAULT_TIMEOUT
    reason: str = ""
    expects: list[str] = dataclasses.field(default_factory=list)


# ---------------------------------------------------------------------------
# Fences (CommonMark-shaped: an opener, content, a closer at least as long)
# ---------------------------------------------------------------------------

# Any indentation: superfences renders a fence nested in a list item (four or more
# spaces) as code too, so such a fence is a block like any other.
_OPENER = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>`{3,}|~{3,})(?P<info>.*)$")


def parse_fences(text: str, name: str) -> list[Fence]:
    """Every top-level fence in *text*.  An unclosed fence is refused."""
    lines = text.split("\n")
    fences: list[Fence] = []
    i = 0
    while i < len(lines):
        match = _OPENER.match(lines[i])
        if not match or (
            match.group("marker")[0] == "`" and "`" in match.group("info")
        ):
            i += 1
            continue
        indent, marker = len(match.group("indent")), match.group("marker")
        start = i
        body: list[str] = []
        i += 1
        while i < len(lines):
            closer = lines[i].strip()
            if closer and set(closer) == {marker[0]} and len(closer) >= len(marker):
                break
            body.append(
                lines[i][indent:] if lines[i][:indent].strip() == "" else lines[i]
            )
            i += 1
        else:
            raise Refused(f"{name}:{start + 1}: unclosed fence ({marker})")
        fence = Fence(start + 1, marker, match.group("info").strip(), body)
        j = i + 1
        while j < len(lines) and lines[j].lstrip().startswith("<!-- expect"):
            fence.trailing.append(lines[j])
            j += 1
        fences.append(fence)
        i += 1
    return fences


_LIST_ITEM = re.compile(r"^(?P<indent> *)(?:[-*+]|[0-9]{1,9}[.)])(?: +|$)")
# MkDocs containers whose body is indented four spaces: admonitions, collapsible
# admonitions and content tabs.
_CONTAINER = re.compile(r"^(?P<indent> *)(?:!!!|\?\?\?\+?|===)(?: |$)")


def indented_code_lines(text: str) -> list[int]:
    """1-based first lines of the indented code blocks in *text*.

    An indented code block renders as code and can be pasted, but it has no
    info string, so nothing could say what it is.  The rule is python-markdown's
    (what MkDocs renders with): a line indented four or more columns past the
    enclosing list item or container, after a blank line or a heading, outside
    a fence and an HTML comment.  A test pins it to the renderer on every page.
    """
    found: list[int] = []
    contexts: list[int] = []  # the column a list item's or container's body starts
    boundary = True  # the previous line ends a block (start, blank, heading, fence)
    fence: Optional[str] = None
    in_code, code_column, in_comment = False, 0, False
    for number, raw in enumerate(text.split("\n"), 1):
        line = raw.expandtabs(4)
        stripped = line.strip()
        if fence is not None:
            if stripped and set(stripped) == {fence[0]} and len(stripped) >= len(fence):
                fence, boundary = None, True
            continue
        if in_comment:
            in_comment = "-->" not in line
            boundary = not in_comment
            continue
        if not stripped:
            boundary = True
            continue
        indent = len(line) - len(line.lstrip(" "))
        if in_code and indent >= code_column:
            continue
        in_code = False
        if boundary:
            while contexts and indent < contexts[-1]:
                contexts.pop()
        base = contexts[-1] if contexts else 0
        if boundary and indent >= base + 4:
            found.append(number)
            in_code, code_column, boundary = True, base + 4, False
            continue
        opener = _OPENER.match(line)
        if opener and not (
            opener.group("marker")[0] == "`" and "`" in opener.group("info")
        ):
            fence = opener.group("marker")
            continue
        if stripped.startswith("<!--"):
            in_comment = "-->" not in stripped[4:]
            boundary = not in_comment
            continue
        item = _LIST_ITEM.match(line) or _CONTAINER.match(line)
        if item:
            contexts.append(len(item.group("indent")) + 4)
        boundary = stripped.startswith("#") and indent < 4
    return found


# ---------------------------------------------------------------------------
# The tag grammar
# ---------------------------------------------------------------------------

_BRACE = re.compile(r"^\{(?P<inner>[^{}]*)\}(?P<rest>.*)$")
_ATTR = re.compile(
    r'\s*(?:(?P<key>[a-z_]+)=(?:"(?P<quoted>[^"]*)"|(?P<bare>\S+))|(?P<word>\S+))'
)
_EXPECT = re.compile(r"^\s*<!-- expect: (?P<text>.+?) -->\s*$")


def fence_language(info: str) -> str:
    """The language a fence names: ``bash`` for ```bash, ```{.bash exec} and
    ```{bash exec}; ``""`` for a fence that names none."""
    brace = _BRACE.match(info)
    if not brace:
        return info.split()[0] if info.split() else ""
    words = [
        m.group("word")
        for m in _ATTR.finditer(brace.group("inner"))
        if m.group("word") and m.group("word") not in ("exec", "skip")
    ]
    classes = [w[1:] for w in words if w.startswith(".")]
    return (classes or words or [""])[0]


def _names_shell(info: str) -> bool:
    return fence_language(info) in SHELL


def _other_shell(language: str) -> bool:
    lowered = language.lower()
    return lowered in OTHER_SHELLS or (lowered in SHELL and language not in SHELL)


# `<category>: <text>`, or `bug #<digits>: <text>`.  Whether the issue is open
# is not checked here: check() runs where there is no network (core-build, the
# unit tests), so only the shape is enforced.
_REASON = re.compile(r"^(?P<category>[a-z]+)(?P<issue> #[0-9]{1,7})?: \S")


def category_of(reason: str) -> Optional[str]:
    """The category a skip reason begins with, or None if it names none."""
    match = _REASON.match(reason)
    if not match or match.group("category") not in CATEGORIES:
        return None
    if (match.group("category") == "bug") != bool(match.group("issue")):
        return None
    return match.group("category")


def classify(fence: Fence, name: str) -> Optional[Block]:
    """The Block for a shell fence, None for any other fence; Refused if malformed."""
    where = f"{name}:{fence.line}"
    info = fence.info
    language = fence_language(info)
    if _other_shell(language):
        raise Refused(
            f"{where}: '{language}' names a shell the runner does not know; "
            "use {.bash …}"
        )
    if not info.startswith("{"):
        if info.split()[:1] and info.split()[0] in SHELL:
            if len(info.split()) > 1:
                raise Refused(
                    f"{where}: '{info}' is not brace form "
                    f"(superfences renders it as a paragraph); write {{.{info.split()[0]} ...}}"
                )
            raise Refused(
                f"{where}: untagged shell fence '```{info}'; tag it "
                f'{{.bash exec}} or {{.{info} skip reason="..."}}'
            )
        if fence.trailing:
            raise Refused(f"{where}: an expectation follows a block that does not run")
        return None
    brace = _BRACE.match(info)
    if not brace:
        raise Refused(f"{where}: malformed brace info string '{info}'")
    if brace.group("rest").strip():
        raise Refused(f"{where}: text after '}}' (it breaks the fence)")
    tokens = [m for m in _ATTR.finditer(brace.group("inner")) if m.group(0).strip()]
    words = [t.group("word") for t in tokens if t.group("word")]
    classes = [w[1:] for w in words if w.startswith(".")]
    words = [w for w in words if not w.startswith(".")]
    if not classes:
        if any(w in SHELL for w in words):
            raise Refused(f"{where}: brace fence names a shell language without '.'")
        lang = ""
    elif len(classes) > 1 or not (tokens[0].group("word") or "").startswith("."):
        if any(c in SHELL for c in classes):
            raise Refused(f"{where}: exactly one language class, and first")
        lang = ""
    else:
        lang = classes[0]
    if lang not in SHELL:  # not a shell fence: not ours to judge, but it never runs
        if "exec" in words or "skip" in words:
            raise Refused(f"{where}: exec/skip on a fence that is not shell")
        if fence.trailing:
            raise Refused(f"{where}: an expectation follows a block that does not run")
        return None
    attrs: dict[str, str] = {}
    for t in tokens:
        if t.group("key"):
            key = t.group("key")
            if key in attrs:
                raise Refused(f"{where}: duplicate attribute '{key}'")
            attrs[key] = (
                t.group("quoted") if t.group("quoted") is not None else t.group("bare")
            )
    kinds = [w for w in words if w in ("exec", "skip")]
    unknown = [w for w in words if w not in ("exec", "skip")] + [
        k for k in attrs if k not in ("timeout", "reason")
    ]
    if unknown:
        raise Refused(f"{where}: unknown attribute(s) {unknown}")
    if len(kinds) != 1:
        raise Refused(f"{where}: a shell fence carries exactly one of exec or skip")
    kind = kinds[0]
    body = "\n".join(fence.body)
    if kind == "skip":
        reason = attrs.get("reason", "")
        if not reason.strip() or len(reason) > 200:
            raise Refused(f'{where}: skip needs reason="..." (1-200 characters)')
        if category_of(reason) is None:
            raise Refused(
                f"{where}: skip reason must start with one of: "
                f"{', '.join(CATEGORIES)}, then ': ' (bug is 'bug #<issue>: ') "
                f"({AUTHORING}#pages-that-cannot-run-here)"
            )
        if "timeout" in attrs:
            raise Refused(f"{where}: timeout on a block that does not run")
        if fence.trailing:
            raise Refused(f"{where}: an expectation follows a block that does not run")
        return Block(fence.line, "skip", lang, body, reason=reason)
    if lang != "bash":
        raise Refused(f"{where}: only .bash blocks run (the runner is bash)")
    if "reason" in attrs:
        raise Refused(f"{where}: reason on a block that runs")
    timeout = DEFAULT_TIMEOUT
    if "timeout" in attrs:
        if (
            not re.fullmatch(r"[0-9]{1,4}", attrs["timeout"])
            or not 1 <= int(attrs["timeout"]) <= 3600
        ):
            raise Refused(f"{where}: timeout must be 1-3600 seconds")
        timeout = int(attrs["timeout"])
    expects = []
    for line in fence.trailing:
        match = _EXPECT.match(line)
        text = match.group("text").strip() if match else ""
        if not match or not text or len(text) > 200 or "-->" in text:
            raise Refused(f"{where}: malformed expectation {line.strip()!r}")
        expects.append(text)
    return Block(fence.line, "exec", lang, body, timeout=timeout, expects=expects)


# ---------------------------------------------------------------------------
# What may be in a block
# ---------------------------------------------------------------------------

_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(?P<word>[A-Za-z_][A-Za-z0-9_]*)\1")
_MASKED = re.compile(r"^\s*(export|declare|local|readonly)\s+[A-Za-z_]\w*=\$\(")
# Ways a block could reach past the runner's compose project (PR-2b isolates each
# document with COMPOSE_PROJECT_NAME).  The quick-start's own plain
# `docker compose down -v` is allowed: under that isolation it removes only the
# runner's project.
_ESCAPES = (
    (re.compile(r"COMPOSE_PROJECT_NAME"), "sets or clears COMPOSE_PROJECT_NAME"),
    (
        re.compile(r"docker\s+compose\b[^\n]*\s(-p\b|--project-name\b)"),
        "names a compose project",
    ),
    (
        re.compile(r"\benv\s+(-u\b|-i\b|--unset\b|--ignore-environment\b)"),
        "rewrites the environment",
    ),
    (re.compile(r"\bunset\s+COMPOSE"), "clears a compose setting"),
    (
        re.compile(
            r"\bdocker\s+(volume|container|network|system|image)\s+(rm|prune)\b"
        ),
        "removes Docker resources directly",
    ),
    (re.compile(r"\bdocker\s+rm\b"), "removes containers directly"),
)


# Where a command word can stand: the start of a line, after a separator or an
# opening `(`, `$(`, a backtick or `{`, or after `then`/`do`/`else`; past any
# `sudo`/`exec`/`time`/`command`/`env` and `NAME=value` prefixes.  Used to
# refuse what a block may not *run*, so `echo npm` is not a hit and
# `cd sdk && npm ci` is.
_COMMAND_AT = (
    r"(?:^|[;&|(`{]|\$\(|\b(?:then|do|else)\s)\s*"
    r"(?:\\?(?:[^\s;&|()<>\"'`:]*/)?(?:sudo|exec|time|command|env)\s+)*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"
    # The command word itself is normalised: a leading backslash (`\aws`
    # bypasses an alias), surrounding quotes (`"aws"`) and any path prefix
    # (`/usr/local/bin/aws`, `./gradlew`) are all the same command.
    r"\\?[\"']?(?:[^\s;&|()<>\"'`:]*/)?"
)
_WORD_END = r"[\"']?(?![\w.-])"
# M6 (T29): until the package names are published (D8), no example that runs
# may install or run a package from a public registry -- the names return 404
# today, so a run would fetch whatever a squatter registers.  Every install
# verb the run image can execute (PE FALSE 4), not a list of our names.
_PACKAGE_MANAGER = re.compile(
    _COMMAND_AT + r"(?P<tool>pip[0-9.]*|pipx|poetry|uvx?|npm|npx|yarn|pnpm|bunx?"
    r"|gem|composer|python[0-9.]*[\"']?\s+-m\s+pip|go\s+(?:get|install|run)"
    r"|cargo\s+install|mvnw?|gradlew?|swift\s+(?:package|build)"
    r"|dotnet\s+(?:add|restore|build|tool\s+install))" + _WORD_END,
    re.M,
)
# PE C10: an example that runs never reaches an AWS account.
_CLOUD = re.compile(_COMMAND_AT + r"(?P<tool>aws|cdk|sam)" + _WORD_END, re.M)


def shell_text(body: str) -> str:
    """*body* as the M6/AWS/registry scans read it: `\\`-newline continuations
    joined, and nothing else changed.

    Here-document bodies are scanned like any other line.  Deciding which
    heredocs are only data (`cat <<EOF > f`) and which run (`bash <<EOF`,
    `. <(cat <<EOF`, `(cat <<EOF) | bash`, ...) took three review rounds and
    was still bypassable, so there is no such decision: an exec block whose
    heredoc merely mentions `npm install` is refused too, and its author makes
    it a skip block or writes the file another way.  (``comments`` still
    treats heredoc bodies as data: that rule is about what zsh sees when the
    block is pasted, not about what runs.)
    """
    return re.sub(r"\\\n", " ", body)


def comments(body: str) -> list[tuple[int, str]]:
    """(0-based line, comment text) for each line of *body* carrying a comment.

    A ``#`` starts a comment only outside quotes and at the start of a word, so
    ``$#``, ``${#x}``, ``a#b`` and a URL's ``#anchor`` are not comments.  Lines
    inside a here-document are data, not shell, and are skipped.
    """
    found, terminator = [], None
    for number, line in enumerate(body.split("\n")):
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        quote = None
        for column, char in enumerate(line):
            if quote:
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif char == "#" and (column == 0 or line[column - 1] in " \t;&|("):
                found.append((number, line[column:].strip()))
                break
        heredoc = _HEREDOC.search(line)
        if heredoc:
            terminator = heredoc.group("word")
    return found


def comment_lines(body: str) -> list[int]:
    """0-based lines of *body* that carry a shell comment (see ``comments``)."""
    return [number for number, _ in comments(body)]


def comment_problem(name: str, line: int, text: str) -> str:
    shown = text if len(text) <= 60 else text[:57] + "..."
    return (
        f'{name}:{line}: shell comment "{shown}" breaks when pasted into zsh. '
        "Move it into the sentence before or after the block "
        f"({AUTHORING}#rewriting-a-comment)."
    )


_SYNTAX_BASH: list[Optional[str]] = []


def syntax_problem(body: str) -> Optional[str]:
    """What ``bash -n`` says is wrong with *body*, or None.

    The bash is resolved the way ``bash_executable`` resolves the one that runs
    the examples (>= 4.4, from PATH), so a laptop's /bin/bash 3.2 is refused
    rather than disagreeing with CI (PE C16).
    """
    if not _SYNTAX_BASH:
        _SYNTAX_BASH.append(bash_executable({"PATH": os.environ.get("PATH", "")}))
    if _SYNTAX_BASH[0] is None:  # check() found no usable bash and said so once
        return None
    return _bash_n(_SYNTAX_BASH[0], body)


def _syntax_checked() -> bool:
    return not (_SYNTAX_BASH and _SYNTAX_BASH[0] is None)


@functools.lru_cache(maxsize=4096)
def _bash_n(bash: str, body: str) -> Optional[str]:
    check = subprocess.run(
        [bash, "--noprofile", "--norc", "-n"],
        input=body,
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode != 0 or check.stderr.strip():
        return check.stderr.strip().replace("\n", " ") or "failed"
    return None


def block_problems(block: Block, name: str) -> list[str]:
    """Everything a reader could not paste, or a run could not do, in *block*."""
    where = f"{name}:{block.line}"
    problems = [
        comment_problem(name, block.line + 1 + offset, text)
        for offset, text in comments(block.body)
    ]
    category = category_of(block.reason) if block.kind == "skip" else None
    if block.kind == "skip":
        if category == "registry" and not _PACKAGE_MANAGER.search(
            shell_text(block.body)
        ):
            problems.append(
                f"{where}: the skip reason says 'registry' but the block runs no "
                "package manager; name the category that fits"
            )
        # A fragment is a template to fill in, not shell as written (plan M4).
        if category != "fragment" and block.body.strip():
            syntax = syntax_problem(block.body)
            if syntax:
                problems.append(f"{where}: syntax (bash -n): {syntax}")
        return problems
    if not block.body.strip():
        return problems + [f"{where}: empty block"]
    last = [line for line in block.body.split("\n") if line.strip()][-1]
    if last.rstrip().endswith("\\"):
        problems.append(
            f"{where}: last line ends in '\\' (it would swallow what follows)"
        )
    if any(_MASKED.search(line) for line in block.body.split("\n")):
        problems.append(
            f"{where}: 'export X=$(...)' masks the substitution's exit "
            "status; assign, then export"
        )
    for pattern, what in _ESCAPES:
        if pattern.search(block.body):
            problems.append(f"{where}: the block {what}")
    installer = _PACKAGE_MANAGER.search(shell_text(block.body))
    if installer:
        tool = " ".join(installer.group("tool").split())
        problems.append(
            f"{where}: a block that runs may not run '{tool}': no example installs "
            "or runs a package until the package names are published (D8). Tag it "
            '{.bash skip reason="registry: …"}'
        )
    cloud = _CLOUD.search(shell_text(block.body))
    if cloud:
        problems.append(
            f"{where}: a block that runs may not call '{cloud.group('tool')}': "
            'no example reaches an AWS account. Tag it {.bash skip reason="aws: …"}'
        )
    syntax = syntax_problem(block.body)
    if syntax:
        problems.append(f"{where}: syntax (bash -n): {syntax}")
    return problems


def lint_block(block: Block, name: str) -> None:
    problems = block_problems(block, name)
    if problems:
        raise Refused(problems)


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------

_DOC_KEYS = {"path", "environment", "exec", "skip", "expects"}
_META_KEYS = {"documents", "exec", "universe"}
_EXEMPT_KEYS = {"path", "reason"}
_PENDING_KEYS = ("comments", "unlabelled", "syntax")
_PENDING_WHAT = {
    "comments": "shell comment lines",
    "unlabelled": "fences that name no language",
    "syntax": "shell blocks that fail bash -n",
}


@dataclasses.dataclass
class Enrolment:
    documents: list[dict]
    exempt: list[dict]
    pending: dict[str, dict]
    universe: list[str]
    name: str
    # What is wrong with the entries themselves; check() reports these with
    # the pages' problems, so one run shows everything.
    problems: list[str] = dataclasses.field(default_factory=list)
    exec_total: int = 0  # [meta] exec


def walk(root: Optional[pathlib.Path] = None) -> set[str]:
    """Every in-scope Markdown page under *root*: the universe.

    A filesystem walk, not ``git ls-files``, so it gives the same answer in
    core-build's copy (no .git).  Directories named in PRUNED_DIRS, and every
    dot-directory but .github, are pruned by name at any depth.
    """
    root = root or ROOT
    found = set()
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in PRUNED_DIRS and (not d.startswith(".") or d in KEPT_DOT_DIRS)
        )
        for file in files:
            if file.lower().endswith(".md") and file.lower() != "claude.md":
                found.add((pathlib.Path(directory) / file).relative_to(root).as_posix())
    return found


def _in_this_tree(rel: str) -> bool:
    """False for a module page in a core tree (no modules/): not refused there."""
    return not (rel.startswith("modules/") and not (ROOT / "modules").is_dir())


def _display(path: pathlib.Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _path_problem(name: str, rel, listed_as: str) -> Optional[str]:
    if (
        not isinstance(rel, str)
        or rel.startswith("/")
        or ".." in pathlib.PurePosixPath(rel).parts
        or not rel.lower().endswith(".md")
    ):
        return f"{name}: {rel} is not a markdown file in the repository"
    if pathlib.PurePosixPath(rel).name.lower() == "claude.md" or rel.startswith(
        ".claude/"
    ):
        return f"{name}: {rel} is working instructions, not documentation (T1)"
    if _in_this_tree(rel) and not (ROOT / rel).is_file():
        return (
            f"{rel} is {listed_as} but does not exist. Renamed? Change the path. "
            "Deleted? Remove its entry"
            + (
                " and set [meta] documents to match."
                if listed_as == "enrolled"
                else "."
            )
        )
    return None


def _count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def load(path: Optional[pathlib.Path] = None) -> Enrolment:
    """The enrolment file, with every structural problem in it refused at once."""
    path = path or ENROLMENT
    name = _display(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise Refused(f"{name}: {error}") from None
    unknown = set(data) - {"meta", "document", "exempt", "pending"}
    if unknown:
        raise Refused(f"{name}: unknown table(s) {sorted(unknown)}")
    meta = data.get("meta", {})
    if (
        set(meta) != _META_KEYS
        or not _count(meta["documents"])
        or not _count(meta["exec"])
        or not isinstance(meta["universe"], list)
        or not all(isinstance(p, str) for p in meta["universe"])
    ):
        raise Refused(
            f"{name}: [meta] must be exactly 'documents = <n>', 'exec = <n>' and "
            "'universe = [<path>, ...]'"
        )
    documents, exempt = data.get("document", []), data.get("exempt", [])
    pending = data.get("pending", {})
    problems: list[str] = []
    for doc in documents:
        if set(doc) != _DOC_KEYS:
            raise Refused(
                f"{name}: a document has keys {sorted(doc)}; want {sorted(_DOC_KEYS)}"
            )
    for entry in exempt:
        if set(entry) != _EXEMPT_KEYS:
            raise Refused(
                f"{name}: an exempt entry has keys {sorted(entry)}; want {sorted(_EXEMPT_KEYS)}"
            )
    for rel, entry in pending.items():
        if not isinstance(entry, dict) or set(entry) != set(_PENDING_KEYS):
            raise Refused(
                f"{name}: [pending] {rel} must be "
                "{ comments = <n>, unlabelled = <n>, syntax = <n> }"
            )
    if len(documents) != meta["documents"]:
        problems.append(
            f"{name} lists {len(documents)} documents but [meta] documents = "
            f"{meta['documents']}; set it to {len(documents)}."
        )
    declared = sum(d["exec"] for d in documents if _count(d["exec"]))
    if declared != meta["exec"]:
        problems.append(
            f"{name}: the documents' exec counts add up to {declared} but "
            f"[meta] exec = {meta['exec']}; set it to {declared}."
        )
    where: dict[str, list[str]] = {}
    for listed_as, paths in (
        ("enrolled", [d["path"] for d in documents]),
        ("exempt", [e["path"] for e in exempt]),
        ("pending", list(pending)),
    ):
        for rel in paths:
            where.setdefault(rel, []).append(listed_as)
            problem = _path_problem(name, rel, listed_as)
            if problem:
                problems.append(problem)
    for rel, lists in sorted(where.items()):
        if len(lists) > 1:
            problems.append(
                f"{rel} is listed {len(lists)} times ({', '.join(lists)}); "
                "a page is exactly one of enrolled, exempt or pending"
            )
    for doc in documents:
        rel = doc["path"]
        if doc["environment"] not in ENVIRONMENTS:
            problems.append(
                f"{rel}: environment {doc['environment']!r} is not one of {ENVIRONMENTS}"
            )
        elif doc["environment"] == "local":
            problems.append(
                f"{rel}: environment 'local' is not implemented yet (the demo applications)"
            )
        for key in ("exec", "skip", "expects"):
            if not _count(doc[key]):
                problems.append(f"{rel}: {key} must be a non-negative integer")
    for entry in exempt:
        reason = entry["reason"]
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 200:
            problems.append(
                f"{entry['path']}: exempt needs a reason (1-200 characters)"
            )
    for rel, entry in pending.items():
        for key in _PENDING_KEYS:
            if not _count(entry[key]):
                problems.append(
                    f"{rel}: [pending] {key} must be a non-negative integer"
                )
    seen: set[str] = set()
    for rel in meta["universe"]:
        if rel in seen:
            problems.append(f"{name}: {rel} is in [meta] universe twice")
        seen.add(rel)
    return Enrolment(
        documents, exempt, pending, meta["universe"], name, problems, meta["exec"]
    )


def load_enrolment(path: Optional[pathlib.Path] = None) -> list[dict]:
    enrolment = load(path)
    if enrolment.problems:
        raise Refused(enrolment.problems)
    return enrolment.documents


def blocks_of(rel: str) -> list[Block]:
    text = (ROOT / rel).read_text(encoding="utf-8")
    blocks = [b for f in parse_fences(text, rel) if (b := classify(f, rel)) is not None]
    for block in blocks:
        lint_block(block, rel)
    return blocks


def _check_stack(documents: list[dict], parsed: dict[str, list[Block]]) -> None:
    problems = []
    for environment, doc_path, doc_environment, up in (
        ("stack", STACK_DOC, "bare", STACK_UP),
        ("stack-full", STACK_FULL_DOC, "stack-full", STACK_FULL_UP),
    ):
        if not any(d["environment"] == environment for d in documents):
            continue
        source = next((d for d in documents if d["path"] == doc_path), None)
        if source is None or source["environment"] != doc_environment:
            problems.append(
                f"a {environment!r} document needs {doc_path} enrolled as "
                f"{doc_environment!r}"
            )
            continue
        ups = [
            b
            for b in parsed.get(doc_path, [])
            if b.kind == "exec" and b.body.strip() == up
        ]
        if len(ups) != 1:
            problems.append(
                f"{doc_path}: {len(ups)} exec blocks equal {up!r} (expected exactly 1)"
            )
    if problems:
        raise Refused(problems)


_COUNTED = {"exec": "exec blocks", "skip": "skip blocks", "expects": "expectations"}


def _enrolled_page(
    rel: str, doc: dict, fences: list[Fence], problems: list[str]
) -> list[Block]:
    blocks = []
    for fence in fences:
        if _other_shell(fence_language(fence.info)):
            continue  # reported for every page, below
        try:
            block = classify(fence, rel)
        except Refused as refusal:
            problems += refusal.problems
            continue
        if block is not None:
            blocks.append(block)
            problems += block_problems(block, rel)
    got = {
        "exec": sum(b.kind == "exec" for b in blocks),
        "skip": sum(b.kind == "skip" for b in blocks),
        "expects": sum(len(b.expects) for b in blocks),
    }
    for key, value in got.items():
        if _count(doc[key]) and value != doc[key]:
            problems.append(
                f"{rel}: found {value} {_COUNTED[key]}; the enrolment says {doc[key]}. "
                f"If you added or removed one on purpose, set {key} = {value}. "
                "If not, a block lost or gained its tag."
            )
    return blocks


def _residual(rel: str, shell: list[Fence], unlabelled: list[Fence]) -> dict[str, int]:
    bodies = ["\n".join(f.body) for f in shell]
    return {
        "comments": sum(len(comment_lines(body)) for body in bodies),
        "unlabelled": len(unlabelled),
        "syntax": sum(
            1 for body in bodies if body.strip() and syntax_problem(body) is not None
        ),
    }


def _pending_page(
    rel: str, entry: dict, shell: list[Fence], unlabelled: list[Fence]
) -> tuple[list[str], dict[str, int]]:
    # A pending page's tags are not read until it is enrolled, so an `exec` tag
    # there would promise a run that never happens.
    problems = [
        f"{rel}:{f.line}: an exec block on a pending page never runs; enrol the "
        "page in the change that tags it exec"
        for f in shell
        if f.info.startswith("{") and "exec" in f.info.strip("{}").split()
    ]
    measured = _residual(rel, shell, unlabelled)
    frozen = PENDING_FROZEN.get(rel)
    if frozen is None:
        problems.append(
            f"{rel}: pending cannot grow, and this page was not pending when the "
            "list was frozen (PENDING_FROZEN in scripts/doc_examples.py). Enrol it, "
            f"or list it as exempt with a reason ({AUTHORING}#enrolling-a-page)."
        )
        return problems, measured
    if not shell and not unlabelled:
        problems.append(
            f"{rel} is pending but has nothing pending (no shell blocks, and every "
            "fence names a language); remove its [pending] entry."
        )
    for key, ceiling in zip(_PENDING_KEYS, frozen):
        if key == "syntax" and not _syntax_checked():
            continue  # not measured without a usable bash (already reported)
        value, what = measured[key], _PENDING_WHAT[key]
        if _count(entry[key]) and value != entry[key]:
            problems.append(
                f"{rel}: found {value} {what}; [pending] says {entry[key]}. "
                f"Set {key} = {value}."
            )
        if value > ceiling:
            problems.append(
                f"{rel}: {value} {what}, more than the {ceiling} this page had when "
                "pending was frozen; the residual can only fall."
            )
    return problems, measured


def _exempt_page(rel: str, shell: list[Fence]) -> list[str]:
    problems = []
    for fence in shell:
        if fence.info.startswith("{"):
            problems.append(
                f"{rel}:{fence.line}: a tagged block on an exempt page; enrol the "
                "page, or leave its blocks untagged"
            )
        body = "\n".join(fence.body)
        problems += [
            comment_problem(rel, fence.line + 1 + offset, text)
            for offset, text in comments(body)
        ]
        syntax = syntax_problem(body) if body.strip() else None
        if syntax:
            problems.append(f"{rel}:{fence.line}: syntax (bash -n): {syntax}")
    return problems


def check(path: Optional[pathlib.Path] = None, out=None) -> dict[str, dict[str, int]]:
    """The whole contract, over every page the walk finds; every problem at once."""
    _SYNTAX_BASH.clear()
    try:
        return _check(path, out or sys.stdout)
    finally:
        # Resolved afresh on every run; "no usable bash" never outlives one.
        _SYNTAX_BASH.clear()


def _check(path: Optional[pathlib.Path], out) -> dict[str, dict[str, int]]:
    enrolment = load(path)
    problems: list[str] = list(enrolment.problems)
    try:
        syntax_problem("true")
    except Refused as refusal:
        # One problem, and every other rule still runs (bash -n is skipped).
        problems += [f"{p}; bash -n was not run on any block" for p in refusal.problems]
        _SYNTAX_BASH.clear()
        _SYNTAX_BASH.append(None)
    found = walk()
    universe = {p for p in enrolment.universe if _in_this_tree(p)}
    for rel in sorted(found - universe):
        problems.append(
            f"{rel}: a page {enrolment.name} does not know. Add it to [meta] "
            f"universe ({AUTHORING}#enrolling-a-page)."
        )
    for rel in sorted(universe - found):
        problems.append(
            f"{rel} is in [meta] universe but the walk does not find it. Renamed? "
            "Change the path. Deleted? Remove it."
        )
    status: dict[str, tuple[str, object]] = {}
    for doc in enrolment.documents:
        status[doc["path"]] = ("enrolled", doc)
    for entry in enrolment.exempt:
        status.setdefault(entry["path"], ("exempt", entry))
    for rel, entry in enrolment.pending.items():
        status.setdefault(rel, ("pending", entry))
    for rel in sorted(status):
        if rel not in found and _in_this_tree(rel) and (ROOT / rel).is_file():
            problems.append(
                f"{rel} is listed but is outside the universe (the walk skips "
                f"{', '.join(PRUNED_DIRS)} and dot-directories other than .github)"
            )

    counts: dict[str, dict[str, int]] = {}
    parsed: dict[str, list[Block]] = {}
    residual = dict.fromkeys(_PENDING_KEYS, 0)
    tally = {"enrolled": 0, "exempt": 0, "pending": 0, "none": 0}
    for rel in sorted(found):
        kind, entry = status.get(rel, ("none", None))
        tally[kind] += 1
        text = (ROOT / rel).read_text(encoding="utf-8")
        try:
            fences = parse_fences(text, rel)
        except Refused as refusal:
            problems += refusal.problems
            continue
        problems += [
            f"{rel}:{line}: an indented code block; use a fenced block with a "
            f"language (`text` for output) ({AUTHORING}#tagging-a-shell-block)"
            for line in indented_code_lines(text)
        ]
        shell, unlabelled = [], []
        for fence in fences:
            language = fence_language(fence.info)
            if not language:
                unlabelled.append(fence)
            elif _other_shell(language):
                problems.append(
                    f"{rel}:{fence.line}: '{language}' names a shell the runner does "
                    "not know; use {.bash …}"
                )
            elif language in SHELL:
                shell.append(fence)
        if kind != "pending":
            problems += [
                f"{rel}:{f.line}: the fence names no language; name one (`text` for "
                f"output) ({AUTHORING}#tagging-a-shell-block)"
                for f in unlabelled
            ]
        if kind == "none":
            if shell:
                problems.append(
                    f"{rel}: {len(shell)} shell block{'s' if len(shell) != 1 else ''}, and the page is not enrolled. "
                    f"Add it to {enrolment.name} ({AUTHORING}#enrolling-a-page), or "
                    "list it as exempt with a reason."
                )
            continue
        if kind in ("enrolled", "exempt") and not shell:
            problems.append(
                f"{rel} is listed as {kind} but has no shell blocks; remove the entry"
                + (" and set [meta] documents to match." if kind == "enrolled" else ".")
            )
            continue
        if kind == "enrolled":
            blocks = _enrolled_page(rel, entry, fences, problems)
            parsed[rel] = blocks
            counts[rel] = {
                "exec": sum(b.kind == "exec" for b in blocks),
                "skip": sum(b.kind == "skip" for b in blocks),
                "expects": sum(len(b.expects) for b in blocks),
            }
            got = counts[rel]
            print(
                f"{rel}: {got['exec']} exec, {got['skip']} skip, "
                f"{got['expects']} expects ({entry['environment']})",
                file=out,
            )
        elif kind == "exempt":
            problems += _exempt_page(rel, shell)
        else:
            found_problems, measured = _pending_page(rel, entry, shell, unlabelled)
            problems += found_problems
            for key in _PENDING_KEYS:
                residual[key] += measured[key]
    try:
        _check_stack(enrolment.documents, parsed)
    except Refused as refusal:
        problems += refusal.problems

    categories: dict[str, int] = {}
    for blocks in parsed.values():
        for block in blocks:
            if block.kind == "skip":
                category = category_of(block.reason) or "?"
                categories[category] = categories.get(category, 0) + 1
    print(
        f"universe: {len(found)} pages; {tally['enrolled']} enrolled, "
        f"{tally['exempt']} exempt, {tally['pending']} pending, "
        f"{tally['none']} with no shell blocks",
        file=out,
    )
    print(
        f"exec blocks: {sum(c['exec'] for c in counts.values())}; skip blocks by "
        "category: "
        + (", ".join(f"{k} {v}" for k, v in sorted(categories.items())) or "none"),
        file=out,
    )
    print(
        f"pending residual: {residual['comments']} comment lines, "
        f"{residual['unlabelled']} unlabelled fences, {residual['syntax']} bash -n "
        "failures",
        file=out,
    )
    if problems:
        raise Refused(problems)
    print(f"{len(enrolment.documents)} document(s): contract holds", file=out)
    return counts


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class _PageScan(html.parser.HTMLParser):
    """Count code blocks, and collect what each <p> says outside and inside <code>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.code_blocks = 0
        self.paragraphs: list[dict] = []
        self._stack: list[str] = []
        self._p: Optional[dict] = None

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag == "div" and "highlight" in classes:
            self.code_blocks += 1
        self._stack.append(tag)
        if tag == "p":
            self._p = {"outside": "", "codes": [], "children": 0, "in_code": False}
        elif self._p is not None:
            self._p["children"] += 1
            if tag == "code":
                self._p["in_code"] = True
                self._p["codes"].append("")

    def handle_endtag(self, tag):
        while self._stack and self._stack.pop() != tag:
            pass
        if tag == "code" and self._p is not None:
            self._p["in_code"] = False
        if tag == "p" and self._p is not None:
            self.paragraphs.append(self._p)
            self._p = None

    def handle_data(self, data):
        if self._p is None:
            return
        if self._p["in_code"]:
            self._p["codes"][-1] += data
        else:
            self._p["outside"] += data


def render_problems(source: str, page_html: str, name: str) -> list[str]:
    """What is wrong with how *page_html* rendered *source*'s fences."""
    problems = []
    fences = len(parse_fences(source, name))
    scan = _PageScan()
    scan.feed(page_html)
    if scan.code_blocks != fences:
        problems.append(
            f"{name}: {scan.code_blocks} rendered code blocks, {fences} fences in source"
        )
    for p in scan.paragraphs:
        leaked = any(
            line.lstrip().startswith(("```", "~~~"))
            for line in p["outside"].split("\n")
        )
        only_code = (
            p["children"] == 1 and len(p["codes"]) == 1 and not p["outside"].strip()
        )
        if leaked or (only_code and "\n" in p["codes"][0]):
            problems.append(
                f"{name}: a fence rendered as a paragraph: {p['outside'][:80]!r}"
            )
    return problems


def render(
    site: pathlib.Path, path: Optional[pathlib.Path] = None, out=sys.stdout
) -> None:
    problems = []
    for doc in load_enrolment(path):
        rel = pathlib.PurePosixPath(doc["path"])
        if rel.parts[0] != "docs":
            continue  # outside docs/, MkDocs builds no page (T1's stated asymmetry)
        page_rel = rel.relative_to("docs").with_suffix("")
        if page_rel.name in ("README", "index"):
            page = site / page_rel.parent / "index.html"
        else:
            page = site / page_rel / "index.html"
        if not page.is_file():
            problems.append(f"{rel}: no page at {page} (excluded from the site?)")
            continue
        problems += render_problems(
            (ROOT / rel).read_text(encoding="utf-8"),
            page.read_text(encoding="utf-8"),
            str(rel),
        )
        print(f"{rel}: rendered", file=out)
    if problems:
        raise Refused("\n".join(problems))


# ---------------------------------------------------------------------------
# Shards, the run deadline and the shard reports (E0b)
# ---------------------------------------------------------------------------

Shard = tuple[str, int, int]  # (profile, k, n), k counted from 1
_SHARD = re.compile(
    r"^(?P<profile>[a-z]+):(?P<k>[1-9][0-9]{0,2})/(?P<n>[1-9][0-9]{0,2})$"
)


def profile_of(doc: dict) -> str:
    """The image profile a page's stack needs."""
    return "full" if doc["environment"] == "stack-full" else "core"


def runs(doc: dict) -> bool:
    """Whether a page has anything to run."""
    return _count(doc["exec"]) and doc["exec"] > 0


def shard_label(shard: Shard) -> str:
    profile, k, n = shard
    return f"{profile}:{k}/{n}"


def parse_shard(text: str) -> Shard:
    match = _SHARD.match(text or "")
    if not match or match.group("profile") not in PROFILES:
        raise Refused(
            f"--shard {text!r}: write PROFILE:K/N, PROFILE one of {', '.join(PROFILES)}"
        )
    k, n = int(match.group("k")), int(match.group("n"))
    if k > n:
        raise Refused(f"--shard {text!r}: shard {k} of {n} does not exist")
    return match.group("profile"), k, n


def shard_plan(documents: list[dict]) -> dict[Shard, list[str]]:
    """Every page that runs, in exactly one shard.

    Per profile, the pages in path order are dealt round-robin across
    ceil(pages / PAGES_PER_SHARD) shards, so no shard holds more than
    PAGES_PER_SHARD.  A function of the enrolment alone: the matrix and each
    shard's pages come from it, and nothing lists a page by hand.  (The
    summary's expected pages do NOT come from here, but from the enrolment
    directly, so a page this function lost is still missed.)
    """
    by_profile: dict[str, list[str]] = {profile: [] for profile in PROFILES}
    for doc in sorted(documents, key=lambda d: d["path"]):
        if runs(doc):
            by_profile[profile_of(doc)].append(doc["path"])
    plan: dict[Shard, list[str]] = {}
    for profile in PROFILES:
        pages = by_profile[profile]
        n = math.ceil(len(pages) / PAGES_PER_SHARD)
        for k in range(1, n + 1):
            plan[(profile, k, n)] = pages[k - 1 :: n]
    return plan


def matrix(plan: dict[Shard, list[str]]) -> dict:
    """The plan as a GitHub Actions matrix (``strategy.matrix``)."""
    return {
        "include": [{"profile": profile, "shard": k, "of": n} for profile, k, n in plan]
    }


@dataclasses.dataclass
class Deadline:
    """When the runner stops: the job's start + its timeout - the margin."""

    at: float  # epoch seconds
    clock: Callable[[], float] = time.time

    def remaining(self) -> float:
        return self.at - self.clock()

    def reached(self) -> bool:
        return self.remaining() <= 0

    def describe(self) -> str:
        return time.strftime("%H:%M:%S UTC", time.gmtime(self.at))


def deadline_from_env(
    environ: Optional[dict] = None, clock: Callable[[], float] = time.time
) -> Optional[Deadline]:
    """The deadline the workflow exported, or None when it exported none.

    ``DOCEX_JOB_START`` is the job's first step's ``date +%s``;
    ``DOCEX_JOB_TIMEOUT_MINUTES`` is the job's ``timeout-minutes`` expression,
    copied textually (a test pins the two as identical).  One without the other
    is refused: a deadline half-configured is not a deadline.
    """
    environ = os.environ if environ is None else environ
    start = environ.get("DOCEX_JOB_START")
    minutes = environ.get("DOCEX_JOB_TIMEOUT_MINUTES")
    if start is None and minutes is None:
        return None
    if not (start and start.isdigit() and minutes and minutes.isdigit()):
        raise Refused(
            "DOCEX_JOB_START and DOCEX_JOB_TIMEOUT_MINUTES must both be whole "
            f"numbers (got {start!r} and {minutes!r}): the job's start in epoch "
            "seconds, and its timeout-minutes"
        )
    budget = int(minutes) * 60 - DEADLINE_MARGIN_SECONDS
    if budget <= 0:
        raise Refused(
            f"a {minutes}-minute job timeout leaves nothing after the "
            f"{DEADLINE_MARGIN_SECONDS} s the runner keeps to tear down and report"
        )
    deadline = Deadline(int(start) + budget, clock)
    if deadline.reached():
        raise Refused(
            f"the run deadline ({deadline.describe()}) passed before the run began"
        )
    return deadline


def _teardown_seconds(deadline: Optional[Deadline]) -> int:
    """How long a teardown may take: past the deadline, inside the margin."""
    if deadline is None:
        return 600
    return int(min(600, max(60, deadline.remaining() + DEADLINE_MARGIN_SECONDS / 2)))


def write_report(
    path: pathlib.Path, shard: Optional[Shard], pages: dict, stopped: Optional[str]
) -> None:
    """What one shard measured: per page, its exec count, the blocks that
    reached their end (from the sentinels), whether it passed, and its time."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": REPORT_VERSION,
        "shard": shard_label(shard) if shard else None,
        "pages": pages,
        "stopped": stopped,
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _report_problem(data) -> Optional[str]:
    if not isinstance(data, dict) or data.get("version") != REPORT_VERSION:
        return f"not a version-{REPORT_VERSION} shard report"
    if not isinstance(data.get("shard"), str) or not isinstance(
        data.get("pages"), dict
    ):
        return "a shard report needs 'shard' and 'pages'"
    for page, result in data["pages"].items():
        if (
            not isinstance(result, dict)
            or set(result) != {"exec", "reached", "passed", "seconds"}
            or not _count(result["exec"])
            or not _count(result["reached"])
            or not isinstance(result["passed"], bool)
            or not isinstance(result["seconds"], (int, float))
        ):
            return f"{page}: malformed result {result!r}"
    return None


def _annotate(kind: str, message: str, out) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{kind}::{_escape(message)}", file=out)


def summarise(
    directory: pathlib.Path, path: Optional[pathlib.Path] = None, out=None
) -> None:
    """Every page that runs ran exactly once, and all of its blocks reached their end.

    The pages expected come from the enrolment, not from the plan, and the
    shards expected from the plan: a page the plan lost, a shard that never ran
    and a report that never arrived are each named.
    """
    out = out or sys.stdout
    enrolment = load(path)
    if enrolment.problems:
        raise Refused(enrolment.problems)
    documents = enrolment.documents
    expected = {d["path"]: d["exec"] for d in documents if runs(d)}
    plan = shard_plan(documents)
    reports = sorted(directory.rglob("*.json")) if directory.is_dir() else []
    if not reports:
        raise Failed(
            f"no shard reports under {directory}: no shard ran, or none uploaded "
            f"its report; {len(expected)} pages did not run"
        )
    problems: list[str] = []
    seen: dict[Shard, str] = {}
    where: dict[str, list[str]] = {}
    results: dict[str, dict] = {}
    for report in reports:
        name = report.relative_to(directory).as_posix()
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            problems.append(f"{name}: unreadable ({error})")
            continue
        problem = _report_problem(data)
        if problem:
            problems.append(f"{name}: {problem}")
            continue
        try:
            shard = parse_shard(data["shard"])
        except Refused as refusal:
            problems += [f"{name}: {p}" for p in refusal.problems]
            continue
        label = shard_label(shard)
        if shard not in plan:
            problems.append(
                f"{name}: shard {label} is not in the plan "
                f"({', '.join(shard_label(s) for s in plan)})"
            )
            continue
        if shard in seen:
            problems.append(f"shard {label} reported twice ({seen[shard]}, {name})")
            continue
        seen[shard] = name
        if data["stopped"]:
            problems.append(f"shard {label}: {data['stopped']}")
        for page, result in data["pages"].items():
            where.setdefault(page, []).append(label)
            results[page] = result
    unreported: set[str] = set()
    for shard, pages in plan.items():
        if shard not in seen:
            unreported.update(pages)
            problems.append(
                f"shard {shard_label(shard)} sent no report (it did not run, or was "
                f"killed before it wrote one); its pages did not run: {', '.join(pages)}"
            )
    for page in sorted(where):
        if page not in expected:
            problems.append(f"{page}: in a shard report, but not a page that runs")
        elif len(where[page]) > 1:
            problems.append(
                f"{page}: ran {len(where[page])} times ({', '.join(where[page])}); "
                "every page runs exactly once"
            )
    for page, exec_count in sorted(expected.items()):
        if page not in where:
            if page not in unreported:
                problems.append(f"{page}: in no shard's report; it did not run")
            continue
        result = results[page]
        if result["exec"] != exec_count:
            problems.append(
                f"{page}: its shard ran it as {result['exec']} exec blocks; the "
                f"enrolment says {exec_count}"
            )
        if result["reached"] != exec_count:
            problems.append(
                f"{page}: {result['reached']} exec blocks reached their end; the "
                f"enrolment says {exec_count}"
            )
        elif not result["passed"]:
            problems.append(f"{page}: FAILED in shard {where[page][0]} (see its log)")

    reached = sum(r["reached"] for p, r in results.items() if p in expected)
    ran = len(set(where) & set(expected))
    for shard in plan:
        pages = [p for p in plan[shard] if p in results]
        seconds = sum(results[p]["seconds"] for p in pages)
        state = "reported" if shard in seen else "NO REPORT"
        print(
            f"shard {shard_label(shard)}: {len(pages)}/{len(plan[shard])} pages, "
            f"{seconds:.0f} s running pages ({state})",
            file=out,
        )
        if seconds > SHARD_BUDGET_SECONDS:
            _annotate(
                "warning",
                f"shard {shard_label(shard)} ran its pages in {seconds:.0f} s, over "
                f"the {SHARD_BUDGET_SECONDS} s budget; measure PAGE_SECONDS again",
                out,
            )
    for page in sorted(results):
        seconds = results[page]["seconds"]
        print(f"  {page}: {seconds:.1f} s", file=out)
        if seconds > PAGE_SECONDS:
            _annotate(
                "warning",
                f"{page} took {seconds:.0f} s, more than PAGE_SECONDS "
                f"({PAGE_SECONDS}); measure again before the shards overrun",
                out,
            )
    print(
        f"measured: {ran}/{len(expected)} pages ran, {reached} exec blocks reached "
        f"their end; [meta] exec = {enrolment.exec_total}",
        file=out,
    )
    if reached != enrolment.exec_total:
        problems.append(
            f"{reached} exec blocks reached their end across the shards; "
            f"[meta] exec = {enrolment.exec_total}"
        )
    if problems:
        raise Failed("\n".join(problems))
    print(f"{len(plan)} shard(s): every page ran once and every block ran", file=out)


def bug_issues(path: Optional[pathlib.Path] = None) -> list[int]:
    """The issue numbers ``bug #N:`` skip reasons name, on the enrolled pages."""
    numbers: set[int] = set()
    for doc in load_enrolment(path):
        rel = doc["path"]
        if not (ROOT / rel).is_file():
            continue
        for fence in parse_fences((ROOT / rel).read_text(encoding="utf-8"), rel):
            try:
                block = classify(fence, rel)
            except Refused:
                continue
            if block and block.kind == "skip" and category_of(block.reason) == "bug":
                numbers.add(int(_REASON.match(block.reason).group("issue")[2:]))
    return sorted(numbers)


# ---------------------------------------------------------------------------
# Execution: one bash per document, blocks separated by sentinels
# ---------------------------------------------------------------------------

PASSED_ENV = (
    "PATH",
    "HOME",
    "USER",
    "TMPDIR",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
)
OVERRIDABLE = ("POSTGRES_HOST_PORT", "REDIS_HOST_PORT", "FRONTEND_HOST_PORT")
OUTPUT_CAP = 4 * 1024 * 1024
READER_JOIN_SECONDS = 5


class Failed(Exception):
    """A document ran and did not do what it says."""


@dataclasses.dataclass
class Outcome:
    """What one block did."""

    reached: bool = False
    rc: Optional[int] = None
    flags: str = ""
    pipefail: str = ""
    stdout: str = ""
    stderr: str = ""


def scrubbed_env(project: str, overrides: dict[str, str]) -> dict[str, str]:
    """The only environment a document sees: nothing it did not set itself."""
    env = {k: os.environ[k] for k in PASSED_ENV if k in os.environ}
    env["COMPOSE_PROJECT_NAME"] = project
    env["COMPOSE_DISABLE_ENV_FILE"] = "1"
    # HOME is passed, so without these the AWS CLI would read the caller's
    # ~/.aws; no example may reach an account (PE C10).
    env["AWS_CONFIG_FILE"] = os.devnull
    env["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
    env.update(overrides)
    return env


def bash_executable(env: dict[str, str]) -> str:
    """The bash on the scrubbed PATH, refused below 4.4 (no inherit_errexit)."""
    path = shutil.which("bash", path=env.get("PATH"))
    if path is None:
        raise Refused("no bash on PATH")
    version = subprocess.run(
        [
            path,
            "--noprofile",
            "--norc",
            "-c",
            'echo "${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}"',
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    ).stdout.strip()
    major, _, minor = version.partition(".")
    if not (major.isdigit() and minor.isdigit()) or (int(major), int(minor)) < (4, 4):
        raise Refused(f"{path} is bash {version or '?'}; the examples need bash >= 4.4")
    return path


def _sentinel(nonce: str, what: str) -> str:
    return f"@@DOCEX:{nonce}:{what}@@"


def write_script(blocks: list[Block], nonce: str) -> str:
    """The document as one script; each block's text is copied byte for byte."""
    parts = ["set -euo pipefail\n"]
    for i, block in enumerate(blocks):
        begin = _sentinel(nonce, f"BEGIN:{i}")
        parts.append(f"printf '\\n{begin}\\n'; printf '\\n{begin}\\n' >&2\n")
        parts.append(block.body if block.body.endswith("\n") else block.body + "\n")
        end = _sentinel(nonce, f"END:{i}:%s:%s:%s")
        # $? first, before anything else can reset it.
        parts.append(
            "__docex_rc=$?; "
            f'printf \'\\n{end}\\n\' "$__docex_rc" "$-" '
            '"$(shopt -qo pipefail && echo pf || echo nopf)"; '
            f'printf \'\\n{end}\\n\' "$__docex_rc" "$-" '
            '"$(shopt -qo pipefail && echo pf || echo nopf)" >&2\n'
        )
    return "".join(parts)


def run_script(
    script: str,
    blocks: list[Block],
    env: dict[str, str],
    bash: str,
    nonce: str,
    deadline: Optional[Deadline] = None,
) -> tuple[list[Outcome], Optional[str], int]:
    """Run *script*; return each block's outcome, a problem if the run itself broke,
    and bash's exit status.  At *deadline* the process group is killed, and the
    block that was running is the first one reported as not reaching its end."""
    begin = re.compile(re.escape(f"@@DOCEX:{nonce}:BEGIN:") + r"(\d+)@@")
    end = re.compile(
        re.escape(f"@@DOCEX:{nonce}:END:") + r"(\d+):(\d+):([^:@]*):([a-z]*)@@"
    )
    outcomes = [Outcome() for _ in blocks]
    state = {"current": None, "since": time.monotonic(), "size": 0}
    lock = threading.Lock()

    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as handle:
        handle.write(script)
        script_path = handle.name
    process = subprocess.Popen(
        [bash, "--noprofile", "--norc", script_path],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
        env=env,
        start_new_session=True,
        text=True,
        errors="replace",
    )

    def read(stream, which):
        current = None
        for line in stream:
            with lock:
                state["size"] += len(line)
            started = begin.search(line)
            finished = end.search(line)
            if started:
                current = int(started.group(1))
                if which == "stdout":
                    with lock:
                        state["current"], state["since"] = current, time.monotonic()
                continue
            if finished:
                i = int(finished.group(1))
                if which == "stdout":
                    outcome = outcomes[i]
                    outcome.reached = True
                    outcome.rc = int(finished.group(2))
                    outcome.flags = finished.group(3)
                    outcome.pipefail = finished.group(4)
                current = None
                continue
            if current is not None:
                if which == "stdout":
                    outcomes[current].stdout += line
                else:
                    outcomes[current].stderr += line

    readers = [
        threading.Thread(target=read, args=(process.stdout, "stdout"), daemon=True),
        threading.Thread(target=read, args=(process.stderr, "stderr"), daemon=True),
    ]
    for reader in readers:
        reader.start()

    problem = None
    while process.poll() is None:
        time.sleep(0.2)
        with lock:
            current, since, size = state["current"], state["since"], state["size"]
        if size > OUTPUT_CAP:
            problem = f"output exceeded {OUTPUT_CAP} bytes; stopped"
        elif deadline is not None and deadline.reached():
            problem = (
                f"the run deadline ({deadline.describe()}) was reached; "
                "process group killed"
            )
        elif current is not None and time.monotonic() - since > blocks[current].timeout:
            problem = (
                f"block {current}: timed out after {blocks[current].timeout}s; "
                "process group killed"
            )
        if problem:
            _kill_group(process.pid)
            break
    rc = process.wait()
    _kill_group(process.pid)  # reap anything a block left running in the background
    for reader in readers:
        reader.join(READER_JOIN_SECONDS)
    if any(reader.is_alive() for reader in readers) and problem is None:
        problem = (
            "a process a block started kept the output open after bash exited "
            "(detached from the process group?)"
        )
    os.unlink(script_path)
    return outcomes, problem, rc


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


_WORD = re.compile(r"[A-Za-z0-9_]")


def find_expectation(text: str, expected: str, start: int = 0) -> int:
    """End offset of the first acceptable match of *expected* in *text*, or -1.

    A match may not begin or end inside a word: an edge of *expected* that is a
    word character must not touch another word character in *text*.
    """
    i = text.find(expected, start)
    while i != -1:
        before = text[i - 1] if i > 0 else ""
        after_at = i + len(expected)
        after = text[after_at] if after_at < len(text) else ""
        head_ok = not (_WORD.match(expected[0]) and before and _WORD.match(before))
        tail_ok = not (_WORD.match(expected[-1]) and after and _WORD.match(after))
        if head_ok and tail_ok:
            return after_at
        i = text.find(expected, i + 1)
    return -1


def judge(
    blocks: list[Block],
    outcomes: list[Outcome],
    problem: Optional[str],
    rc: int,
    name: str,
) -> list[str]:
    """Every way the run fell short of the page."""
    problems = []
    for i, (block, outcome) in enumerate(zip(blocks, outcomes)):
        where = f"{name}:{block.line}"
        tail = "\n".join((outcome.stdout + outcome.stderr).strip().split("\n")[-50:])
        if not outcome.reached:
            reason = problem or f"bash exited {rc}"
            problems.append(f"{where}: block did not reach its end ({reason})\n{tail}")
            reached = sum(o.reached for o in outcomes)
            problems.append(
                f"{name}: executed {reached}/{len(blocks)} exec blocks; "
                f"first not reached: {where}"
            )
            return problems
        if outcome.rc != 0:
            problems.append(f"{where}: block exited {outcome.rc}\n{tail}")
            continue
        if (
            "e" not in outcome.flags
            or "u" not in outcome.flags
            or outcome.pipefail != "pf"
        ):
            problems.append(
                f"{where}: block turned off strict mode ($-={outcome.flags}, {outcome.pipefail})"
            )
            continue
        position = 0
        for n, expected in enumerate(block.expects, 1):
            found = find_expectation(outcome.stdout, expected, position)
            if found == -1:
                problems.append(
                    f"{where}: expectation {n}/{len(block.expects)} not found: {expected}\n{tail}"
                )
                break
            position = found
        # The blocks exempt: the stack starts (Quick Start's, and the modules
        # page's full-profile one). When compose has to
        # build, it writes BuildKit's progress to stdout (nothing when the images
        # exist), so no expectation can hold on both paths; `--wait` failing unless
        # every service is healthy, and the next block's expectations, verify it.
        if (
            outcome.stdout.strip()
            and not block.expects
            and block.body.strip() not in (STACK_UP, STACK_FULL_UP)
        ):
            printed = "\n".join(outcome.stdout.strip().split("\n")[:20])
            problems.append(
                f"{where}: block printed output but carries no expectation; "
                f"its stdout began:\n{printed}"
            )
    if problem and not problems:
        problems.append(f"{name}: {problem}")
    if rc != 0 and not problems:
        problems.append(f"{name}: bash exited {rc} after every block reported success")
    return problems


def execute_counted(
    blocks: list[Block],
    name: str,
    env: dict[str, str],
    deadline: Optional[Deadline] = None,
) -> tuple[list[str], int]:
    """Run a document's exec blocks in one shell; the problems, and how many
    blocks reached their end (counted from the sentinels, not the enrolment)."""
    runnable = [b for b in blocks if b.kind == "exec"]
    if not runnable:
        return [], 0
    nonce = secrets.token_hex(8)
    bash = bash_executable(env)
    outcomes, problem, rc = run_script(
        write_script(runnable, nonce), runnable, env, bash, nonce, deadline
    )
    reached = sum(o.reached for o in outcomes)
    return judge(runnable, outcomes, problem, rc, name), reached


def execute(blocks: list[Block], name: str, env: dict[str, str]) -> list[str]:
    """Run a document's exec blocks in one shell; no Docker involved."""
    return execute_counted(blocks, name, env)[0]


# ---------------------------------------------------------------------------
# Docker: preflight, an isolated project per document, teardown, snapshot
# ---------------------------------------------------------------------------


def _docker(
    *args: str, env: Optional[dict] = None, timeout: int = 120
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        timeout=timeout,
        check=False,
    )


def _published_ports(env: dict[str, str]) -> list[int]:
    config = _docker("compose", "config", "--format", "json", env=env)
    if config.returncode != 0:
        raise Refused(f"docker compose config failed: {config.stderr.strip()[:300]}")
    ports = []
    for service in json.loads(config.stdout).get("services", {}).values():
        for port in service.get("ports", []):
            published = str(port.get("published", "")) if isinstance(port, dict) else ""
            if published.isdigit():
                ports.append(int(published))
    return sorted(set(ports))


def _port_in_use(port: int) -> bool:
    """Bound on either stack: a listener on ::1 only is invisible to 0.0.0.0."""
    for family, address in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            if family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            sock.bind((address, port))
        except OSError:
            return True
        finally:
            sock.close()
    return False


def _leftovers() -> dict[str, list[str]]:
    """Resources a previous run of this script left behind, by compose project."""
    label = '{{.Label "com.docker.compose.project"}}'
    found: dict[str, list[str]] = {}
    for what, args in (
        ("container", ("ps", "-a", "--format", "{{.Names}} " + label)),
        ("volume", ("volume", "ls", "--format", "{{.Name}} " + label)),
        ("network", ("network", "ls", "--format", "{{.Name}} " + label)),
    ):
        for line in _docker(*args).stdout.splitlines():
            name, _, project = line.partition(" ")
            if project.startswith("docex-"):
                found.setdefault(project, []).append(f"{what} {name}")
    return found


def preflight(env: dict[str, str]) -> None:
    """Refuse, touching nothing, unless a document can start a stack of its own."""
    for args in (("info",), ("compose", "version")):
        if _docker(*args).returncode != 0:
            raise Refused(f"`docker {' '.join(args)}` failed; is Docker running?")
    busy = [p for p in _published_ports(env) if _port_in_use(p)]
    if busy:
        raise Refused(
            f"port(s) {busy} are in use; the documents address the stack on those "
            "ports. Stop what holds them (a developer stack: `docker compose stop`)."
        )
    left = _leftovers()
    if left:
        commands = "; ".join(f"docker compose -p {p} down -v" for p in sorted(left))
        listed = ", ".join(r for resources in left.values() for r in resources)
        raise Refused(
            f"a previous run left {listed}; remove it with `{commands}` "
            "(this script never deletes what it did not start)"
        )


def project_resources(project: str) -> list[str]:
    label = f"label=com.docker.compose.project={project}"
    found = []
    for what, args in (
        ("container", ("ps", "-a", "-q", "--filter", label)),
        ("volume", ("volume", "ls", "-q", "--filter", label)),
        ("network", ("network", "ls", "-q", "--filter", label)),
    ):
        found += [f"{what} {x}" for x in _docker(*args).stdout.split()]
    return found


def _volumes() -> set[str]:
    return set(_docker("volume", "ls", "-q").stdout.split())


def _report_dropped(out) -> None:
    """Name (never show) what the caller had set that the documents will not see."""
    compose_file = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    interpolated = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)", compose_file))
    dropped = sorted(
        k
        for k in os.environ
        if k not in PASSED_ENV
        and (k in interpolated or k.startswith(("COMPOSE_", "EXPERIMENTLY_")))
    )
    if dropped:
        print(f"not passed to the documents: {', '.join(dropped)}", file=out)
    if (ROOT / ".env").exists():
        print("ignoring .env (COMPOSE_DISABLE_ENV_FILE=1)", file=out)


def run_bounded(
    argv: list[str],
    env: dict[str, str],
    timeout: int,
    deadline: Optional[Deadline] = None,
) -> tuple[Optional[int], str, str, Optional[str]]:
    """Run *argv* in a process group of its own; (rc, stdout, stderr, why).

    *why* is None when it finished, else why it was stopped: its own timeout,
    or the run deadline, whichever comes first.  The whole group is killed, so
    nothing it started (compose's plugins, a build) outlives it.
    """
    limit, why = float(timeout), f"timed out after {timeout}s"
    if deadline is not None and deadline.remaining() < limit:
        limit = max(0.0, deadline.remaining())
        why = f"the run deadline ({deadline.describe()}) was reached"
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
        env=env,
        start_new_session=True,
        text=True,
        errors="replace",
    )
    try:
        stdout, stderr = process.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        _kill_group(process.pid)
        stdout, stderr = process.communicate()
        return None, stdout, stderr, f"{why}; process group killed"
    return process.returncode, stdout, stderr, None


def _get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def full_profile_problem(rel: str, fetch: Callable[[str], object] = _get_json):
    """None when the running API says it is the full profile, else the problem."""
    try:
        answer = fetch(MODULES_URL)
    except (OSError, ValueError) as error:
        return (
            f"{rel}: the full profile did not load: GET {MODULES_URL} failed ({error})"
        )
    profile = answer.get("profile") if isinstance(answer, dict) else None
    if profile != "full":
        return (
            f"{rel}: the full profile did not load: GET /api/v1/modules says "
            f"profile {profile!r}"
        )
    return None


def run_document(
    doc: dict,
    blocks: list[Block],
    index: int,
    overrides: dict[str, str],
    stack_up: Optional[Block],
    out,
    deadline: Optional[Deadline] = None,
    stack_full_up: Optional[Block] = None,
) -> tuple[list[str], int]:
    """The page's problems, and how many of its exec blocks reached their end."""
    rel = doc["path"]
    project = f"docex-{secrets.token_hex(4)}-{index}"
    env = scrubbed_env(project, overrides)
    preflight(env)
    print(f"{rel}: running under compose project {project}", file=out)
    problems: list[str] = []
    reached = 0
    starts = {
        "stack": (STACK_UP, stack_up),
        "stack-full": (STACK_FULL_UP, stack_full_up),
    }
    try:
        if doc["environment"] in starts:
            command, source = starts[doc["environment"]]
            rc, _, stderr, why = run_bounded(
                [bash_executable(env), "--noprofile", "--norc", "-c", command],
                env,
                source.timeout if source else DEFAULT_TIMEOUT,
                deadline,
            )
            if why or rc != 0:
                problems = [
                    f"{rel}: the stack did not start ({command}): "
                    f"{why or f'exit {rc}'}\n{stderr[-2000:]}"
                ]
                return problems, reached
            if doc["environment"] == "stack-full":
                problem = full_profile_problem(rel)
                if problem:
                    problems = [problem]
                    return problems, reached
        problems, reached = execute_counted(blocks, rel, env, deadline)
    finally:
        try:
            _docker(
                "compose",
                "down",
                "-v",
                "--remove-orphans",
                env=env,
                timeout=_teardown_seconds(deadline),
            )
        except subprocess.TimeoutExpired:
            problems.append(f"{rel}: teardown (docker compose down -v) timed out")
        left = project_resources(project)
        if left:
            problems.append(
                f"{rel}: isolation: resources remain after teardown: {left}"
            )
    return problems, reached


def run_verdict(doc: dict, problems: list[str], reached: int) -> tuple[str, list[str]]:
    """The line printed for a page that ran, and its problems.

    The number printed is the count of exec blocks that reached their end,
    measured from the sentinels; the enrolment's number is only what it is
    compared with (a block that silently stopped running would otherwise be
    reported as run).
    """
    rel, expected = doc["path"], doc["exec"]
    if reached != expected and not problems:
        problems = [
            f"{rel}: {reached} exec blocks reached their end; the enrolment says "
            f"{expected}"
        ]
    verdict = "passed" if not problems else "FAILED"
    return f"{rel}: {verdict} ({reached}/{expected} exec blocks ran)", problems


def _start_block(parsed: dict[str, list[Block]], doc: str, up: str) -> Optional[Block]:
    return next(
        (b for b in parsed.get(doc, []) if b.kind == "exec" and b.body.strip() == up),
        None,
    )


def run(
    path: Optional[pathlib.Path] = None,
    only: Optional[str] = None,
    overrides: Optional[dict[str, str]] = None,
    out=None,
    shard: Optional[Shard] = None,
    report: Optional[pathlib.Path] = None,
    deadline: Optional[Deadline] = None,
    clock: Callable[[], float] = time.monotonic,
    run_page: Optional[Callable] = None,
) -> None:
    """Run the pages that run (one shard of them, with *shard*).

    Prints each page's measured count and seconds, then the shard's measured
    total; with *report*, writes them for the summary, even when a page fails
    or the deadline stops the run.  *run_page* replaces ``run_document`` in
    tests (no Docker).
    """
    overrides = overrides or {}
    out = out or sys.stdout
    run_page = run_page or run_document
    check(path, out=out)  # the static contract first; nothing runs if it fails
    documents = load_enrolment(path)
    if only and only not in {d["path"] for d in documents}:
        raise Refused(f"{only} is not enrolled")
    selected = {d["path"] for d in documents if runs(d)}
    if shard is not None:
        plan = shard_plan(documents)
        if shard not in plan:
            raise Refused(
                f"shard {shard_label(shard)} is not in the plan "
                f"({', '.join(shard_label(s) for s in plan) or 'no shards'}); "
                "the matrix is stale or hand-written"
            )
        selected &= set(plan[shard])
    if only:
        selected &= {only}
    full = sorted(
        d["path"]
        for d in documents
        if d["path"] in selected and d["environment"] == "stack-full"
    )
    if full and not (ROOT / "modules").is_dir():
        raise Refused(
            f"{', '.join(full)}: needs the full profile, and this tree has no "
            "modules/ (a core tree); run a core shard"
        )
    parsed = {d["path"]: blocks_of(d["path"]) for d in documents}
    stack_up = _start_block(parsed, STACK_DOC, STACK_UP)
    stack_full_up = _start_block(parsed, STACK_FULL_DOC, STACK_FULL_UP)
    _report_dropped(out)
    print(f"bash: {bash_executable(scrubbed_env('docex-probe', overrides))}", file=out)
    label = f"shard {shard_label(shard)}" if shard else "all pages"
    if deadline is not None:
        print(
            f"{label}: run deadline {deadline.describe()} "
            f"({deadline.remaining():.0f} s from now)",
            file=out,
        )
    before = _volumes()
    problems: list[str] = []
    results: dict[str, dict] = {}
    stopped: Optional[str] = None
    try:
        for index, doc in enumerate(documents):
            if doc["path"] not in selected:
                continue
            rel = doc["path"]
            if stopped is None and deadline is not None and deadline.reached():
                stopped = (
                    f"the run deadline ({deadline.describe()}) was reached; the "
                    "pages after it did not start"
                )
            if stopped is not None:
                results[rel] = {
                    "exec": doc["exec"],
                    "reached": 0,
                    "passed": False,
                    "seconds": 0,
                }
                problems.append(f"{rel}: not run: {stopped}")
                print(f"{rel}: NOT RUN (run deadline)", file=out)
                continue
            started = clock()
            found, reached = run_page(
                doc,
                parsed[rel],
                index,
                overrides,
                stack_up,
                out,
                deadline,
                stack_full_up,
            )
            seconds = clock() - started
            line, found = run_verdict(doc, found, reached)
            print(f"{line} in {seconds:.1f}s", file=out)
            results[rel] = {
                "exec": doc["exec"],
                "reached": reached,
                "passed": not found,
                "seconds": round(seconds, 1),
            }
            problems += found
        if stopped is None and deadline is not None and deadline.reached():
            stopped = f"the run deadline ({deadline.describe()}) was reached"
        lost = sorted(before - _volumes())
        if lost:
            problems.append(f"volumes that existed before the run are gone: {lost}")
    finally:
        reached_total = sum(r["reached"] for r in results.values())
        enrolled_total = sum(r["exec"] for r in results.values())
        print(
            f"{label}: {len(results)} page(s), {reached_total} exec blocks reached "
            f"their end (measured); the enrolment says {enrolled_total} for these "
            "pages",
            file=out,
        )
        if report is not None:
            write_report(report, shard, results, stopped)
    if problems:
        raise Failed("\n\n".join(problems))


_WHERE = re.compile(r"^(?P<file>[^\s:]+\.(?:md|toml))(?::(?P<line>[0-9]+))?[: ]")


def _escape(text: str, prop: bool = False) -> str:
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


def report_refusal(refusal: Refused, err=None) -> None:
    """One ``refused:`` line per problem; in GitHub Actions, an annotation too."""
    err = err or sys.stderr
    annotate = os.environ.get("GITHUB_ACTIONS") == "true"
    for problem in refusal.problems:
        print(f"refused: {problem}", file=err)
        if annotate:
            where = _WHERE.match(problem)
            location = ""
            if where:
                location = f" file={_escape(where.group('file'), prop=True)}"
                if where.group("line"):
                    location += f",line={where.group('line')}"
            print(f"::error{location}::{_escape(problem)}", file=err)
    if len(refusal.problems) > 1:
        print(f"{len(refusal.problems)} problems", file=err)


def main(argv: Optional[list[str]] = None) -> int:
    # Progress is written line by line, so a job killed mid-run still shows the
    # page it was on (a pipe is block-buffered by default).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate tags and counts")
    mode.add_argument(
        "--render", metavar="SITE_DIR", type=pathlib.Path, help="check a built site"
    )
    mode.add_argument("--run", action="store_true", help="run the examples in Docker")
    mode.add_argument(
        "--plan", action="store_true", help="print the shards as a GitHub matrix"
    )
    mode.add_argument(
        "--summarise",
        metavar="DIR",
        type=pathlib.Path,
        help="check the shard reports under DIR",
    )
    mode.add_argument(
        "--bug-issues",
        action="store_true",
        help="print the issue numbers 'bug #N' skip reasons name",
    )
    parser.add_argument("--only", metavar="PATH", help="with --run: one enrolled page")
    parser.add_argument(
        "--shard", metavar="PROFILE:K/N", help="with --run: one shard of --plan"
    )
    parser.add_argument(
        "--report",
        metavar="FILE",
        type=pathlib.Path,
        help="with --run: write what was measured, for --summarise",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=f"with --run: set one of {', '.join(OVERRIDABLE)} for the documents",
    )
    args = parser.parse_args(argv)
    overrides = {}
    for item in args.env:
        name, _, value = item.partition("=")
        if name not in OVERRIDABLE or not value:
            print(
                f"refused: --env accepts only {', '.join(OVERRIDABLE)}", file=sys.stderr
            )
            return 2
        overrides[name] = value
        print(f"override: {name}={value}")
    if (args.shard or args.report) and not args.run:
        print("refused: --shard and --report go with --run", file=sys.stderr)
        return 2
    try:
        if args.check:
            check()
        elif args.render:
            render(args.render)
        elif args.plan:
            plan = shard_plan(load_enrolment())
            for shard, pages in plan.items():
                print(f"{shard_label(shard)}: {', '.join(pages)}", file=sys.stderr)
            print(json.dumps(matrix(plan), separators=(",", ":")))
        elif args.summarise:
            summarise(args.summarise)
        elif args.bug_issues:
            for number in bug_issues():
                print(number)
        else:
            shard = parse_shard(args.shard) if args.shard else None
            deadline = deadline_from_env()
            if (
                shard is not None
                and deadline is None
                and os.environ.get("GITHUB_ACTIONS") == "true"
            ):
                raise Refused(
                    "a shard in GitHub Actions needs its deadline: export "
                    "DOCEX_JOB_START and DOCEX_JOB_TIMEOUT_MINUTES"
                )
            run(
                only=args.only,
                overrides=overrides,
                shard=shard,
                report=args.report,
                deadline=deadline,
            )
    except Refused as refusal:
        report_refusal(refusal)
        return 2
    except Failed as failure:
        print(f"failed:\n{failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
