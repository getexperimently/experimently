"""The tree a video is recorded from: ``git archive <ref>``, never the working tree.

1. ``git archive <commit> | tar -x`` into ``<work root>/tree-<profile>``: only
   what the ref tracks, so a developer's uncommitted or untracked files do not
   reach the video. The only git commands the tool runs are ``rev-parse`` and
   ``archive``; neither writes. A ref that is not here is refused with the
   fetch command to run, which the tool does not run itself.
2. Core: ``modules/`` is deleted (through ``WorkRoot.remove``).
3. ``frontend/node_modules`` is cloned from the checkout the tool runs from
   (``cp -c``: copy-on-write on APFS, so it costs no space, and a build tool
   that wrote into one could not change the checkout's file).
4. ``npm run build`` with ``guard.dashboard_settings``, then core_build.sh's two
   bundle checks, copied: no module route in a core bundle and the workspaces
   stub present (or, for full, the module route present).

The manifest records the Next.js version actually built with beside the one
the ref's lockfile pins: a checkout's ``node_modules`` can be older than the
ref being recorded.

Nothing here needs ``.git`` in the tree it builds: ``backend/tests/unit/showcase``
builds a tree from a plain tar stream in a directory with none.
"""

from __future__ import annotations

import json
import re
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Callable, Dict, List, Mapping, Optional

from showcase.capture import guard

#: core_build.sh's step_frontend, copied: a core bundle names none of these.
MODULE_ROUTES = re.compile(
    rb"/api/v1/workspaces|/api/v1/rbac/|/api/v1/hipaa|/api/v1/warehouse/"
)
#: ...and has the workspaces stub page, whose description this is.
CORE_STUB_TEXT = b"Separate teams into workspaces"
FULL_ROUTE = re.compile(rb"/api/v1/workspaces")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class BuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class Source:
    """The commit a video is recorded from."""

    ref: str
    commit: str
    version: str


def resolve_ref(repo: Path, ref: str, *, run=subprocess.run) -> str:
    """The commit *ref* names in *repo*; Refused (with the fetch to run) when absent."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}", ref):
        raise guard.Refused(f"--ref {ref!r} is not a ref")
    done = run(
        [
            "git",
            "-C",
            str(repo),
            "rev-parse",
            "--verify",
            "--quiet",
            f"{ref}^{{commit}}",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=guard.tool_env(),
    )
    commit = done.stdout.strip()
    if done.returncode != 0 or not _SHA.match(commit):
        raise guard.Refused(
            f"{ref} is not in {repo}. The tool runs no git command that writes;"
            f" fetch it first: git -C {repo} fetch --tags origin"
        )
    return commit


def extract(stream: IO[bytes], tree: Path) -> None:
    """Unpack a tar stream into *tree*, which must not exist yet."""
    if tree.exists():
        raise BuildError(f"{tree} exists already")
    tree.mkdir(parents=True)
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        archive.extractall(tree, filter="data")


def archive(repo: Path, commit: str, tree: Path) -> None:
    """``git archive <commit>`` of *repo*, unpacked into *tree*."""
    process = subprocess.Popen(
        ["git", "-C", str(repo), "archive", "--format=tar", commit],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=guard.tool_env(),
    )
    assert process.stdout is not None
    try:
        extract(process.stdout, tree)
    finally:
        process.stdout.close()
        stderr = (
            process.stderr.read().decode(errors="replace") if process.stderr else ""
        )
        status = process.wait()
    if status != 0:
        raise BuildError(f"git archive {commit} exited {status}: {stderr.strip()}")


def strip_modules(tree: Path, profile: str, work: guard.WorkRoot) -> None:
    modules = tree / "modules"
    if profile == "full":
        if not modules.is_dir():
            raise BuildError("--profile full, but the ref has no modules/ directory")
        return
    if modules.exists():
        work.remove(modules)


def clone_node_modules(source: Path, tree: Path, *, run=subprocess.run) -> None:
    """``cp -cR`` *source* to ``tree/frontend/node_modules`` (copy-on-write)."""
    if not (source / "next" / "package.json").is_file():
        raise BuildError(
            f"{source} has no Next.js; run `npm ci` in frontend/ of the checkout"
            " the tool runs from"
        )
    target = tree / "frontend" / "node_modules"
    if target.exists():
        raise BuildError(f"{target} exists already")
    done = run(
        ["cp", "-cR", str(source), str(target)],
        capture_output=True,
        text=True,
        env=guard.tool_env(),
    )
    if done.returncode != 0:
        raise BuildError(f"cp -cR node_modules failed: {done.stderr.strip()}")


def bundle_check(static: Path, profile: str) -> str:
    """core_build.sh's bundle checks on ``out/_next/static``; the line it logs."""
    if not static.is_dir():
        raise BuildError("next build produced no out/_next/static")
    found_route: List[str] = []
    stub = False
    full_route = False
    for path in sorted(static.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if MODULE_ROUTES.search(data):
            found_route.append(path.relative_to(static).as_posix())
        if CORE_STUB_TEXT in data:
            stub = True
        if FULL_ROUTE.search(data):
            full_route = True
    if profile == "core":
        if found_route:
            raise BuildError(
                "the core bundle references module routes: "
                + ", ".join(found_route[:5])
            )
        if not stub:
            raise BuildError("the core bundle has no workspaces stub page")
        return "core bundle: no module route, workspaces stub present"
    if not full_route:
        raise BuildError("the full bundle does not reference /api/v1/workspaces")
    return "full bundle: module routes present"


def next_versions(tree: Path) -> Dict[str, Optional[str]]:
    """The Next.js the build used, and the one the ref's lockfile pins."""
    used = None
    pinned = None
    package = tree / "frontend" / "node_modules" / "next" / "package.json"
    if package.is_file():
        used = json.loads(package.read_text(encoding="utf-8")).get("version")
    lock = tree / "frontend" / "package-lock.json"
    if lock.is_file():
        packages = json.loads(lock.read_text(encoding="utf-8")).get("packages", {})
        pinned = (packages.get("node_modules/next") or {}).get("version")
    return {"next_used": used, "next_lockfile": pinned}


def build_dashboard(
    tree: Path,
    env: Mapping[str, str],
    log: Path,
    *,
    spawn: Callable[..., int],
) -> None:
    status = spawn(["npm", "run", "build"], cwd=tree / "frontend", env=env, log=log)
    if status != 0:
        raise BuildError(f"npm run build exited {status}; see {log}")
