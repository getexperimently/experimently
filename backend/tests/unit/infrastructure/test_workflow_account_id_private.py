"""No workflow run prints the AWS account ID (Stream I, PE v1 F1 / C1).

The repository is public, so every Deploy, Rollback and Database Migration run
is too: its log, its annotations, its step summary and its run name. Three
things keep the account ID out of them, and this file pins each:

1. The account ID is an environment SECRET, never a variable. A step's log
   header prints its evaluated `env:` block before the step runs, so a
   variable's value is public before any `::add-mask::` could execute; the
   runner registers a secret for masking at the start of the job. So no file
   under `.github/` names `vars.AWS_ACCOUNT_ID`.
2. Every `aws-actions/configure-aws-credentials` step sets
   `mask-aws-account-id: true`, which masks the ASSUMED account -- the one the
   wrong-account check finds is not the configured one.
3. Whether the runner's mask also reaches annotations and step summaries is
   not something to rely on, so nothing a workflow writes to one interpolates
   a full ARN, an image reference with its registry host
   (`<account>.dkr.ecr...`) or the account itself: `${ARN##*/}` prints
   `family:revision` and `${IMAGE#*/}` prints `repository@sha256:...`. The
   static check below follows each value from where it enters a step (an
   `env:` whose name or source says it holds one, `get-caller-identity`, a
   `taskDefinition` or `.image` query) through the step's assignments, and
   fails on any summary or annotation line that prints one unstripped.

The behavioural half runs the summary- and annotation-writing steps as
written, with fake ARNs and images that carry a fake account ID, and greps
what they wrote for it. What GitHub itself does with a masked value in an
annotation, a summary or a run title is only observable on GitHub: the
fake-ID dispatch in Stream I S1 step 7 is that proof, and this file is not.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
GITHUB_DIR = REPO_ROOT / ".github"
WORKFLOWS = GITHUB_DIR / "workflows"
AWS_WORKFLOWS = [
    WORKFLOWS / name for name in ("deploy.yml", "rollback.yml", "db-migrate.yml")
]

pytestmark = pytest.mark.skipif(
    not WORKFLOWS.is_dir(), reason="this tree has no .github/workflows"
)

#: Fake account IDs the leak guard allowlists: the configured account, and
#: the "other" account a wrong role would assume.
ACCOUNT = "123456789012"
OTHER_ACCOUNT = "111111111111"


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["on"] = document.pop(True, document.get("on"))
    return document


def _workflow_files() -> list[Path]:
    return sorted(p for p in WORKFLOWS.iterdir() if p.suffix in (".yml", ".yaml"))


def _action_files() -> list[Path]:
    actions = GITHUB_DIR / "actions"
    if not actions.is_dir():
        return []
    return sorted(actions.rglob("action.y*ml"))


def _steps_of(path: Path) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(job id, job, step) for a workflow; ("", {}, step) for a composite action."""
    document = _load(path)
    if "jobs" in document:
        return [
            (name, job, step)
            for name, job in (document.get("jobs") or {}).items()
            for step in job.get("steps") or []
        ]
    return [("", {}, step) for step in (document.get("runs") or {}).get("steps") or []]


# --- 1. the account ID is a secret -----------------------------------------------


@pytest.mark.regression
def test_no_file_under_github_reads_the_account_id_from_a_variable():
    offenders = []
    for path in sorted(GITHUB_DIR.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if re.search(r"\bvars\s*\.\s*AWS_ACCOUNT_ID\b", line):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
                )
    assert not offenders, (
        "the account ID must be an environment SECRET: a variable's value is "
        "printed in the step's log header before anything can mask it\n"
        + "\n".join(offenders)
    )


@pytest.mark.regression
@pytest.mark.parametrize("path", AWS_WORKFLOWS, ids=lambda p: p.name)
def test_the_aws_workflows_read_the_account_id_from_the_secret(path):
    text = path.read_text(encoding="utf-8")
    assert "${{ secrets.AWS_ACCOUNT_ID }}" in text


# --- 2. the assumed account is masked --------------------------------------------


def _credential_steps() -> list[tuple[Path, dict[str, Any]]]:
    return [
        (path, step)
        for path in _workflow_files() + _action_files()
        for _, _, step in _steps_of(path)
        if str(step.get("uses", "")).startswith("aws-actions/configure-aws-credentials")
    ]


