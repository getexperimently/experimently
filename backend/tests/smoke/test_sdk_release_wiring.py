"""Every SDK in the tree is accounted for by the release plumbing.

``scripts/check_sdk_version.py``'s ``ECOSYSTEMS`` map and
``.github/workflows/sdk-release.yml`` both enumerate SDKs by name.  A
hand-typed list of names beside a directory that grows is the repository's most
frequent defect: a list that was complete when it was written, silently
incomplete a month later, and green the whole time because nothing compares it
to the thing it lists.

So compare it.  A new ``sdk/<name>/`` fails these tests until someone has said
how it is published -- including "not yet", which is a real answer that the
gate then enforces by refusing its tags.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SDK_DIR = ROOT / "sdk"
WORKFLOW = ROOT / ".github" / "workflows" / "sdk-release.yml"

pytestmark = pytest.mark.smoke


def sdk_directories() -> set[str]:
    """Every SDK in the tree.

    A directory under ``sdk/`` holding a manifest or source, not the shared
    files that sit beside them (``sdk/LICENSE`` is a file, and anything
    starting with a dot or an underscore is tooling).
    """
    return {
        entry.name
        for entry in SDK_DIR.iterdir()
        if entry.is_dir() and not entry.name.startswith((".", "_"))
    }


def ecosystems() -> dict[str, str]:
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        "check_sdk_version", ROOT / "scripts" / "check_sdk_version.py"
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.ECOSYSTEMS)


def test_every_sdk_directory_has_an_ecosystem() -> None:
    directories = sdk_directories()
    mapped = set(ecosystems())
    unmapped = directories - mapped
    assert not unmapped, (
        f"sdk/{{{','.join(sorted(unmapped))}}} exist but "
        "scripts/check_sdk_version.py does not say how they are published. "
        "Add them to ECOSYSTEMS -- 'unwired' is a valid answer and refuses "
        "their tags until an account exists."
    )


def test_no_ecosystem_entry_without_a_directory() -> None:
    """The other direction: a name left behind after a rename publishes nothing."""
    stale = set(ecosystems()) - sdk_directories()
    assert not stale, (
        f"ECOSYSTEMS names {sorted(stale)}, which are not directories under sdk/"
    )


@pytest.mark.parametrize("sdk", sorted(sdk_directories()))
def test_wired_sdks_report_a_version_and_unwired_ones_refuse(sdk: str) -> None:
    """Each SDK behaves the way its ecosystem says it should.

    ``pypi``/``npm`` must yield a version from their own manifest; ``tag-only``
    (Go) needs no manifest; ``unwired`` must *fail*, so that tagging one is a
    loud refusal rather than a workflow that quietly publishes nothing.
    """
    ecosystem = ecosystems()[sdk]
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_sdk_version.py"), sdk],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if ecosystem == "unwired":
        assert result.returncode != 0, (
            f"sdk/{sdk} is marked unwired but the gate accepted it: {result.stdout}"
        )
        assert "no publishing identity" in result.stderr
    else:
        assert result.returncode == 0, (
            f"sdk/{sdk} ({ecosystem}) failed its own check: {result.stderr}"
        )


@pytest.mark.parametrize(
    "sdk", sorted(name for name, eco in ecosystems().items() if eco in {"pypi", "npm"})
)
def test_a_mismatched_tag_is_refused(sdk: str) -> None:
    """The gate's whole job: a tag that does not match the manifest."""
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_sdk_version.py"),
            sdk,
            "--expect",
            "99.99.99",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        f"sdk/{sdk} accepted a tag of 99.99.99: {result.stdout}"
    )


