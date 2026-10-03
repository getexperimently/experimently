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