@pytest.mark.regression
def test_every_credentials_step_masks_the_account_id():
    steps = _credential_steps()
    # Not vacuous: deploy, rollback and db-migrate each assume a role.
    assert {p.name for p, _ in steps} >= {
        "deploy.yml",
        "rollback.yml",
        "db-migrate.yml",
    }
    unmasked = [
        f"{path.name}: {step.get('name', step.get('uses'))}"
        for path, step in steps
        if str((step.get("with") or {}).get("mask-aws-account-id", "")).lower()
        != "true"
    ]
    assert not unmasked, (
        "configure-aws-credentials does not mask the account ID by default; "
        f"set mask-aws-account-id: true on {unmasked}"
    )


# --- 3. no summary or annotation line prints a full ARN, an image, the account ---

#: An `env:` or GITHUB_ENV name that holds an ARN, an image or the account:
#: *IMAGE*, *ARN*, TASK_DEFINITION*, and the registry and the account
#: themselves. A name ending in one of the suffixes below holds something else
#: (IMAGE_TAG is `v1.2.3-full`; ROLE_ARN_SET is `true`).
SENSITIVE_NAME = re.compile(
    r"IMAGE|(?:^|_)ARNS?(?:_|$)|^TASK_DEFINITION|REGISTRY|ACCOUNT", re.IGNORECASE
)
NOT_SENSITIVE_SUFFIX = re.compile(
    r"_(TAG|DIGEST|SET|REUSED|OUTCOME|CHECK)$", re.IGNORECASE
)

#: Where a value holding one comes from, whatever it is called: a step output
#: or input that is an ARN or an image, the secret, `get-caller-identity`, and
#: an AWS query for a task definition or an image.
SENSITIVE_SOURCE = re.compile(
    r"outputs\.(arn|image|release_arn|serving_arn|serving_image|registry)\b"
    r"|task_definition_arn|secrets\.AWS_ACCOUNT_ID|get-caller-identity"
    r"|taskDefinition\b|taskDefinitionArn|\.image\b(?!\.)|\bregistry\b"
)

#: `${VAR#*/}` and `${VAR##*/}` strip the registry host and the ARN prefix.
STRIPS = {"#*/", "##*/"}

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: `name=` at the start of a statement: after the line's start, whitespace,
#: or a case arm's `)`.
_ASSIGNED = re.compile(r"(?:^|(?<=[\s)]))([A-Za-z_][A-Za-z0-9_]*)=")
_PRINTS = re.compile(r"(?:^|[;&|(){}]|\bthen|\belse|\bdo)\s*(?:echo|printf)\b")
_READ = re.compile(r"^\s*read\s+(?:-r\s+)?((?:[A-Za-z_][A-Za-z0-9_]*\s*)+)<<<(.*)$")
_SUMMARY_END = re.compile(r'^\}\s*>>\s*"?\$\{?GITHUB_STEP_SUMMARY\}?"?\s*$')
_ANNOTATION = re.compile(r"::(error|warning|notice)\b")


def _sensitive_name(name: str) -> bool:
    return bool(SENSITIVE_NAME.search(name)) and not NOT_SENSITIVE_SUFFIX.search(name)


def _closing_brace(text: str, start: int) -> int:
    """The index of the `}` closing the `${` at ``start``."""
    depth = 0
    i = start
    while i < len(text):
        if text.startswith("${", i):
            depth += 1
            i += 2
            continue
        if text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text)


def unstripped(text: str, tainted: set[str]) -> list[str]:
    """The tainted variables ``text`` expands without stripping them."""
    found: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("${", i):
            end = _closing_brace(text, i)
            body = text[i + 2 : end]
            i = end + 1
            if body.startswith("#"):
                continue  # ${#VAR} is a length
            match = _NAME.match(body)
            if not match:
                continue
            name, rest = match.group(0), body[match.end() :]
            if rest in STRIPS:
                continue
            if rest.startswith((":+", "+")):
                # ${VAR:+alt} prints alt, never VAR.
                found += unstripped(rest.lstrip(":+"), tainted)
                continue
            if name in tainted:
                found.append(name)
            if rest.startswith((":-", "-", ":=", "=")):
                found += unstripped(rest.lstrip(":-="), tainted)
            continue
        if text[i] == "$":
            match = _NAME.match(text, i + 1)
            if match:
                if match.group(0) in tainted:
                    found.append(match.group(0))
                i = match.end()
                continue
        i += 1
    return found