def test_every_ecosystem_has_a_job_that_runs_for_it() -> None:
    """Each ecosystem in ECOSYSTEMS is reachable by a job in sdk-release.yml.

    The first version of this test searched the workflow *text* for ``sdk/js``
    and friends. That passed on the header comments alone: the jobs are gated
    on the resolved ``ecosystem``, not on SDK names, so deleting a comment
    broke it and deleting the whole ``npm:`` job did not. It was also a bare
    substring search, which ``sdk/openfeature-python`` satisfied for
    ``sdk/openfeature``. Two ways to pass for the wrong reason in six lines --
    the most frequent defect class in this repository: a check that passes
    for the wrong reason.

    So parse the YAML and read the conditions the jobs actually carry. If an
    SDK resolves to an ecosystem no job selects, its tag passes the version
    gate and then finds nothing to run: a green workflow that published
    nothing.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    conditions = " ".join(str(job.get("if", "")) for job in workflow["jobs"].values())

    # 'unwired' is the one ecosystem with no job on purpose: check_sdk_version.py
    # refuses those tags in `resolve`, before any publish job is reached.
    needed = {eco for eco in ecosystems().values() if eco != "unwired"}
    missing = {eco for eco in needed if f"'{eco}'" not in conditions}
    assert not missing, (
        f"no job in sdk-release.yml runs for ecosystem(s) {sorted(missing)}; "
        f"the job conditions are: {conditions!r}"
    )


def test_unwired_sdks_have_no_publish_job() -> None:
    """The other direction: 'unwired' must not be selectable by any job.

    A job gated on ``ecosystem == 'unwired'`` would publish an SDK whose
    registry account does not exist, which is the state `resolve` refuses
    outright.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for name, job in workflow["jobs"].items():
        assert "'unwired'" not in str(job.get("if", "")), (
            f"job {name!r} selects the 'unwired' ecosystem"
        )


