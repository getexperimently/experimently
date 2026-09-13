"""Reader for ``modules-manifest.txt`` — the optional modules' file list.

Not a test module (pytest does not collect it); imported by
``test_core_boundary.py`` and ``test_core_model_registry.py`` so that both
read the same single source of truth.

The manifest lists repository-relative paths as they sit in the tree: under
``modules/``, mirrored from where the code was written (see the header of the
file itself).  Two shapes appear:

``modules/backend/app/services/sso_service.py``
    A file.  Its module path is ``modules.backend.app.services.sso_service``.
``modules/backend/app/services/integrations``
    A directory.  Everything under it belongs to a module.

:meth:`Manifest.module_paths` yields both spellings of every module -- the
``modules.``-prefixed one and the pre-move one
(``backend.app.services.sso_service``, ``backend.lambda.split_url_router``) --
so a core file that still names a module the old way is a crossing too.

A ``path::route`` entry -- a single route moving out of a file that stays core
-- was a shape the manifest could once carry.  Nothing has written one since
the move and nothing ever read the parsed result, so such a line is now a
parse error rather than something silently accepted.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field
from typing import List, Set, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "modules-manifest.txt"

#: The directory (and Python package) the modules live in.
MODULES_DIR = "modules"

_TABLES_HEADER = "MODULE TABLES"
_NOT_MODULE_MARKER = "NOT module tables"
_TABLE_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")


@dataclass
class Manifest:
    """Parsed ``modules-manifest.txt``."""

    #: Repository-relative paths of whole module files and directories.
    paths: List[str] = field(default_factory=list)
    #: Table names the core ``Base.metadata`` must never contain.
    tables: List[str] = field(default_factory=list)

    @property
    def python_paths(self) -> List[str]:
        """Entries that name Python files or package directories."""
        return [
            p
            for p in self.paths
            if p.endswith(".py") or "." not in p.rsplit("/", 1)[-1]
        ]

    def module_paths(self) -> Set[str]:
        """Every dotted module path an import of a module's code can use."""
        modules: Set[str] = set()
        for path in self.python_paths:
            if not path.startswith(("backend/", "infrastructure/", f"{MODULES_DIR}/")):
                continue
            for spelling in _spellings(path):
                modules.add(spelling.replace("/", "."))
        return modules

    def path_prefixes(self) -> List[Tuple[str, str]]:
        """``(repo path, dotted prefix)`` for module *directories*, both spellings."""
        out = []
        for path in self.paths:
            if path.endswith(".py"):
                continue
            if "." in path.rsplit("/", 1)[-1]:
                continue
            for spelling in _spellings(path):
                out.append((path, spelling.replace("/", ".")))
        return out


def _spellings(path: str) -> List[str]:
    """The post-move and pre-move repository paths of a manifest entry (no ``.py``).

    ``modules/backend/app/x.py`` was ``backend/app/x.py``; ``modules/lambda/x``
    was ``backend/lambda/x`` (the Lambda packages mirror to ``modules/lambda``,
    not ``modules/backend/lambda``).  A pre-move entry yields its ``modules/``
    form the same way round, so the reader accepts either state.

    The pre-move spelling is only a crossing while nothing core answers to
    it.  An entry written *after* the move -- ``modules/backend/app/db`` (the
    modules' alembic branch), ``modules/backend/tests/conftest.py`` -- mirrors
    a path that is, and stays, core; deriving ``backend.app.db`` from it would
    flag every ``from backend.app.db.session import`` in the tree.  So the old
    spelling is dropped whenever the old path still exists.
    """
    prefix = f"{MODULES_DIR}/"
    lambda_prefix = f"{MODULES_DIR}/lambda/"
    trimmed = path[:-3] if path.endswith(".py") else path
    if trimmed.startswith(lambda_prefix):
        pair = [trimmed, "backend/lambda/" + trimmed[len(lambda_prefix) :]]
    elif trimmed.startswith("backend/lambda/"):
        pair = [lambda_prefix + trimmed[len("backend/lambda/") :], trimmed]
    elif trimmed.startswith(prefix):
        pair = [trimmed, trimmed[len(prefix) :]]
    else:
        pair = [f"{prefix}{trimmed}", trimmed]
    post, pre = pair
    suffix = ".py" if path.endswith(".py") else ""
    if (REPO_ROOT / (pre + suffix)).exists():
        return [post]
    return [post, pre]


def load(manifest_path: pathlib.Path = MANIFEST_PATH) -> Manifest:
    """Parse the manifest at *manifest_path*."""
    manifest = Manifest()
    in_tables = False
    for raw in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            comment = line.lstrip("#").strip()
            if _TABLES_HEADER in comment and "∩" in comment:
                in_tables = True
                continue
            if in_tables:
                if comment.startswith(_NOT_MODULE_MARKER):
                    in_tables = False
                    continue
                # A table name is a bare identifier on its own comment line;
                # the section's prose, rules and separators are skipped.
                if _TABLE_NAME_RE.fullmatch(comment):
                    manifest.tables.append(comment)
            continue

        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        if "::" in entry:
            raise ValueError(
                f"{manifest_path.name}: `{entry}` is a route-only entry. "
                "Nothing reads those any more; list the whole file, or leave "
                "it out."
            )
        manifest.paths.append(entry)
    return manifest


def module_tables() -> List[str]:
    """The modules' table names, straight from the manifest."""
    return load().tables