def _logical_lines(script: str) -> list[str]:
    """The script's lines, with backslash continuations joined."""
    lines: list[str] = []
    pending = ""
    for raw in script.splitlines():
        if raw.lstrip().startswith("#"):
            continue
        if raw.rstrip().endswith("\\"):
            pending += raw.rstrip()[:-1] + " "
            continue
        lines.append(pending + raw)
        pending = ""
    if pending:
        lines.append(pending)
    return lines


def _step_taint(env: dict[str, Any]) -> set[str]:
    tainted = set()
    for name, value in (env or {}).items():
        if _sensitive_name(name) or SENSITIVE_SOURCE.search(str(value)):
            tainted.add(name)
    return tainted


def _without_substitutions(text: str) -> str:
    """``text`` with every `$( ... )` removed (nested ones included)."""
    out, depth, i = [], 0, 0
    while i < len(text):
        if text.startswith("$(", i):
            depth += 1
            i += 2
            continue
        if depth and text[i] == "(":
            depth += 1
        elif depth and text[i] == ")":
            depth -= 1
            i += 1
            continue
        if not depth:
            out.append(text[i])
        i += 1
    return "".join(out)


def _value_taint(value: str, tainted: set[str]) -> bool:
    """Does an assigned value hold an ARN, an image or the account?

    A command substitution is judged by what it asks for (a sensitive source
    such as `.taskDefinitionArn`), not by its arguments: `status="$(jq -r
    '.status' <<<"$TD")"` is a status even though `$TD` holds an ARN.
    Outside substitutions, an unstripped tainted variable taints the value.
    """
    if SENSITIVE_SOURCE.search(value):
        return True
    return bool(unstripped(_without_substitutions(value), tainted))


def _read_taint(source: str, count: int, tainted: set[str]) -> list[bool]:
    """Per name of `read -r A B C <<<"$(aws ... --query '...[x, y, z]')"`."""
    fields = re.search(r"\.\[(.*)\]", source)
    if fields:
        depth, parts, current = 0, [], ""
        for char in fields.group(1):
            depth += char in "[("
            depth -= char in "])"
            if char == "," and depth == 0:
                parts.append(current)
                current = ""
            else:
                current += char
        parts.append(current)
        if len(parts) == count:
            return [bool(SENSITIVE_SOURCE.search(part)) for part in parts]
    return [_value_taint(source, tainted)] * count


def leaks(script: str, env: dict[str, Any]) -> list[str]:
    """Every summary or annotation line printing an unstripped sensitive value.

    Flow-sensitive in the order the lines are written: an assignment taints
    its variable when its right-hand side reads a sensitive source or expands
    a tainted variable unstripped, and clears it otherwise (so
    `primary="${primary##*/}"` makes `primary` printable). An UPPER_CASE name
    that is sensitive by name is tainted even when this step does not declare
    it, because GITHUB_ENV exports reach every later step undeclared.
    """
    tainted = _step_taint(env)
    found: list[str] = []
    in_summary = False
    lines = _logical_lines(script)
    for index, line in enumerate(lines):
        stripped = line.strip()
        # Undeclared, sensitively named UPPER_CASE names (GITHUB_ENV exports).
        for name in re.findall(r"\$\{?([A-Z_][A-Z0-9_]*)", line):
            if _sensitive_name(name):
                tainted.add(name)
        prints = bool(_PRINTS.search(stripped))
        read = _READ.match(line)
        if read:
            names = read.group(1).split()
            for name, verdict in zip(
                names, _read_taint(read.group(2), len(names), tainted)
            ):
                (tainted.add if verdict else tainted.discard)(name)
        elif not prints:
            # `a="$x" b="$y"`, `1) why="..." ;;`: each name gets the verdict
            # of its own value, which runs to the next assignment.
            matches = list(_ASSIGNED.finditer(line))
            for n, match in enumerate(matches):
                end = matches[n + 1].start() if n + 1 < len(matches) else len(line)
                value = line[match.end() : end]
                if _value_taint(value, tainted):
                    tainted.add(match.group(1))
                else:
                    tainted.discard(match.group(1))
        if stripped == "{":
            # A group is a summary only when it is redirected to one.
            closing = next(
                (x for x in lines[index + 1 :] if x.strip().startswith("}")), ""
            )
            in_summary = bool(_SUMMARY_END.match(closing.strip()))
            continue
        if stripped.startswith("}"):
            in_summary = False
            continue
        is_summary = in_summary or "GITHUB_STEP_SUMMARY" in line
        if prints and (is_summary or _ANNOTATION.search(line)):
            if "GITHUB_OUTPUT" in line or "GITHUB_ENV" in line:
                continue
            # A `$( ... )` prints its output: judged by what it asks AWS for.
            names = unstripped(_without_substitutions(line), tainted)
            if SENSITIVE_SOURCE.search(line) and not SENSITIVE_SOURCE.search(
                _without_substitutions(line)
            ):
                names.append("$(...)")
            if names:
                found.append(f"{sorted(set(names))}: {stripped[:160]}")
    return found


