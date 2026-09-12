"""
What alembic's autogenerate must leave alone in the Community migration chain.

The Enterprise model module (``models/workspace.py``) attaches two foreign
keys to Community tables -- ``experiments.workspace_id`` and
``feature_flags.workspace_id`` -> ``workspaces.id`` -- whenever the Enterprise
models are loaded.  Those constraints are managed by the Enterprise alembic
branch (issue #89), never by this chain: migration ``a7b8c9d0e1f2`` drops
them on every database, and a fresh Enterprise bootstrap re-creates them from
the models, so an Enterprise metadata compared against a migrated Enterprise
database always differs by exactly these two.  An autogenerate that emitted
them would put a reference to ``workspaces`` into a Community migration, which
then fails ``upgrade head`` on every Community database and silently
re-couples the editions.
"""

from __future__ import annotations

from typing import Any

#: Constraint names the Enterprise model module owns.
ENTERPRISE_MANAGED_CONSTRAINTS = frozenset(
    {"experiments_workspace_id_fkey", "feature_flags_workspace_id_fkey"}
)


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """alembic ``include_object`` hook: skip the Enterprise-managed constraints."""
    if type_ == "foreign_key_constraint" and name in ENTERPRISE_MANAGED_CONSTRAINTS:
        return False
    return True
