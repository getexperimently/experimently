"""A docs-only pull request reports every required check -- and still runs the docs tests.

Branch protection requires ``core-build``, ``full-build`` and
``SDK Live Contract / sdk-live-contract (core)``. All three used to be skipped
by a job-level ``if: needs.changes.outputs.docs_only != 'true'`` and, unlike a
plain job, neither skip reports under the required name: a matrix job skipped
before it expands reports once as the literal ``${{ matrix.profile }}-build``,
and a skipped reusable-workflow caller reports only as ``SDK Live Contract``.
#133 (``docs/auth/sso.md`` only) sat BLOCKED with every check that ran green.

So those two jobs always run and every STEP is conditioned instead. These are
YAML reads, not greps, and they pin the exact condition on every step, so a
new step that is not classified here fails until it is:

* ``profile-build``: every build step ``docs_only != 'true'``; on a docs-only
  change the core leg alone checks out, sets up Python and runs the tests that
  pin ``docs/`` content (``DOCS_TESTS``);
* ``_platform.yml``: a ``skip`` input, every step's condition starting with
  ``!inputs.skip`` inside ``${{ }}`` (a bare leading ``!`` is a YAML tag);
* the three sources of the required check names;
* ``git diff --no-renames`` in the ``changes`` job, without which
  ``git mv backend/a.py docs/a.py`` lists only ``docs/a.py``.

The classification itself is tested in
``backend/tests/unit/scripts/test_classify_changes.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GATE = WORKFLOWS / "pr-qa-gate.yml"
PLATFORM = WORKFLOWS / "_platform.yml"

#: A distribution that does not ship the workflows has nothing here to check.
if not GATE.is_file() or not PLATFORM.is_file():
    pytest.skip("this tree has no .github/workflows", allow_module_level=True)

NOT_DOCS = "needs.changes.outputs.docs_only != 'true'"
DOCS = "needs.changes.outputs.docs_only == 'true'"
CORE = "matrix.profile == 'core'"

#: Every step of profile-build, by name (or `uses:` when unnamed), and its
#: exact `if:`. Insertion order is the step order.
PROFILE_BUILD_STEPS: Dict[str, Optional[str]] = {
    "Docs-only change": DOCS,
    "actions/checkout@v7": f"{NOT_DOCS} || {CORE}",
    "Set up Python": f"{NOT_DOCS} || {CORE}",
    "Install backend dependencies (docs tests)": f"{DOCS} && {CORE}",
    "Docs content tests": f"{DOCS} && {CORE}",
    "Set up Node.js": NOT_DOCS,
    "Install backend dependencies": NOT_DOCS,
    "Install module dependencies": f"{NOT_DOCS} && matrix.profile == 'full'",
    "Install gitleaks": NOT_DOCS,
    "${{ matrix.profile }} build": NOT_DOCS,
}

#: Every step of _platform.yml's job and its exact `if:`.
PLATFORM_STEPS: Dict[str, str] = {
    "Skipped": "${{ inputs.skip }}",
    "actions/checkout@v7": "${{ !inputs.skip }}",
    "Make the core profile real": "${{ !inputs.skip && inputs.profile == 'core' }}",
    "Set up Python": "${{ !inputs.skip }}",
    "Set up Node.js": (
        "${{ !inputs.skip && (contains(inputs.sdks, 'js') || "
        "contains(inputs.sdks, 'react') || contains(inputs.sdks, 'edge') || "
        "contains(inputs.sdks, 'openfeature')) }}"
    ),
    "Set up Go": "${{ !inputs.skip && contains(inputs.sdks, 'go') }}",
    "Set up Java": (
        "${{ !inputs.skip && (contains(inputs.sdks, 'java') || "
        "contains(inputs.sdks, 'android')) }}"
    ),
    "Set up Ruby": "${{ !inputs.skip && contains(inputs.sdks, 'ruby') }}",
    "Set up PHP": "${{ !inputs.skip && contains(inputs.sdks, 'php') }}",
    "Set up .NET": "${{ !inputs.skip && contains(inputs.sdks, 'dotnet') }}",
    "Install backend dependencies": "${{ !inputs.skip }}",
    "Install module dependencies": "${{ !inputs.skip && inputs.profile == 'full' }}",
    "Install SDK dependencies": (
        "${{ !inputs.skip && inputs.suite == 'sdk-live-contract' }}"
    ),
    "Create the schema": "${{ !inputs.skip }}",
    "Apply seeds": "${{ !inputs.skip && inputs.seed != '' }}",
    "Start the API": "${{ !inputs.skip }}",
    "Assert the running profile": "${{ !inputs.skip }}",
    "Run suite": "${{ !inputs.skip }}",
    "Backend log (on failure)": "${{ !inputs.skip && failure() }}",
}

#: The tests that read docs/ content and so must run on the pull request that
#: changes docs/ alone. On any other change unit-tests / smoke-tests run them.
DOCS_TESTS = (
    "backend/tests/unit/scripts/test_doc_examples.py",
    "backend/tests/unit/docs/",
    "backend/tests/smoke/test_openapi_snapshot.py",
    "backend/tests/smoke/test_version_sources.py",
    "backend/tests/unit/infrastructure/test_dashboard_image_docs.py",
    "backend/tests/unit/infrastructure/test_rollback_uses_codedeploy.py",
    "backend/tests/unit/db/test_alembic_plan.py",
)

#: Python tests that name docs/ but are deliberately NOT in DOCS_TESTS.
NOT_DOCS_TESTS = {
    # Reads only docs/api/stability.md, and docs/api/** is never docs-only
    # (scripts/classify_changes.py), so a change there runs unit-tests.
    "backend/tests/unit/scripts/test_makefile_guards.py": "docs/api only",
    # Hands the classifier path STRINGS such as "docs/a.py"; opens no file.
    "backend/tests/unit/scripts/test_classify_changes.py": "fixture strings only",
}
# Not Python, so not scanned here, and not run on a docs-only change:
# frontend/src/tests/services/docs-links.test.ts (DOCS_ROOT built from
# __dirname) checks every docsUrl() link addresses a page under docs/. Deleting
# or renaming a linked page on a docs-only pull request is NOT caught before
# merge. Recorded as a residual in the plan; running it needs Node and npm ci.
# The real-tree scan in test_leak_guard.py reads docs/ through `git ls-files`;
# the required Leak Guard workflow runs the same guard on every pull request.

#: A test that reads docs/: the directory as a quoted path segment, a quoted
#: path under it, or the site config. Catches `REPO_ROOT / "docs" / ...` and
#: `Path("docs")`, not only the literal "docs/...".
DOCS_READER = re.compile(r"""["']docs["']|["']docs/|mkdocs\.yml""")


class _NoDuplicateKeys(yaml.SafeLoader):
    """safe_load keeps the LAST of two `if:` keys silently; this refuses."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise AssertionError(
                    f"duplicate key {key!r} at line {key_node.start_mark.line + 1}"
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _load(path: Path) -> Dict[str, Any]:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_NoDuplicateKeys)