def _summary_leaks(path: Path) -> list[str]:
    document = _load(path)
    offenders = []
    for job_name, job, step in _steps_of(path):
        if "run" not in step:
            continue
        env = {
            **(document.get("env") or {}),
            **(job.get("env") or {}),
            **(step.get("env") or {}),
        }
        for leak in leaks(step["run"], env):
            offenders.append(f"{path.name} / {job_name} / {step.get('name')}: {leak}")
    return offenders


@pytest.mark.regression
@pytest.mark.parametrize(
    "path", _workflow_files() + _action_files(), ids=lambda p: p.name
)
def test_no_summary_or_annotation_prints_an_arn_an_image_or_the_account(path):
    offenders = _summary_leaks(path)
    assert not offenders, (
        "a step summary or annotation interpolates a full ARN, an image with its "
        "registry host, or the account ID; print ${ARN##*/} (family:revision) "
        "or ${IMAGE#*/} (repository@sha256:...) instead\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    "script, env, expected",
    [
        ('echo "::error::$ARN is bad"', {}, ["ARN"]),
        ('echo "::error::${ARN##*/} is bad"', {}, []),
        (
            '{\n  echo "| Image | ${IMAGE:-none} |"\n} >> "$GITHUB_STEP_SUMMARY"',
            {},
            ["IMAGE"],
        ),
        ('{\n  echo "| Image | ${IMAGE#*/} |"\n} >> "$GITHUB_STEP_SUMMARY"', {}, []),
        ('echo "| Tag | ${IMAGE_TAG} |" >> "$GITHUB_STEP_SUMMARY"', {}, []),
        (
            'x="${PREVIOUS:-none}"\necho "::warning::${x}"',
            {"PREVIOUS": "${{ steps.previous.outputs.arn }}"},
            ["x"],
        ),
        (
            'x="${PREVIOUS##*/}"\necho "::warning::${x:-none}"',
            {"PREVIOUS": "${{ steps.previous.outputs.arn }}"},
            [],
        ),
        (
            'p="$(aws ecs describe-services --query taskDefinition)"\n'
            'p="${p##*/}"\necho "::error::on ${p}"',
            {},
            [],
        ),
        (
            'echo "::error::expected ${EXPECTED_ACCOUNT_ID}"',
            {},
            ["EXPECTED_ACCOUNT_ID"],
        ),
        (
            'actual="$(aws sts get-caller-identity)"\necho "::error::in ${actual}"',
            {},
            ["actual"],
        ),
        ('echo "::error::${ARN:+an ARN was given}"', {}, []),
        (
            'TD="$(aws ecs describe-task-definition --query taskDefinition)"\n'
            'status="$(jq -r \'.status\' <<<"$TD")"\n'
            'echo "::error::it is $status"',
            {},
            [],
        ),
        (
            'read -r SERVING RUNNING <<<"$(aws ecs describe-services --query '
            '"services[0].[taskSets[?status==\'PRIMARY\'].taskDefinition | [0], runningCount]")"\n'
            'echo "::error::$RUNNING running"\n'
            'echo "::error::serving $SERVING"',
            {},
            ["SERVING"],
        ),
        (
            '{\n  echo "image=$IMAGE"\n} >> "$GITHUB_OUTPUT"',
            {"IMAGE": "${{ steps.image.outputs.image }}"},
            [],
        ),
        (
            '1) why="on $TARGET" ;;\necho "::error::${why}"',
            {"TARGET": "${{ inputs.task_definition_arn }}"},
            ["why"],
        ),
        (
            '*) echo "::error::$REF is bad" ;;',
            {"REF": "${{ steps.x.outputs.image }}"},
            ["REF"],
        ),
    ],
    ids=[
        "bare-arn",
        "stripped-arn",
        "image-in-summary",
        "stripped-image",
        "image-tag-is-not-an-image",
        "tainted-through-an-assignment",
        "stripped-through-an-assignment",
        "restripped-local",
        "exported-account",
        "caller-identity",
        "alternate-value-only",
        "a-field-read-from-a-tainted-json-is-not-tainted",
        "read-taints-by-position",
        "an-output-group-is-not-a-summary",
        "a-case-arm-assignment",
        "an-echo-in-a-case-arm",
    ],
)
def test_the_leak_check_itself(script, env, expected):
    """The static check's own cases: it fires on each shape, and only on them."""
    found = leaks(script, env)
    if expected:
        assert found and all(any(n in f for n in expected) for f in found), found
    else:
        assert found == [], found