def test_the_resolve_job_runs_the_version_gate() -> None:
    """`resolve` must actually call check_sdk_version.py.

    Everything else here assumes the workflow refuses a mismatched tag. It
    does that by running the script; a `resolve` that stopped would leave the
    version check to nothing at all.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["resolve"]["steps"]
    commands = " ".join(str(step.get("run", "")) for step in steps)
    assert "scripts/check_sdk_version.py" in commands
    assert "--expect" in commands, (
        "resolve runs check_sdk_version.py but without --expect, so it never "
        "compares the tag to the manifest"
    )


# --------------------------------------------------------------------------
# #687: the npm job publishes the tarball it checked, with registry ranges
# --------------------------------------------------------------------------

PACKED_TGZ = "${{ steps.pack.outputs.tgz }}"


def _npm_steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["npm"]["steps"]


def _index(steps: list[dict], what: str, predicate) -> int:
    found = [i for i in range(len(steps)) if predicate(steps[i])]
    assert len(found) == 1, (
        f"expected exactly one npm-job step that {what}, found {len(found)}: "
        f"{[steps[i].get('name') for i in found]}"
    )
    return found[0]


def _run_of(step: dict) -> str:
    return str(step.get("run", ""))


@pytest.mark.regression
def test_the_npm_job_pins_checks_and_publishes_the_checked_tarball() -> None:
    """#687: pin -> npm view -> pack -> check the packed package.json ->
    consumer install -> publish that same tarball, in that order.

    On the old job none of these steps existed and ``npm publish`` packed the
    source manifest, ``file:../js`` and all.
    """
    steps = _npm_steps()

    pin = _index(
        steps,
        "runs the pin script on the SDK directory",
        lambda s: (
            'scripts/pin_npm_local_deps.py "sdk/' in _run_of(s)
            and "--rewrites-file" in _run_of(s)
        ),
    )
    view = _index(steps, "runs npm view", lambda s: "npm view" in _run_of(s))
    pack = _index(
        steps,
        "packs",
        lambda s: "npm pack" in _run_of(s) and "--dry-run" not in _run_of(s),
    )
    check = _index(
        steps,
        "checks the packed package.json",
        lambda s: "--check-only" in _run_of(s),
    )
    consumer = _index(
        steps, "runs npm ls --all", lambda s: "npm ls --all" in _run_of(s)
    )
    publish = _index(steps, "runs npm publish", lambda s: "npm publish" in _run_of(s))

    order = [pin, view, pack, check, consumer, publish]
    assert order == sorted(order), (
        "the npm job must run, in order: pin, npm view, npm pack, --check-only, "
        f"the consumer install, npm publish; indices were {order}"
    )

    # The pin step feeds the npm view step's condition and its list.
    assert steps[pin].get("id") == "pin"
    assert "rewritten=" in _run_of(steps[pin])
    assert steps[view].get("if") == "steps.pin.outputs.rewritten != '0'"
    assert '"$RUNNER_TEMP/rewrites.txt"' in _run_of(steps[view])
    assert "|| true" not in _run_of(steps[view])
    assert "continue-on-error" not in steps[view]

    # The check reads package/package.json out of the packed tarball itself.
    assert steps[pack].get("id") == "pack"
    assert "tgz=" in _run_of(steps[pack])
    check_run = _run_of(steps[check])
    assert 'tar -xzf "$TGZ"' in check_run and "package/package.json" in check_run
    assert '--check-only "$out/package/package.json"' in check_run

    # The consumer installs that tarball alone, runs no lifecycle scripts, and
    # takes peers at the versions in the SDK's lock.
    consumer_run = _run_of(steps[consumer])
    assert "--ignore-scripts" in consumer_run
    assert (
        'npm install --ignore-scripts --no-audit --no-fund "$TGZ" $peers'
        in consumer_run
    )
    assert "--print-peer-pins" in consumer_run

    # And publishing is of that same tarball, not a fresh pack of the directory.
    assert _run_of(steps[publish]).startswith('npm publish "$TGZ"')
    for i in (check, consumer, publish):
        assert (steps[i].get("env") or {}).get("TGZ") == PACKED_TGZ, steps[i].get(
            "name"
        )
    for i in (pin, view, pack, check, consumer, publish):
        assert "continue-on-error" not in steps[i], steps[i].get("name")


# --------------------------------------------------------------------------
# #775: every npm SDK names this repository, so provenance can be attached
# --------------------------------------------------------------------------

REPOSITORY_URL = "https://github.com/getexperimently/experimently"


def npm_sdks() -> list[str]:
    return sorted(name for name, eco in ecosystems().items() if eco == "npm")


def test_the_npm_list_is_not_empty() -> None:
    """The parametrised test below is vacuous if no SDK resolves to npm."""
    assert npm_sdks(), "ECOSYSTEMS names no npm SDK"


@pytest.mark.regression
@pytest.mark.parametrize("sdk", npm_sdks())
def test_every_npm_sdk_names_its_repository(sdk: str) -> None:
    """#775: ``npm publish --provenance`` compares ``repository.url`` with the
    repository that ran the workflow, and refuses a package that names none.

    sdk/edge and sdk/react carried no ``repository`` at all, so their first
    publish would have failed at the very last step. The URL is compared
    exactly, in one form for every package, and ``directory`` must be the
    package's own folder.
    """
    import json

    manifest = json.loads((SDK_DIR / sdk / "package.json").read_text(encoding="utf-8"))
    repository = manifest.get("repository")
    assert isinstance(repository, dict), (
        f"sdk/{sdk}/package.json has no repository object: {repository!r}"
    )
    assert repository.get("type") == "git", repository
    assert repository.get("url") == REPOSITORY_URL, (
        f"sdk/{sdk}/package.json repository.url is {repository.get('url')!r}, "
        f"expected {REPOSITORY_URL!r}"
    )
    assert repository.get("directory") == f"sdk/{sdk}", (
        f"sdk/{sdk}/package.json repository.directory is "
        f"{repository.get('directory')!r}, expected 'sdk/{sdk}'"
    )


# --------------------------------------------------------------------------
# #773: a job that installs or tests cannot request an OIDC token, and the
# publish job checks the package it uploads against the tag
# --------------------------------------------------------------------------
#
# Two sets carry the change in progress, and both are exact, so that neither
# half of it can be undone without a test going red:
#
#   UNSPLIT_TOKEN_JOBS  jobs that still install or test while holding
#                       `id-token: write`. Only `npm`, until it is split the
#                       way PyPI is; then this becomes the empty set.
#   PUBLISH_JOBS        jobs split out to hold the token and publish only.
#                       `pypi` now; `npm` joins it when that job is split.

UNSPLIT_TOKEN_JOBS = {"npm"}
PUBLISH_JOBS = {"pypi"}
RELEASE_ENVIRONMENT = "sdk-release"

#: A step whose `run:` installs packages, runs a test suite or builds one.
INSTALLS_OR_TESTS = re.compile(
    r"\bnpm\s+(ci|install|test|run)\b"
    r"|\bpip3?\s+install\b|-m\s+pip\s+install\b"
    r"|\bpytest\b|-m\s+build\b|\btwine\b"
)
EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
PYPA_PIN = re.compile(r"pypa/gh-action-pypi-publish@([0-9a-f]{40})")


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _effective_permissions(workflow: dict, job: dict):
    """A job with no `permissions:` block inherits the workflow's."""
    if "permissions" in job:
        return job["permissions"]
    return workflow.get("permissions")


