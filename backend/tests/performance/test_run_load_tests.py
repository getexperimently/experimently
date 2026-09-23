"""`run_load_tests.py` must know where the repository root is.

This workflow had **never passed**: 29 runs since 2026-05-11, every one a
failure, with

    Could not find 'backend/tests/performance/locustfiles/api_load_test.py'.

for a file that is tracked and present. The cause was one character:

    _REPO_ROOT = Path(__file__).resolve().parents[4]

This file is at ``<root>/backend/tests/performance/run_load_tests.py``, so the
parents are ``performance``(0), ``tests``(1), ``backend``(2), ``<root>``(3) --
and ``parents[4]`` is the directory *above* the repository.

That value is the ``cwd`` of both subprocesses the script starts, so locust
resolved the workflow's relative ``--locustfile`` against the wrong directory.
Reproduced verbatim by running locust from one level up, and fixed by running
it from the root:

    cwd=<parent of repo>  -> exit 1, "Could not find ..."
    cwd=<repo root>       -> exit 0, "Starting Locust 2.39.1"

An off-by-one in a path index is invisible on a developer machine whenever the
checkout happens to sit one level below something importable, which is why it
survived four months of weekly red runs. These assertions are about the
*repository*, not about an index, so they fail the same way wherever the
checkout lives.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent / "run_load_tests.py"


@pytest.fixture(scope="module")
def runner() -> ModuleType:
    """Import `run_load_tests.py` by path.

    Not `import backend.tests.performance.run_load_tests`: the module inserts
    into `sys.path` at import time, and going through the package would let a
    correct `sys.path` mask an incorrect `_REPO_ROOT`.
    """
    spec = importlib.util.spec_from_file_location("_run_load_tests", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.regression
def test_repo_root_is_the_repository(runner: ModuleType) -> None:
    """Asserted by contents, not by counting `..` levels.

    A test that recomputed the index would fail the same way the code does.
    """
    root = runner._REPO_ROOT
    missing = [
        marker
        for marker in ("backend", "pyproject.toml", "scripts")
        if not (root / marker).exists()
    ]
    assert not missing, (
        f"_REPO_ROOT is {root}, which is not this repository -- {missing} are "
        "not there. It is the `cwd` of the server and locust subprocesses, so "
        "every relative path they are given resolves against the wrong "
        "directory (the workflow had 29 failures and 0 successes this way)."
    )


@pytest.mark.regression
def test_repo_root_contains_this_test(runner: ModuleType) -> None:
    """The tightest statement of the same property.

    `_REPO_ROOT` must be an ancestor of this file. `parents[4]` is an ancestor
    too -- of the checkout's *parent* -- so this also pins the direction:
    the relative path from the root has to be the one the workflow passes.
    """
    root = runner._REPO_ROOT
    relative = Path(__file__).resolve().relative_to(root)
    assert relative == Path("backend/tests/performance/test_run_load_tests.py"), (
        f"this file is {relative} below _REPO_ROOT ({root}); the workflow "
        "passes `backend/tests/performance/locustfiles/...`, so anything else "
        "means those paths do not resolve"
    )


@pytest.mark.regression
def test_every_profile_locustfile_exists(runner: ModuleType) -> None:
    """The mapping the `--profile` flag resolves to.

    These are absolute (built from `_THIS_DIR`), so they survived the bug the
    workflow's relative path did not -- which is precisely why nobody noticed:
    a developer running `--profile baseline` locally sees it work.
    """
    missing = {
        profile: path
        for profile, path in runner._PROFILE_LOCUSTFILES.items()
        if not Path(path).is_file()
    }
    assert not missing, f"profiles naming a locustfile that is not there: {missing}"


@pytest.mark.regression
def test_the_workflow_locustfile_paths_resolve(runner: ModuleType) -> None:
    """The workflow passes RELATIVE paths; they must resolve from `_REPO_ROOT`.

    This is the assertion that would have caught the original bug. The
    `--profile` mapping above is absolute and cannot catch it.
    """
    # Located from THIS file, not from `_REPO_ROOT`. Keyed on `_REPO_ROOT` the
    # test skips when the root is wrong -- silently passing in exactly the
    # state it exists to catch. Located from `__file__` it fails instead.
    here = Path(__file__).resolve().parents[3]
    workflow = here / ".github" / "workflows" / "performance-tests.yml"
    if not workflow.is_file():
        pytest.skip("this tree has no .github/workflows")

    import re

    paths = sorted(
        set(re.findall(r'FILE="([^"]+\.py)"', workflow.read_text(encoding="utf-8")))
    )
    assert paths, f"no locustfile paths found in {workflow}"

    missing = [p for p in paths if not (runner._REPO_ROOT / p).is_file()]
    assert not missing, (
        f"{workflow.name} passes these relative paths, and they do not resolve "
        f"from _REPO_ROOT ({runner._REPO_ROOT}): {missing}"
    )