@pytest.mark.regression
def test_no_run_name_or_job_name_interpolates_an_arn_or_an_image():
    """A run's title is public and is never masked."""
    offenders = []
    for path in _workflow_files():
        document = _load(path)
        names = [("run-name", document.get("run-name", ""))]
        names += [
            (f"jobs.{j}.name", job.get("name", ""))
            for j, job in document["jobs"].items()
        ]
        for where, value in names:
            for expression in re.findall(r"\$\{\{(.*?)\}\}", str(value)):
                if re.search(r"arn|image|account", expression, re.IGNORECASE):
                    offenders.append(f"{path.name} {where}: {expression.strip()}")
    assert not offenders, offenders


#: In a `uses:` step's `with:` value -- which the step's log header prints,
#: resolved -- an expression that yields an ARN, an image or the account: an
#: input named for one, a step output that holds one, or an `env.` name that
#: is sensitive by name. Secrets are masked by the runner and not listed.
WITH_SENSITIVE = re.compile(
    r"\binputs\.[A-Za-z0-9_-]*(?:arn|image)[A-Za-z0-9_-]*"
    r"|\bsteps\.[A-Za-z0-9_-]+\.outputs\."
    r"(?:arn|image|release_arn|serving_arn|serving_image|registry|expect)\b",
    re.IGNORECASE,
)


def _env_sensitive(name: str, env: dict[str, Any]) -> bool:
    """`env.NAME` yields an ARN, an image or the account.

    Judged by its definition where the workflow gives one (`REGISTRY:
    ghcr.io` is a literal, not an account's registry), and by its name where
    it does not (a GITHUB_ENV export).
    """
    if name not in env:
        return _sensitive_name(name)
    value = str(env[name])
    if SENSITIVE_SOURCE.search(value):
        return True
    return _sensitive_name(name) and "${{" in value


def with_leaks(step: dict[str, Any], env: dict[str, Any] | None = None) -> list[str]:
    """The `with:` values of a `uses:` step that interpolate an ARN or image."""
    env = {**(env or {}), **(step.get("env") or {})}
    found = []
    for key, value in (step.get("with") or {}).items():
        for expression in re.findall(r"\$\{\{(.*?)\}\}", str(value), re.DOTALL):
            names = [
                n
                for n in re.findall(r"\benv\.([A-Za-z0-9_]+)", expression)
                if _env_sensitive(n, env)
            ]
            if WITH_SENSITIVE.search(expression) or names:
                found.append(f"{key}: ${{{{{expression.strip()}}}}}")
    return found