def _can_request_oidc(permissions) -> bool:
    if permissions == "write-all":
        return True
    return isinstance(permissions, dict) and permissions.get("id-token") == "write"


def _installs_or_tests(job: dict) -> bool:
    return any(INSTALLS_OR_TESTS.search(_run_of(step)) for step in job.get("steps", []))


def _step(job: str, name: str) -> dict:
    steps = [s for s in _workflow()["jobs"][job]["steps"] if s.get("name") == name]
    assert len(steps) == 1, (
        f"expected one {job!r} step named {name!r}, found {len(steps)}"
    )
    return steps[0]


@pytest.mark.regression
def test_no_job_that_installs_or_tests_can_request_an_oidc_token() -> None:
    """B1. Effective permissions, so a workflow-level grant is seen too.

    On the old file both `pypi` and `npm` installed, tested and held
    `id-token: write`. The set is exact: it fails if the PyPI split is undone,
    and again once npm is split and the set is not emptied with it.
    """
    workflow = _workflow()
    holding = {
        name
        for name, job in workflow["jobs"].items()
        if _installs_or_tests(job)
        and _can_request_oidc(_effective_permissions(workflow, job))
    }
    assert holding == UNSPLIT_TOKEN_JOBS, (
        f"jobs that install or test and can request an OIDC token: "
        f"{sorted(holding)}; expected exactly {sorted(UNSPLIT_TOKEN_JOBS)}"
    )


def test_the_release_environment_and_the_token_sit_on_the_publish_jobs_only() -> None:
    """B3. The approval and the token belong to the jobs that publish."""
    workflow = _workflow()
    expected = PUBLISH_JOBS | UNSPLIT_TOKEN_JOBS
    with_environment = set()
    with_token = set()
    for name, job in workflow["jobs"].items():
        environment = job.get("environment")
        if isinstance(environment, dict):
            environment = environment.get("name")
        if environment is not None:
            assert environment == RELEASE_ENVIRONMENT, (name, environment)
            with_environment.add(name)
        if _can_request_oidc(_effective_permissions(workflow, job)):
            with_token.add(name)
    assert with_environment == expected, (
        f"jobs in the {RELEASE_ENVIRONMENT!r} environment: {sorted(with_environment)}; "
        f"expected exactly {sorted(expected)}"
    )
    assert with_token == expected, (
        f"jobs that can request an OIDC token: {sorted(with_token)}; "
        f"expected exactly {sorted(expected)}"
    )


def test_no_publish_job_run_block_contains_an_expression() -> None:
    """C3. In a publish job, values reach a script through `env:` only."""
    jobs = _workflow()["jobs"]
    assert PUBLISH_JOBS <= set(jobs), sorted(PUBLISH_JOBS - set(jobs))
    found = [
        (name, step.get("name") or step.get("uses"))
        for name in sorted(PUBLISH_JOBS)
        for step in jobs[name]["steps"]
        if "${{" in _run_of(step)
    ]
    assert not found, f"a publish-job run: block contains ${{{{ }}}}: {found}"


