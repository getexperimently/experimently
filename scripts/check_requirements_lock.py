#!/usr/bin/env python3
"""Check that every requirements lock still satisfies the pins it was made from.

Two pairs, one per profile:

* ``backend/requirements/runtime.txt`` -> ``backend/requirements/runtime.lock``
  (the core image, ``backend/Dockerfile``'s ``runtime`` stage),
* ``modules/requirements.txt`` -> ``modules/requirements.lock``
  (the module-only dependencies the ``full`` stage adds on top).

A lock (``make lock``, ``uv pip compile --universal --generate-hashes``) is what
the Dockerfile installs, so a pin bumped in the input without a regenerated lock
would ship the old version.  This check is deliberately offline and
deterministic: it does not re-resolve (a re-resolution can differ for reasons
that are not drift -- a wheel added to an old release changes the hash list), it
only asserts that

* every ``name==version`` pin in the input appears in its lock at exactly
  that version,
* every requirement in the lock is an exact ``==`` pin carrying at least one
  ``--hash`` (so ``pip install --require-hashes`` accepts the file),
* the two locks never pin the same package at different versions -- the full
  image installs one after the other, and the second install would silently
  replace a package the first one resolved.

It also checks the *inputs* against each other.  ``backend/requirements.txt``
is the superset every CI job and every developer venv installs;
``backend/requirements/runtime.txt`` is the subset the image installs, and its
own header says "Keep the pins identical to backend/requirements.txt".  Nothing
enforced that, and nothing watched runtime.txt either: a Dependabot pip update
edits ``backend/requirements.txt`` alone, so a security bump could land, go
green, and ship an image still running the old version.  Every pin shared
between two input files must therefore name the same version, and every
runtime.txt pin must be present in backend/requirements.txt -- which is what
makes a bump in one file fail the lint job until the other follows.

The modules pair is skipped when ``modules/`` is absent (a core checkout).

Usage (from the repository root)::

    python scripts/check_requirements_lock.py
    make lock-check

Exit status 0 when the locks are consistent, 1 with a list of problems otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: ``(input pins, lock, required)`` -- the modules pair is absent in a core
#: checkout, where ``modules/`` has been removed.
PAIRS = [
    (
        ROOT / "backend" / "requirements" / "runtime.txt",
        ROOT / "backend" / "requirements" / "runtime.lock",
        True,
    ),
    (
        ROOT / "modules" / "requirements.txt",
        ROOT / "modules" / "requirements.lock",
        False,
    ),
]

#: ``(subset, superset, required, every_pin)`` -- pins the two files share must
#: name the same version.  ``backend/requirements.txt`` is the superset CI and
#: every developer venv install; the other two are what the image stages
#: install.  ``every_pin`` additionally requires the subset's *whole* pin list
#: to be present in the superset: true for runtime.txt, which is by definition
#: a subset of backend/requirements.txt, and false for modules/requirements.txt,
#: whose own pins (python3-saml, the warehouse drivers) are module-only and
#: belong nowhere else.
SUPERSETS = [
    (
        ROOT / "backend" / "requirements" / "runtime.txt",
        ROOT / "backend" / "requirements.txt",
        True,
        True,
    ),
    (
        ROOT / "modules" / "requirements.txt",
        ROOT / "backend" / "requirements.txt",
        False,
        False,
    ),
]

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==([^\s;\\]+)")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_pins(path: Path) -> dict[str, str]:
    """``{canonical name: version}`` for every ``name==version`` line."""
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = _PIN.match(line)
        if match:
            pins[canonical(match.group(1))] = match.group(3)
    return pins


def lock_entries(path: Path) -> tuple[dict[str, str], list[str]]:
    """``({name: version}, problems)`` for the lock file."""
    pins: dict[str, str] = {}
    problems: list[str] = []
    current: str | None = None
    hashes = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("--hash="):
            hashes += 1
            continue
        if current is not None and hashes == 0:
            problems.append(
                f"{current}: no --hash lines (pip --require-hashes would refuse it)"
            )
        current = None
        hashes = 0
        match = _PIN.match(stripped)
        if not match:
            problems.append(f"not an exact pin: {stripped.rstrip(chr(92)).strip()}")
            continue
        current = canonical(match.group(1))
        pins[current] = match.group(3)
    if current is not None and hashes == 0:
        problems.append(
            f"{current}: no --hash lines (pip --require-hashes would refuse it)"
        )
    return pins, problems


def check_pair(requirements: Path, lock: Path) -> tuple[dict[str, str], list[str]]:
    """``({name: version} the lock pins, problems)`` for one input/lock pair."""
    if not lock.exists():
        return {}, [f"{lock.relative_to(ROOT)} is missing; run `make lock`"]
    wanted = read_pins(requirements)
    locked, problems = lock_entries(lock)
    source = requirements.name
    for name, version in sorted(wanted.items()):
        if name not in locked:
            problems.append(
                f"{name}=={version} is pinned in {source} but absent from the lock"
            )
        elif locked[name] != version:
            problems.append(
                f"{name}: {source} pins {version}, the lock has {locked[name]}"
            )
    if not problems:
        print(
            f"{lock.relative_to(ROOT)}: {len(locked)} pinned, hashed packages; "
            f"all {len(wanted)} {source} pins present at their versions"
        )
    return locked, problems


def _show(path: Path) -> str:
    """*path* relative to the repository root when it is inside it."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check_superset(subset: Path, superset: Path, every_pin: bool) -> list[str]:
    """Problems with *subset*'s pins against *superset*'s."""
    problems: list[str] = []
    wanted = read_pins(subset)
    have = read_pins(superset)
    here = _show(subset)
    there = _show(superset)
    for name, version in sorted(wanted.items()):
        if name not in have:
            if every_pin:
                problems.append(
                    f"{name}=={version} is pinned in {here} but absent from "
                    f"{there}, which every CI job and every developer venv installs"
                )
            continue
        if have[name] != version:
            problems.append(f"{name}: {here} pins {version}, {there} pins {have[name]}")
    return problems


