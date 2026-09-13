"""The images must build from a *core* checkout, on either builder.

A core checkout has no ``modules/`` directory at all.  BuildKit builds only the
stages the requested ``--target`` needs, so it never looks at the module stages
when you ask for ``core``.  A classic builder -- ``DOCKER_BUILDKIT=0``, Compose
v1, Kaniko, older buildah -- has no notion of an unused stage: it runs every
stage in the file, in order, whatever ``--target`` says.  ``core`` is the LAST
stage, so a plain ``docker build -f backend/Dockerfile .`` (what
``docs/getting-started/modules.md`` tells a self-hoster to run, and what
``docker compose build api`` does) reaches the module stages and fails in them::

    COPY failed: file not found in build context: modules/requirements.lock

The invariant that prevents it: no COPY from the build **context** may name
``modules`` by an explicit path.  Those that need it use a glob -- paired with a
path that is always present, because a glob matching nothing is itself an error
("COPY failed: no source files were specified") on both builders.  ``COPY
--from=<stage>`` is exempt: a stage always has what the stage put there.

``frontend/Dockerfile`` has the same hazard for the same reason, so it is
checked here too: it picks its profile with ``FROM
modules-tree-${EXPERIMENTLY_PROFILE}``, which a classic builder does not read
as "build only that one" -- it builds ``modules-tree-full`` as well, and its
``COPY modules/frontend/`` then failed on a core checkout.

The end-to-end proof is a build with each builder; this is the cheap guard that
fails the moment an explicit path comes back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"

#: Every Dockerfile whose build context is the repository root and which
#: therefore has to tolerate a tree with no ``modules/`` in it.
DOCKERFILES = (DOCKERFILE, REPO_ROOT / "frontend" / "Dockerfile")


def _instructions(text: str) -> list[str]:
    """The Dockerfile's instructions, line continuations joined, comments out."""
    joined = re.sub(r"\\\n", " ", text)
    return [
        " ".join(line.split())
        for line in joined.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def context_copy_sources(dockerfile: Path = DOCKERFILE) -> list[tuple[str, str]]:
    """``(instruction, source)`` for every COPY/ADD that reads the build context."""
    found = []
    for instruction in _instructions(dockerfile.read_text()):
        words = instruction.split()
        if words[0].upper() not in ("COPY", "ADD"):
            continue
        flags = [w for w in words[1:] if w.startswith("--")]
        if any(flag.startswith("--from=") for flag in flags):
            continue  # from a stage, not from the context
        operands = [w for w in words[1:] if not w.startswith("--")]
        for source in operands[:-1]:  # the last operand is the destination
            found.append((instruction, source))
    return found


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.parent.name)
def test_no_copy_names_modules_by_an_explicit_path(dockerfile):
    offenders = [
        (instruction, source)
        for instruction, source in context_copy_sources(dockerfile)
        if "modules" in source and "*" not in source
    ]
    assert not offenders, (
        "these COPY sources name modules/ by an explicit path, so a core "
        f"checkout cannot build {dockerfile.parent.name}/Dockerfile with a "
        f"classic (DOCKER_BUILDKIT=0) builder at all: {offenders}"
    )


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.parent.name)
def test_every_modules_glob_is_paired_with_a_path_that_always_exists(dockerfile):
    """A glob that matches nothing is an error too, not a no-op."""
    for instruction, source in context_copy_sources(dockerfile):
        if "modules" not in source or "*" not in source:
            continue
        companions = [
            other
            for other_instruction, other in context_copy_sources(dockerfile)
            if other_instruction == instruction and "modules" not in other
        ]
        assert companions, (
            f"{instruction!r} has only optional sources; both builders fail it "
            "with 'no source files were specified' when the glob matches "
            "nothing. Pair it with a path that is always in the context."
        )
        for companion in companions:
            assert (REPO_ROOT / companion).exists(), (
                f"{companion} is what keeps {instruction!r} from an empty "
                "match, and it is not in the repository"
            )


@pytest.mark.unit
@pytest.mark.regression
def test_core_is_the_last_stage_so_it_is_the_default_target():
    """Why the stages above it have to tolerate a missing modules/ at all."""
    stages = [
        instruction.split(" AS ")[-1].strip()
        for instruction in _instructions(DOCKERFILE.read_text())
        if instruction.upper().startswith("FROM ") and " AS " in instruction.upper()
    ]
    assert stages[-1] == "core", stages