def test_the_pypi_build_and_publish_jobs_are_a_pair() -> None:
    """B11. Same condition; the publish job needs the build; the build job
    keeps every check it had and cannot request a token."""
    workflow = _workflow()
    build = workflow["jobs"]["pypi-build"]
    publish = workflow["jobs"]["pypi"]
    condition = "needs.resolve.outputs.ecosystem == 'pypi'"
    assert build.get("if") == condition
    assert publish.get("if") == condition
    assert build.get("needs") == "resolve"
    assert set(publish.get("needs") or []) == {"resolve", "pypi-build"}
    assert build.get("permissions") == {"contents": "read"}
    assert "environment" not in build
    assert publish.get("name") == "publish to PyPI"

    names = [s.get("name") or s.get("uses") for s in build["steps"]]
    order = [
        "Run the SDK's tests",
        "Build",
        "Check the distributions",
        "Built version matches the tag",
        "Record the distributions",
        "Upload the checked distributions",
    ]
    indices = [names.index(n) for n in order]
    assert indices == sorted(indices), f"pypi-build steps out of order: {names}"
    assert "twine check dist/*" in _run_of(build["steps"][names.index(order[2])])


def test_the_pypi_publish_job_runs_only_the_download_the_check_and_the_upload() -> None:
    """B2. Exactly three steps; no checkout, no Python set-up, no install."""
    publish = _workflow()["jobs"]["pypi"]
    steps = publish["steps"]
    assert [s.get("name") for s in steps[:2]] == [
        "Download the checked distributions",
        "Check the distributions against the tag",
    ], [s.get("name") or s.get("uses") for s in steps]
    assert len(steps) == 3, [s.get("name") or s.get("uses") for s in steps]

    download, check, upload = steps
    assert download.get("uses") == "actions/download-artifact@v8"
    assert download.get("with") == {
        "name": "pypi-dist",
        "path": "${{ github.workspace }}/dist",
    }
    assert "run" not in download

    assert "uses" not in check
    assert "working-directory" not in check
    assert _run_of(check).startswith("set -euo pipefail\npython3 - <<'PY'\n")
    assert not INSTALLS_OR_TESTS.search(_run_of(check))

    assert PYPA_PIN.fullmatch(str(upload.get("uses"))), upload.get("uses")
    assert upload.get("with") == {"packages-dir": "dist/"}
    assert set(upload) == {"uses", "with"}


def test_the_pypa_action_is_pinned_to_a_commit_with_its_version() -> None:
    """The publish action runs beside the token: a full commit SHA, not a
    branch, with the version it is in a comment for the reader."""
    lines = [
        line
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if "pypa/gh-action-pypi-publish@" in line and not line.lstrip().startswith("#")
    ]
    assert len(lines) == 1, lines
    assert re.search(
        r"uses: pypa/gh-action-pypi-publish@[0-9a-f]{40} # v\d+\.\d+\.\d+$", lines[0]
    ), lines[0]


def test_the_publish_job_compares_with_the_digest_the_build_job_recorded() -> None:
    """B4. The expected digest comes from the build job's output, not from a
    file that travels in the same artifact."""
    workflow = _workflow()
    build = workflow["jobs"]["pypi-build"]
    assert build.get("outputs") == {"digest": "${{ steps.record.outputs.digest }}"}
    record = _step("pypi-build", "Record the distributions")
    assert record.get("id") == "record"
    assert "digest=" in _run_of(record)

    check = _step("pypi", "Check the distributions against the tag")
    assert check.get("env") == {
        "NAME": "${{ needs.resolve.outputs.name }}",
        "VERSION": "${{ needs.resolve.outputs.version }}",
        "DIGEST": "${{ needs.pypi-build.outputs.digest }}",
    }
    script = _run_of(check)
    assert 'os.environ["DIGEST"]' in script
    assert "if digest != expected_digest:" in script


def test_the_distributions_are_uploaded_once_and_never_overwritten() -> None:
    """B5. An empty upload fails the build job; an existing artifact of the
    same name is not replaced."""
    upload = _step("pypi-build", "Upload the checked distributions")
    assert upload.get("uses") == "actions/upload-artifact@v7"
    assert upload.get("with") == {
        "name": "pypi-dist",
        "path": "sdk/${{ needs.resolve.outputs.sdk }}/dist/",
        "if-no-files-found": "error",
        "overwrite": False,
    }


