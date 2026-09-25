"""A core tree cannot see the checkout it was copied from (#47).

``tree_profiles.core_tree`` answers "what does a **core** build do?" by copying
``backend/`` somewhere with no ``modules/`` beside it.  That only means anything
if the interpreter it runs cannot find the modules package some other way, and
an editable install (``pip install -e .``, what ``nightly-qa`` and a developer
venv do) is exactly such a way: setuptools appends a finder to
``sys.meta_path`` that maps ``modules`` -- and every ``backend.*`` child the
copy lacks -- back into the checkout.  Under it the "core" bootstrap built the
twelve module tables, and every core-tree test either failed (the two in
``test_profile_transitions.py``) or passed while testing the full profile.

These tests use nothing but ``core_tree`` and ``run``, the harness's own
entry points, so a harness that leaks fails them on an assertion.  The
``integration-tests`` workflow installs the repository editable and sets
``EXPERIMENTLY_REQUIRE_EDITABLE``; :func:`test_the_integration_job_is_armed`
fails that job if the install is ever dropped, because without it the leak
these tests look for cannot occur and they pass whatever the harness does.
"""

from __future__ import annotations

import importlib.machinery
import json
import os
import pathlib
import sys

import pytest

from backend.tests.integration.database import tree_profiles

pytestmark = [pytest.mark.integration, pytest.mark.regression]

#: Printed by a subprocess in the core tree: where ``modules``, ``backend`` and
#: ``backend.tests`` resolve.  ``backend`` itself is not imported -- only
#: located -- so the probe runs no package code.
_PROBE = """
import importlib.machinery, importlib.util, json, sys

modules = importlib.util.find_spec("modules")
backend = importlib.util.find_spec("backend")
children = []
for finder in sys.meta_path:
    if finder is importlib.machinery.PathFinder:
        continue
    find = getattr(finder, "find_spec", None)
    spec = find("backend.tests", None) if find else None
    if spec is not None:
        children.append(str(spec.origin))
print(json.dumps({
    "modules": None if modules is None else str(modules.origin),
    "backend": list(backend.submodule_search_locations or []),
    "backend_children": children,
}))
"""


def _probe(tree: pathlib.Path, extra_env=None) -> dict:
    process = tree_profiles.run(tree, ["-c", _PROBE], "unused", extra_env)
    assert process.returncode == 0, process.stderr[-3000:]
    return json.loads(process.stdout.strip().splitlines()[-1])


def _inside(path: str, tree: pathlib.Path) -> bool:
    return pathlib.Path(path).resolve().is_relative_to(tree.resolve())


def test_a_core_tree_resolves_no_modules_package(tmp_path):
    tree = tree_profiles.core_tree(tmp_path / "core")
    seen = _probe(tree)

    assert seen["modules"] is None, f"`modules` leaked into the core tree: {seen}"
    assert seen["backend"], seen
    assert all(_inside(p, tree) for p in seen["backend"]), seen
    assert seen["backend_children"] == [], seen


def test_a_modules_directory_elsewhere_on_the_path_is_not_seen(tmp_path):
    """The path-shaped leak: a ``.pth`` or PYTHONPATH entry holding ``modules/``.

    Planted here rather than waited for, so this holds with or without an
    editable install.
    """
    tree = tree_profiles.core_tree(tmp_path / "core")
    leak = tmp_path / "elsewhere"
    (leak / "modules").mkdir(parents=True)
    (leak / "modules" / "__init__.py").write_text("", encoding="utf-8")

    seen = _probe(tree, {"PYTHONPATH": os.pathsep.join([str(tree), str(leak)])})

    assert seen["modules"] is None, f"`modules` leaked into the core tree: {seen}"


def test_a_core_tree_with_a_modules_package_refuses_to_run(tmp_path):
    """A leak the harness cannot remove is a failure, never a full profile."""
    tree = tree_profiles.core_tree(tmp_path / "core")
    (tree / "modules").mkdir()
    (tree / "modules" / "__init__.py").write_text("", encoding="utf-8")

    process = tree_profiles.run(tree, ["-c", "pass"], "unused")

    assert process.returncode != 0, (process.stdout, process.stderr)
    assert "modules" in process.stderr, process.stderr[-3000:]


@pytest.mark.skipif(
    os.environ.get("EXPERIMENTLY_REQUIRE_EDITABLE") != "1",
    reason="only the integration-tests workflow requires the editable install",
)
def test_the_integration_job_is_armed():
    """The job runs with the leak these tests exist to catch.

    Without an editable install nothing but ``PathFinder`` can resolve
    ``modules``, and every test above passes whatever the harness does.
    """
    finders = [
        type(finder).__name__ if not isinstance(finder, type) else finder.__name__
        for finder in sys.meta_path
        if finder is not importlib.machinery.PathFinder
        and getattr(finder, "find_spec", None) is not None
        and finder.find_spec("modules", None) is not None
    ]
    assert finders, (
        "no editable finder resolves `modules`: the integration-tests job has "
        "lost its `pip install -e .` and the core-tree tests cannot fail"
    )