@pytest.mark.regression
@pytest.mark.parametrize(
    "path", _workflow_files() + _action_files(), ids=lambda p: p.name
)
def test_no_uses_step_passes_an_arn_or_an_image_in_its_with_block(path):
    """A `uses:` step's log header prints its resolved `with:` values."""
    workflow_env = _load(path).get("env") or {}
    offenders = [
        f"{path.name} / {job} / {step.get('name', step.get('uses'))}: {leak}"
        for job, job_def, step in _steps_of(path)
        if "uses" in step
        for leak in with_leaks(step, {**workflow_env, **(job_def.get("env") or {})})
    ]
    assert not offenders, (
        "pass family:revision from an earlier step's output instead\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    "with_block, leaks_expected",
    [
        ({"slack-message": "to `${{ inputs.task_definition_arn }}`"}, True),
        (
            {"slack-message": "`${{ inputs.dashboard_task_definition_arn || 'x' }}`"},
            True,
        ),
        ({"slack-message": "`${{ steps.target.outputs.arn }}`"}, True),
        ({"slack-message": "`${{ steps.web-image.outputs.image }}`"}, True),
        ({"image": "${{ env.DASHBOARD_IMAGE }}"}, True),
        ({"slack-message": "`${{ steps.shown.outputs.target }}`"}, False),
        ({"role-to-assume": "${{ secrets.AWS_ROLE_ARN }}"}, False),
        (
            {
                "stack": "${{ env.FARGATE_STACK }}",
                "environment": "${{ inputs.environment }}",
            },
            False,
        ),
    ],
)
def test_the_with_check_itself(with_block, leaks_expected):
    assert bool(with_leaks({"uses": "x/y@v1", "with": with_block})) is leaks_expected


@pytest.mark.regression
def test_the_slack_steps_get_family_revision_from_a_full_arn(tmp_path):
    """The step the Slack blocks read: a full ARN in, family:revision out."""
    arn = f"arn:aws:ecs:us-west-2:{ACCOUNT}:task-definition/experimentation-backend-staging:41"
    dash = f"arn:aws:ecs:us-west-2:{ACCOUNT}:task-definition/experimentation-dashboard-staging:7"
    code, log, _ = run_step(
        tmp_path,
        ROLLBACK,
        "Name the revisions without the account",
        TARGET=arn,
        DASHBOARD_TARGET=dash,
    )
    assert code == 0, log
    output = (tmp_path / "output").read_text()
    assert "target=experimentation-backend-staging:41\n" in output
    assert "dashboard=experimentation-dashboard-staging:7\n" in output
    assert ACCOUNT not in output + log
    slack = [
        step
        for step in _environment_job(ROLLBACK)["steps"]
        if str(step.get("uses", "")).startswith("slackapi/")
    ]
    assert len(slack) == 2
    assert all(
        "steps.shown.outputs.target" in step["with"]["slack-message"] for step in slack
    )


@pytest.mark.regression
def test_the_rollback_error_dump_is_scrubbed(tmp_path):
    """The Failed/Stopped branch prints get-deployment's JSON through `scrub`."""
    step = _step(ROLLBACK, "Shift traffic and wait for it to land")
    assert "--output json" in step["run"]
    assert (
        '|| echo "(its error information could not be read)"; } | scrub' in step["run"]
    )
    assert step["run"].count('last_error="$(scrub <<<"$last_error")"') == 1
    stop = _step(ROLLBACK, "Stop any deployment already in flight")
    assert stop["run"].count('last_error="$(scrub <<<"$last_error")"') == 1
    # And run it: a Failed deployment whose error names the account.
    code, log, _ = run_step(
        tmp_path,
        ROLLBACK,
        "Shift traffic and wait for it to land",
        DEPLOYMENT_ID="d-TEST",
        ROLLBACK_TIMEOUT_SECONDS="30",
    )
    assert code == 1, log
    assert "is not authorized" in log and "<account>" in log, log
    assert ACCOUNT not in log, log


# --- the behavioural half: run the printing steps with a fake account -------------

_EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def _fake_value(key: str, expression: str) -> str:
    family = (
        "dashboard" if "DASHBOARD" in key or "dashboard" in expression else "backend"
    )
    arn = f"arn:aws:ecs:us-west-2:{ACCOUNT}:task-definition/experimentation-{family}-staging:41"
    repo = "web" if family == "dashboard" else "backend"
    image = (
        f"{ACCOUNT}.dkr.ecr.us-west-2.amazonaws.com/experimentation-platform/{repo}"
        "@sha256:" + "c" * 64
    )
    if expression == "inputs.environment":
        return "staging"
    if re.search(
        r"outputs\.(arn|release_arn|serving_arn)\b|task_definition_arn", expression
    ):
        return arn
    if re.search(r"outputs\.(image|serving_image)\b", expression):
        return image
    if re.search(r"outputs\.registry\b", expression):
        return f"{ACCOUNT}.dkr.ecr.us-west-2.amazonaws.com"
    if "secrets.AWS_ACCOUNT_ID" in expression:
        return ACCOUNT
    if expression.endswith(".outputs.digest"):
        return "sha256:" + "d" * 64
    if expression.endswith(".outputs.tag"):
        return "v0.7.0-full"
    if expression.endswith(".outcome"):
        return "success"
    if expression == "job.status":
        return "failure"
    if expression.startswith("inputs.override_alarms") and "reason" not in expression:
        return "false"
    return f"fake-{key.lower()}"