def _key(step: Dict[str, Any]) -> str:
    return step.get("name") or step["uses"]


def _conditions(steps: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    keys = [_key(s) for s in steps]
    assert len(keys) == len(set(keys)), f"two steps share a name: {keys}"
    return {_key(s): s.get("if") for s in steps}


@pytest.fixture(scope="module")
def gate() -> Dict[str, Any]:
    return _load(GATE)


@pytest.fixture(scope="module")
def platform() -> Dict[str, Any]:
    return _load(PLATFORM)


# ---------------------------------------------------------------------------
# The classification input
# ---------------------------------------------------------------------------
class TestTheChangesJob:
    def _run(self, gate) -> str:
        (step,) = [
            s for s in gate["jobs"]["changes"]["steps"] if s.get("id") == "check"
        ]
        return step["run"]

    def test_the_diff_does_not_detect_renames(self, gate):
        """Without it, `git mv backend/a.py docs/a.py` lists only docs/a.py."""
        diffs = [line for line in self._run(gate).splitlines() if "git diff" in line]
        assert diffs, "the changes job no longer runs git diff"
        for line in diffs:
            assert "git diff --no-renames --name-only" in line, line

    def test_the_diff_feeds_the_classifier_into_github_output(self, gate):
        run = self._run(gate)
        assert (
            'git diff --no-renames --name-only "$BASE" "$HEAD" '
            '| python3 scripts/classify_changes.py >> "$GITHUB_OUTPUT"'
        ) in run
        assert "set -euo pipefail" in run, "a failing git diff must fail the job"

    def test_the_output_is_wired(self, gate):
        outputs = gate["jobs"]["changes"]["outputs"]
        assert outputs == {"docs_only": "${{ steps.check.outputs.docs_only }}"}


# ---------------------------------------------------------------------------
# No job-level skip on a job whose check name protection cannot see skipped
# ---------------------------------------------------------------------------
class TestNoJobLevelSkip:
    @pytest.mark.parametrize("job", ["profile-build", "sdk-live-contract"])
    def test_the_two_jobs_have_no_job_level_if(self, gate, job):
        assert "if" not in gate["jobs"][job], (
            f"{job} has a job-level if: again. Skipped, it never reports its "
            "required check name and every docs-only pull request is BLOCKED."
        )

    def test_no_matrix_or_reusable_job_skips_on_docs_only(self, gate):
        """The same trap for any job added later in either shape."""
        for name, job in gate["jobs"].items():
            if "strategy" in job or "uses" in job:
                assert "docs_only" not in str(job.get("if", "")), name


# ---------------------------------------------------------------------------
# The three sources of the required check names
# ---------------------------------------------------------------------------
class TestTheRequiredCheckNames:
    def test_the_matrix_name_expands_to_core_build_and_full_build(self, gate):
        job = gate["jobs"]["profile-build"]
        assert job["name"] == "${{ matrix.profile }}-build"
        profiles = [row["profile"] for row in job["strategy"]["matrix"]["include"]]
        assert profiles == ["core", "full"]

    def test_the_caller_is_named_sdk_live_contract(self, gate):
        job = gate["jobs"]["sdk-live-contract"]
        assert job["name"] == "SDK Live Contract"
        assert job["uses"] == "./.github/workflows/_platform.yml"
        assert job["with"]["profile"] == "core"
        assert job["with"]["suite"] == "sdk-live-contract"

    def test_the_callee_job_is_named_suite_and_profile(self, platform):
        jobs = platform["jobs"]
        assert list(jobs) == ["platform"]
        assert jobs["platform"]["name"] == "${{ inputs.suite }} (${{ inputs.profile }})"
        assert "if" not in jobs["platform"]


# ---------------------------------------------------------------------------
# profile-build: every step conditioned, docs tests in the core leg
# ---------------------------------------------------------------------------
class TestProfileBuildSteps:
    def test_every_step_has_exactly_its_condition(self, gate):
        actual = _conditions(gate["jobs"]["profile-build"]["steps"])
        assert list(actual.items()) == list(PROFILE_BUILD_STEPS.items())

    def test_the_build_itself_is_the_core_build_script(self, gate):
        steps = {_key(s): s for s in gate["jobs"]["profile-build"]["steps"]}
        run = steps["${{ matrix.profile }} build"]["run"]
        assert run.startswith("scripts/core_build.sh --profile ${{ matrix.profile }}")

    def test_the_skip_reason_is_printed(self, gate):
        first = gate["jobs"]["profile-build"]["steps"][0]
        assert "docs-only change" in first["run"]

    def test_the_docs_tests_are_exactly_the_list(self, gate):
        steps = {_key(s): s for s in gate["jobs"]["profile-build"]["steps"]}
        words = steps["Docs content tests"]["run"].split()
        assert words[:3] == ["python", "-m", "pytest"]
        assert tuple(w for w in words if w.startswith("backend/")) == DOCS_TESTS
        install = steps["Install backend dependencies (docs tests)"]["run"]
        assert install.strip() == "pip install -r backend/requirements.txt"

    @pytest.mark.parametrize("path", DOCS_TESTS)
    def test_every_docs_test_exists(self, path):
        assert (REPO_ROOT / path).exists(), f"{path} is gone: the step would error"

    def test_every_python_docs_reader_is_classified(self):
        """A new test that reads docs/ is either in DOCS_TESTS or excused.

        Found by the path shape, including paths composed from a root
        constant (`REPO_ROOT / "docs" / ...`), not by the literal string.
        """
        roots = [
            REPO_ROOT / "backend" / "tests",
            REPO_ROOT / "modules" / "backend" / "tests",
        ]
        readers = set()
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*.py"):
                if DOCS_READER.search(
                    path.read_text(encoding="utf-8", errors="replace")
                ):
                    readers.add(path.relative_to(REPO_ROOT).as_posix())
        assert readers, "the scan found nothing: it is broken, not clean"

        def covered(rel: str) -> bool:
            if rel == Path(__file__).relative_to(REPO_ROOT).as_posix():
                return True
            if rel in NOT_DOCS_TESTS:
                return True
            return any(
                rel == t or (t.endswith("/") and rel.startswith(t)) for t in DOCS_TESTS
            )

        unclassified = sorted(r for r in readers if not covered(r))
        assert not unclassified, (
            "these tests read docs/ but a docs-only pull request would not run "
            f"them: add them to DOCS_TESTS and the workflow step, or to "
            f"NOT_DOCS_TESTS with the reason: {unclassified}"
        )


# ---------------------------------------------------------------------------
# _platform.yml: the skip input
# ---------------------------------------------------------------------------
class TestPlatformSkip:
    def test_skip_is_a_boolean_input_defaulting_to_false(self, platform):
        # PyYAML reads the `on:` key as True.
        inputs = platform[True]["workflow_call"]["inputs"]
        assert inputs["skip"]["type"] == "boolean"
        assert inputs["skip"]["default"] is False

    def test_the_caller_passes_docs_only_as_skip(self, gate):
        assert gate["jobs"]["sdk-live-contract"]["with"]["skip"] == (
            "${{ needs.changes.outputs.docs_only == 'true' }}"
        )

    def test_every_step_has_exactly_its_condition(self, platform):
        actual = _conditions(platform["jobs"]["platform"]["steps"])
        assert list(actual.items()) == list(PLATFORM_STEPS.items())

    def test_every_work_step_starts_with_not_skip(self, platform):
        """Belt and braces over the exact table: the shape of each condition."""
        steps = platform["jobs"]["platform"]["steps"]
        assert steps[0]["if"] == "${{ inputs.skip }}"
        for step in steps[1:]:
            cond = step.get("if", "")
            assert cond.startswith("${{ !inputs.skip") and cond.endswith("}}"), _key(
                step
            )
            assert cond.count("${{") == 1, f"{_key(step)}: nested expression {cond}"
