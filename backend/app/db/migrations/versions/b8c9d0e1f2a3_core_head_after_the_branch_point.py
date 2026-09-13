"""The core head, so a7b8c9d0e1f2 can be the modules branch's branch point

This revision changes nothing about the schema.  It exists so that the core
chain has a head *after* ``a7b8c9d0e1f2``, which is what lets the ``modules``
branch hang off ``a7b8c9d0e1f2`` and still leave two heads.

Why that is needed
------------------
``a7b8c9d0e1f2`` drops the two ``workspace_id`` foreign keys from
``experiments`` and ``feature_flags``; the modules branch's base revision
(``modules_0001_rbac``) puts them back on a database that has a ``workspaces``
table.  One undoes the other, so the order they run in is the whole
correctness of the pair -- and alembic only orders two revisions when one is
an *ancestor* of the other.

``modules_0001_rbac`` used to be an independent alembic base: no ancestry
edge, so alembic was free to schedule it anywhere in the plan, and it put it
early.  On any database behind ``a7b8c9d0e1f2`` -- every deployment that has
not yet taken the release that introduced it -- a single ``alembic upgrade
heads`` therefore ran the restoration *first* and the drop *second*, ended
with both revisions stamped and both foreign keys gone, and nothing ever ran
either of them again.  ``ON DELETE SET NULL`` was silently absent from then
on.  (``db/bootstrap.py`` hid it, because ``reconcile_with_models`` adds the
models' ``use_alter`` keys afterwards, but the production migration paths --
the CDK migration task, ``deploy-prod.yml``, ``db-migrate.yml`` and
``docs/self-hosting/migrations.md`` -- all run raw ``alembic upgrade heads``.)

The edge cannot be a ``depends_on``: alembic removes the depended-on revision
from ``_real_heads``, which is what ``heads`` resolves to, so ``stamp heads``
on a fresh full bootstrap wrote a single row and a core image then died on a
revision it has no file for.  Worse, from a database recorded at exactly
``a7b8c9d0e1f2`` a ``depends_on`` edge makes alembic re-plan part of the core
chain and re-run migrations that are already applied.

So the edge is a plain ``down_revision``: ``modules_0001_rbac`` now chains
from ``a7b8c9d0e1f2``.  That alone would leave ``a7b8c9d0e1f2`` with exactly
one child and therefore no core head at all -- one row again.  This revision
is the second child.  ``a7b8c9d0e1f2`` becomes a real branch point, the core
chain keeps a head of its own, ``alembic heads`` prints two, and every upgrade
runs the drop before the restoration because ancestry says so.

Being a branch point also stops the ``modules`` branch label leaking down the
core chain: alembic walks a label up from its revision until it reaches a
branch point (``RevisionMap._add_branches``), and that walk now stops here.

Nothing to do on upgrade or downgrade: a marker revision has no schema of its
own, and both directions are deliberately empty rather than "not implemented"
so ``alembic downgrade`` past it works.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-12
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No schema change -- see the module docstring."""


def downgrade() -> None:
    """No schema change -- see the module docstring."""