def _resolve(key: str, value: Any) -> str:
    text = str(value)
    return _EXPR.sub(lambda m: _fake_value(key, m.group(1)), text)


def _environment_job(path: Path) -> dict[str, Any]:
    (job,) = [j for j in _load(path)["jobs"].values() if "environment" in j]
    return job


def _step(path: Path, name: str) -> dict[str, Any]:
    (step,) = [s for s in _environment_job(path)["steps"] if s.get("name") == name]
    return step


FAKE_AWS = f"""#!/bin/sh
# get-caller-identity: the assumed role is in another account. get-deployment:
# a Failed deployment whose error names a role ARN.
case "$*" in
  *get-caller-identity*) echo "${{FAKE_CALLER:-{OTHER_ACCOUNT}}}"; exit 0 ;;
  *"deploy get-deployment"*"deploymentInfo.status "*) echo Failed; exit 0 ;;
  *"deploy get-deployment"*"errorInformation.code"*) echo HEALTH_CONSTRAINTS; exit 0 ;;
  *"deploy get-deployment"*"status:status"*)
    echo '{{"status": "Failed", "error": {{"message": "User: arn:aws:sts::{ACCOUNT}:assumed-role/deploy/x is not authorized"}}}}'
    exit 0 ;;
esac
echo "fake aws: unexpected call $*" >&2
exit 99
"""


def run_step(tmp_path: Path, path: Path, name: str, **overrides: str):
    """Run one step's script as the runner does; return (code, log, summary)."""
    document = _load(path)
    job = _environment_job(path)
    step = _step(path, name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "aws"
    fake.write_text(FAKE_AWS)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    summary = tmp_path / "summary.md"
    summary.write_text("")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "GITHUB_"))}
    for scope in (
        document.get("env") or {},
        job.get("env") or {},
        step.get("env") or {},
    ):
        env.update({k: _resolve(k, v) for k, v in scope.items()})
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
        GITHUB_STEP_SUMMARY=str(summary),
        GITHUB_OUTPUT=str(tmp_path / "output"),
        GITHUB_ENV=str(tmp_path / "env"),
        GITHUB_ACTOR="someone",
        # The first step's GITHUB_ENV export reaches every later step.
        EXPECTED_ACCOUNT_ID=ACCOUNT,
        AWS_CONFIG_FILE="/dev/null",
        AWS_SHARED_CREDENTIALS_FILE="/dev/null",
    )
    env.update(overrides)
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, result.stdout + result.stderr, summary.read_text()


DEPLOY, ROLLBACK, MIGRATE = AWS_WORKFLOWS

#: The steps that print a summary or an annotation without calling AWS, with
#: the input combinations that reach their branches.
PRINTING_STEPS = [
    (DEPLOY, "Run summary", {}),
    (DEPLOY, "Run summary", {"SHIFT_RESULT": "alarm", "APPROVED": "true"}),
    (DEPLOY, "Run summary", {"SHIFT_RESULT": "alarm", "APPROVED": ""}),
    (DEPLOY, "Run summary", {"ALARM_AFTER_SHIFT": "true"}),
    (DEPLOY, "Run summary", {"OVERRIDE_ALARMS": "true"}),
    (DEPLOY, "Run summary", {"PREVIOUS_DASHBOARD_RELEASE": "", "ROLLOUT": ""}),
    (DEPLOY, "If the migration was applied and the shift was never approved", {}),
    (DEPLOY, "If the migration was applied and the shift was approved", {}),
    (DEPLOY, "If an alarm rolled the API back", {"APPROVED": "false"}),
    (DEPLOY, "If an alarm rolled the API back", {"APPROVED": "true", "PREVIOUS": ""}),
    (
        DEPLOY,
        "If the API was deployed and the dashboard was not",
        {"GUARD": "0", "RECHECK": "", "ROLLOUT": ""},
    ),
    (ROLLBACK, "Run summary", {"DASHBOARD_OUTCOME": "success"}),
    (ROLLBACK, "Run summary", {"DASHBOARD_INPUT": "", "DASHBOARD_OUTCOME": "skipped"}),
    (ROLLBACK, "Run summary", {"REFUSED": "codeDeployRollback"}),
    (ROLLBACK, "Refuse a rollback to the revision already serving", {}),
    (MIGRATE, "Run summary", {}),
    (MIGRATE, "Run summary", {"ACCOUNT_CHECK": "failure"}),
]