# The steps' scripts, run the way the runner runs them: bash -eo pipefail,
# with `env:` resolved from the values given and `python3`/`python` this
# interpreter. A copy of the idea in test_dashboard_deploy_wiring.py's Runner,
# cut down to what these steps use, rather than an import of it: that one
# fakes aws and curl, which nothing here calls.


def _run_step(
    step: dict, values: dict[str, str], tmp_path: Path, cwd: Path
) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("python3", "python"):
        if not (bin_dir / name).exists():
            (bin_dir / name).symlink_to(sys.executable)
    output = tmp_path / "github_output"
    output.touch()

    def resolve(match: re.Match) -> str:
        expression = match.group(1)
        assert expression in values, f"no value for ${{{{ {expression} }}}}"
        return values[expression]

    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_WORKSPACE": str(tmp_path / "workspace"),
        "HOME": str(tmp_path),
    }
    for key, value in (step.get("env") or {}).items():
        env[key] = EXPRESSION.sub(resolve, str(value))
    script = tmp_path / "step.sh"
    script.write_text(_run_of(step), encoding="utf-8")
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _outputs(tmp_path: Path) -> dict[str, str]:
    lines = (tmp_path / "github_output").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def _dist_files(project: str, version: str) -> dict[str, bytes]:
    stem = re.sub(r"[-_.]+", "_", project).lower()
    return {
        f"{stem}-{version}-py3-none-any.whl": f"wheel {project} {version}".encode(),
        f"{stem}-{version}.tar.gz": f"sdist {project} {version}".encode(),
    }


