"""Reader for ``ee-manifest.txt`` — the Enterprise edition module list.

Not a test module (pytest does not collect it); imported by
``test_ce_boundary.py`` and ``test_core_model_registry.py`` so that both read
the same single source of truth.

The manifest lists repository-relative paths as they sit *today*, before the
physical move to ``ee/`` (see the header of the file itself).  Three shapes
appear:

``backend/app/services/sso_service.py``
    A file.  Its module path is ``backend.app.services.sso_service``.
``backend/app/services/integrations``
    A directory.  Everything under it is Enterprise.
``backend/app/api/v1/endpoints/compliance.py::reports``
    A *route* inside a file that is otherwise Community.  The file is NOT an
    Enterprise module, so importing it is not a crossing; only the named route
    moves.  These entries are parsed and kept separately.

``derive_module_paths`` also yields the post-move ``ee.``-prefixed form, so the
boundary test keeps working after issue #89 lands.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "ee-manifest.txt"

_EE_TABLES_HEADER = "EE TABLES"
_NOT_EE_MARKER = "NOT EE tables"
_TABLE_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")


@dataclass
class Manifest:
    """Parsed ``ee-manifest.txt``."""

    #: Repository-relative paths of whole Enterprise files and directories.
    paths: List[str] = field(default_factory=list)
    #: ``{path: [route names]}`` for partial (route-only) entries.
    partial: Dict[str, List[str]] = field(default_factory=dict)
    #: Table names the Community ``Base.metadata`` must never contain.
    tables: List[str] = field(default_factory=list)

    @property
    def python_paths(self) -> List[str]:
        """Enterprise entries that name Python files or package directories."""
        return [
            p
            for p in self.paths
            if p.endswith(".py") or "." not in p.rsplit("/", 1)[-1]
        ]

    def module_paths(self) -> Set[str]:
        """Every dotted module path an import of an Enterprise module can use."""
        modules: Set[str] = set()
        for path in self.python_paths:
            if not path.startswith(("backend/", "infrastructure/", "ee/")):
                continue
            trimmed = path[:-3] if path.endswith(".py") else path
            dotted = trimmed.replace("/", ".")
            modules.add(dotted)
            if dotted.startswith("ee."):
                modules.add(dotted[len("ee.") :])
            else:
                modules.add(f"ee.{dotted}")
        return modules

    def path_prefixes(self) -> List[Tuple[str, str]]:
        """``(repo path, dotted prefix)`` for Enterprise *directories*."""
        out = []
        for path in self.paths:
            if path.endswith(".py"):
                continue
            if "." in path.rsplit("/", 1)[-1]:
                continue
            out.append((path, path.replace("/", ".")))
        return out


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
            if _EE_TABLES_HEADER in comment and "∩" in comment:
                in_tables = True
                continue
            if in_tables:
                if comment.startswith(_NOT_EE_MARKER):
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
            path, route = entry.split("::", 1)
            manifest.partial.setdefault(path.strip(), []).append(route.strip())
        else:
            manifest.paths.append(entry)
    return manifest


def ee_tables() -> List[str]:
    """The Enterprise table names, straight from the manifest."""
    return load().tables