@pytest.mark.regression
@pytest.mark.parametrize(
    "path, name, overrides",
    PRINTING_STEPS,
    ids=[f"{p.stem}:{n}:{i}" for i, (p, n, _) in enumerate(PRINTING_STEPS)],
)
def test_the_printing_steps_print_no_account_id(tmp_path, path, name, overrides):
    code, log, summary = run_step(tmp_path, path, name, **overrides)
    assert "unexpected call" not in log, log
    # Not vacuous: each wrote something, and the fakes were in its inputs.
    assert (summary + log).strip(), (code, log)
    assert ACCOUNT not in summary, summary
    assert ACCOUNT not in log, log
    assert "dkr.ecr" not in summary + log


@pytest.mark.regression
@pytest.mark.parametrize("path", AWS_WORKFLOWS, ids=lambda p: p.name)
def test_the_wrong_account_refusal_names_neither_account(tmp_path, path):
    code, log, _ = run_step(tmp_path, path, "Refuse the wrong AWS account")
    assert code == 1, log
    assert "Wrong AWS account" in log
    assert ACCOUNT not in log and OTHER_ACCOUNT not in log, log


@pytest.mark.parametrize("path", AWS_WORKFLOWS, ids=lambda p: p.name)
def test_the_right_account_passes_without_printing_it(tmp_path, path):
    code, log, _ = run_step(
        tmp_path, path, "Refuse the wrong AWS account", FAKE_CALLER=ACCOUNT
    )
    assert code == 0, log
    assert ACCOUNT not in log, log


@pytest.mark.regression
def test_the_summaries_say_the_account_matches_rather_than_print_it(tmp_path):
    for path in AWS_WORKFLOWS:
        _, _, summary = run_step(tmp_path, path, "Run summary", ACCOUNT_CHECK="success")
        assert (
            "| Account / region | matches the environment's AWS_ACCOUNT_ID secret / `us-west-2` |"
            in summary
        ), (path.name, summary)


@pytest.mark.regression
def test_the_rollback_run_name_carries_no_revision():
    run_name = _load(ROLLBACK)["run-name"]
    assert "task_definition_arn" not in run_name
    assert "dashboard_task_definition_arn" not in run_name


@pytest.mark.regression
def test_the_scripts_print_revisions_and_images_without_the_account(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import public_text
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))
    arn = f"arn:aws:ecs:us-west-2:{ACCOUNT}:task-definition/experimentation-backend-staging:41"
    group = f"arn:aws:elasticloadbalancing:us-west-2:{ACCOUNT}:targetgroup/exp-Blue/0123456789abcdef"
    image = (
        f"{ACCOUNT}.dkr.ecr.us-west-2.amazonaws.com/experimentation-platform/web@sha256:"
        + "e" * 64
    )
    assert public_text.short_arn(arn) == "experimentation-backend-staging:41"
    assert public_text.short_arn(group) == "targetgroup/exp-Blue/0123456789abcdef"
    assert (
        public_text.short_image(image)
        == "experimentation-platform/web@sha256:" + "e" * 64
    )
    assert public_text.short_image("experimentation-platform/web:bootstrap") == (
        "experimentation-platform/web:bootstrap"
    )
    denied = f"User: arn:aws:sts::{ACCOUNT}:assumed-role/deploy/x is not authorized"
    assert ACCOUNT not in public_text.redact(denied)
    # A digest is hex and a timestamp is longer: neither is an account.
    assert public_text.redact("sha256:" + "1" * 64) == "sha256:" + "1" * 64
    assert public_text.redact("20260927123456") == "20260927123456"