def _record(tmp_path: Path, files: dict[str, bytes]) -> str:
    """Run the build job's record step over `files`; return its digest."""
    sdk = tmp_path / "sdk"
    (sdk / "dist").mkdir(parents=True)
    for name, data in files.items():
        (sdk / "dist" / name).write_bytes(data)
    result = _run_step(
        _step("pypi-build", "Record the distributions"), {}, tmp_path, sdk
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return _outputs(tmp_path)["digest"]


def _check(
    tmp_path: Path, files: dict[str, bytes], name: str, version: str, digest: str
) -> subprocess.CompletedProcess:
    """Run the publish job's check over `files` in $GITHUB_WORKSPACE/dist."""
    dist = tmp_path / "workspace" / "dist"
    dist.mkdir(parents=True)
    for filename, data in files.items():
        (dist / filename).write_bytes(data)
    return _run_step(
        _step("pypi", "Check the distributions against the tag"),
        {
            "needs.resolve.outputs.name": name,
            "needs.resolve.outputs.version": version,
            "needs.pypi-build.outputs.digest": digest,
        },
        tmp_path,
        tmp_path / "workspace",
    )


@pytest.mark.parametrize("project", ["experimently", "experimently-openfeature"])
def test_the_check_accepts_what_the_build_job_recorded(
    project: str, tmp_path: Path
) -> None:
    files = _dist_files(project, "0.1.0")
    digest = _record(tmp_path, files)
    result = _check(tmp_path, files, project, "0.1.0", digest)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"2 file(s) for {project} 0.1.0" in result.stdout


SIBLING_WHEEL = "experimently_openfeature-0.1.0-py3-none-any.whl"


#: Each case is checked twice over: the build job recording a digest of the
#: changed set (so the digest agrees and only the name, version and file
#: checks stand between it and the upload), and the original set.
REFUSALS = [
    (
        "a same-version wheel of the sibling project",
        lambda f: {**f, SIBLING_WHEEL: b"sibling"},
        f"{SIBLING_WHEEL} is for 'experimently_openfeature', not 'experimently'",
    ),
    (
        "a same-version sdist of the sibling project",
        lambda f: {**f, "experimently_openfeature-0.1.0.tar.gz": b"sibling"},
        "is for 'experimently_openfeature', not 'experimently'",
    ),
    (
        "a wheel at another version",
        lambda f: {**f, "experimently-0.0.9-py3-none-any.whl": b"old"},
        "is version '0.0.9', not '0.1.0'",
    ),
    (
        "a stray file",
        lambda f: {**f, "notes.txt": b"x"},
        "notes.txt is neither a wheel nor an sdist",
    ),
    (
        "a digest file beside the distributions",
        lambda f: {**f, "SHA256SUMS": b"x"},
        "SHA256SUMS is neither a wheel nor an sdist",
    ),
]


@pytest.mark.parametrize("recorded", ["the changed set", "the original set"])
@pytest.mark.parametrize(
    ("case", "change", "refusal"),
    REFUSALS,
    ids=[case for case, _, _ in REFUSALS],
)
def test_the_check_refuses(
    case: str, change, refusal: str, recorded: str, tmp_path: Path
) -> None:
    """Condition 4: each of these must stop the upload, whichever set the
    build job's digest describes."""
    files = _dist_files("experimently", "0.1.0")
    changed = change(files)
    digest = _record(
        tmp_path / "build", changed if recorded == "the changed set" else files
    )
    result = _check(tmp_path / "publish", changed, "experimently", "0.1.0", digest)
    assert result.returncode == 1, (case, result.stdout, result.stderr)
    assert refusal in result.stdout, (case, result.stdout)


def test_the_check_refuses_a_byte_changed_after_the_digest_was_recorded(
    tmp_path: Path,
) -> None:
    """B4: the harness flips one byte of the wheel between the two jobs."""
    files = _dist_files("experimently", "0.1.0")
    digest = _record(tmp_path / "build", files)
    flipped = {
        name: (data[:-1] + bytes([data[-1] ^ 1]) if name.endswith(".whl") else data)
        for name, data in files.items()
    }
    result = _check(tmp_path / "publish", flipped, "experimently", "0.1.0", digest)
    assert result.returncode == 1, result.stdout
    assert "the downloaded files have digest" in result.stdout, result.stdout
    assert f"the build job recorded {digest}" in result.stdout, result.stdout


def test_the_check_refuses_an_empty_download(tmp_path: Path) -> None:
    """B5: no files is a refusal, not a vacuous pass."""
    digest = _record(tmp_path / "build", _dist_files("experimently", "0.1.0"))
    result = _check(tmp_path / "publish", {}, "experimently", "0.1.0", digest)
    assert result.returncode == 1, result.stdout
    assert "nothing was downloaded into" in result.stdout, result.stdout


def test_the_check_refuses_a_missing_digest(tmp_path: Path) -> None:
    files = _dist_files("experimently", "0.1.0")
    result = _check(tmp_path, files, "experimently", "0.1.0", "")
    assert result.returncode == 1, result.stdout
    assert "the build job recorded no usable digest" in result.stdout


def test_the_check_compares_the_whole_normalised_name(tmp_path: Path) -> None:
    """`Experimently.OpenFeature` and `experimently_openfeature` are one
    project under PEP 503; `experimently` is a different one."""
    files = _dist_files("experimently-openfeature", "0.1.0")
    digest = _record(tmp_path, files)
    result = _check(tmp_path, files, "Experimently.OpenFeature", "0.1.0", digest)
    assert result.returncode == 0, result.stdout + result.stderr

    other = tmp_path / "other"
    other.mkdir()
    result = _check(other, files, "experimently", "0.1.0", digest)
    assert result.returncode == 1, result.stdout


@pytest.mark.parametrize(
    ("tag", "wheel_version", "ok"),
    [
        ("0.1.0", "0.1.0", True),
        ("1.0.0rc1", "1.0.0rc1", True),
        ("1.0.0-rc.1", "1.0.0rc1", False),
    ],
)
def test_the_build_job_refuses_a_version_not_in_its_pep_440_spelling(
    tag: str, wheel_version: str, ok: bool, tmp_path: Path
) -> None:
    """The publish job compares file names with the tag as strings, so the
    build job refuses a tag it would only refuse after approval."""
    sdk = tmp_path / "sdk"
    (sdk / "dist").mkdir(parents=True)
    (sdk / "dist" / f"experimently-{wheel_version}-py3-none-any.whl").write_bytes(b"w")
    result = _run_step(
        _step("pypi-build", "Built version matches the tag"),
        {"needs.resolve.outputs.version": tag},
        tmp_path,
        sdk,
    )
    assert (result.returncode == 0) is ok, result.stdout + result.stderr