def main() -> int:
    failed = False
    resolved: dict[str, tuple[str, Path]] = {}
    for requirements, lock, required in PAIRS:
        if not requirements.exists():
            if required:
                print(f"{requirements.relative_to(ROOT)} is missing")
                failed = True
            continue
        locked, problems = check_pair(requirements, lock)
        if problems:
            print(
                f"{lock.relative_to(ROOT)} is out of date with "
                f"{requirements.relative_to(ROOT)}:"
            )
            for problem in problems:
                print(f"  - {problem}")
            failed = True
        for name, version in locked.items():
            previous = resolved.get(name)
            if previous is not None and previous[0] != version:
                print(
                    f"{name}: {previous[1].relative_to(ROOT)} pins {previous[0]}, "
                    f"{lock.relative_to(ROOT)} pins {version} -- the full image "
                    f"installs both locks, so one would replace the other"
                )
                failed = True
            else:
                resolved[name] = (version, lock)

    for subset, superset, required, every_pin in SUPERSETS:
        if not subset.exists() or not superset.exists():
            if required:
                print(f"{subset.relative_to(ROOT)} is missing")
                failed = True
            continue
        problems = check_superset(subset, superset, every_pin)
        if problems:
            print(
                f"{subset.relative_to(ROOT)} disagrees with "
                f"{superset.relative_to(ROOT)}:"
            )
            for problem in problems:
                print(f"  - {problem}")
            failed = True
        else:
            print(
                f"{subset.relative_to(ROOT)}: every shared pin matches "
                f"{superset.relative_to(ROOT)}"
            )

    if failed:
        print(
            "Bring the requirements files back into agreement, then regenerate "
            "the locks with `make lock` (uv pip compile) and commit the result."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
