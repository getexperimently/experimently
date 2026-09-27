"""Every module the LLM call paths import is installed, and pinned (#196).

The provider SDKs are imported inside functions, so a missing one never fails
an import at start-up or in a test that mocks it: the API image shipped with
neither ``anthropic`` nor ``openai``, and every ``/complete`` call answered 502
while the suite stayed green. The list checked here is derived from the source
by ``scripts/llm_sdk_imports.py`` (function-local imports included), not typed,
so an import added to those files tomorrow is covered by this test tomorrow.

Two halves, because either can be true while the other is false:

* ``find_spec``: the module is present in *this* environment -- in CI, the one
  ``backend/requirements.txt`` builds.
* the pins: the module's distribution is pinned in ``backend/requirements.txt``
  (every test job and developer venv), in ``backend/requirements/runtime.txt``
  and in ``runtime.lock`` (what the image installs). A developer venv that
  happens to have a package installed would otherwise pass the first half for
  a pin nobody wrote down. The image itself is checked by the Docker Smoke job,
  with the same derived list.

``google.*`` is excluded by the script (the Gemini half of #196 is separate);
``test_exclusion_is_only_google`` pins that the exclusion stays that narrow.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import textwrap
from importlib import metadata
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = REPO_ROOT / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


llm = _load("llm_sdk_imports")
locks = _load("check_requirements_lock")

DERIVED = llm.derived_imports()
FIRST_PARTY = ("backend",)


def _top(module: str) -> str:
    return module.split(".", 1)[0]


def _third_party() -> list[str]:
    """Top-level names that are neither the standard library nor this project."""
    return sorted(
        {
            _top(m)
            for m in DERIVED
            if _top(m) not in sys.stdlib_module_names and _top(m) not in FIRST_PARTY
        }
    )


def test_the_derivation_sees_the_provider_sdks():
    """A derivation that returned nothing would make every check below vacuous.

    ``anthropic`` and ``openai`` are only ever imported inside a function in
    these files, so their presence here is also the proof that function-local
    imports are walked.
    """
    assert {"anthropic", "openai"} <= set(DERIVED), DERIVED


def test_function_local_imports_are_found(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text(
        textwrap.dedent(
            """
            import os
            from typing import Any

            class P:
                async def complete(self):
                    try:
                        import somesdk.client  # noqa
                        from othersdk import thing  # noqa
                    except Exception:
                        raise
            """
        )
    )
    assert llm.imports_in(source) == {"os", "typing", "somesdk.client", "othersdk"}


def test_exclusion_is_only_google():
    assert llm.EXCLUDED_PREFIXES == ("google",)
    assert all(m == "google" or m.startswith("google.") for m in llm.excluded_imports())
    assert not any(_top(m) == "google" for m in DERIVED)


@pytest.mark.parametrize("module", DERIVED)
def test_module_is_installed(module):
    assert importlib.util.find_spec(module) is not None, (
        f"{module} is imported by an LLM call path but is not installed here; "
        "pin it in backend/requirements.txt and backend/requirements/runtime.txt "
        "and run `make lock`"
    )


@pytest.mark.parametrize("package", _third_party())
def test_third_party_import_loads(package):
    """``find_spec`` finds the package; importing it proves its own
    dependencies (jiter, httpx2, ...) are there too."""
    importlib.import_module(package)


@pytest.mark.parametrize("package", _third_party())
def test_third_party_import_is_pinned_everywhere_it_must_be(package):
    distributions = metadata.packages_distributions().get(package)
    assert distributions, f"no installed distribution provides {package!r}"
    requirements = locks.read_pins(REPO_ROOT / "backend" / "requirements.txt")
    runtime = locks.read_pins(REPO_ROOT / "backend" / "requirements" / "runtime.txt")
    lock, _ = locks.lock_entries(
        REPO_ROOT / "backend" / "requirements" / "runtime.lock"
    )
    for dist in distributions:
        name = locks.canonical(dist)
        for label, pins in (
            ("backend/requirements.txt", requirements),
            ("backend/requirements/runtime.txt", runtime),
            ("backend/requirements/runtime.lock", lock),
        ):
            assert name in pins, (
                f"{package} (distribution {name}) is imported by an LLM call "
                f"path but is not pinned in {label}"
            )
