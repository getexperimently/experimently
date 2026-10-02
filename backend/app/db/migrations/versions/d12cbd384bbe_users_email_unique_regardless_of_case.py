"""Users: an email address belongs to one account whatever its letter case

Adds the unique index ``ix_users_email_lower`` on ``lower(email)`` beside the
exact unique index on ``email``, which stays.  NULL addresses are still allowed,
any number of them: the index is a plain unique one (NULLS DISTINCT).

The model declares the same index (``User.__table_args__``), so a schema built
by ``db/bootstrap.py``'s ``create_all`` already has it; the transition tests
rewind such a schema and replay the chain.  The index is therefore created only
when it is absent -- and "present" means the index this release builds, valid,
unique and with exactly this definition.  An index of that name in any other
state (an INVALID one left by a ``CREATE UNIQUE INDEX CONCURRENTLY`` that failed,
a non-unique one, another expression) is refused with the ``DROP INDEX`` to run,
never taken as done.

In order, inside the single transaction ``upgrade heads`` runs every pending
revision in (``env.py`` sets no ``transaction_per_migration``), so a refusal
rolls back every revision of the run and changes nothing:

1. ``lock_timeout`` is set to 30 s for this transaction, ``users`` is locked in
   SHARE mode -- the lock ``CREATE INDEX`` takes anyway, taken before the check
   so no row can be written between the check and the build -- and the setting
   is put back to its default straight after, so no later revision inherits it.
   A session still writing to ``users`` after 30 s ends the upgrade with a clean
   refusal instead of queueing every later write to the table behind it.
2. The pre-check, in SQL: groups of non-NULL addresses equal under PostgreSQL's
   ``lower()`` -- the same function the index uses, which is not Python's
   ``str.lower()`` outside ASCII.  Only account ids come back.  Any group
   refuses the upgrade with a message naming the group count and at most 20
   groups of ids; no address, domain or username is in it, because the deploy
   copies the tail of this output into a log that may be shared.
3. ``CREATE UNIQUE INDEX``.  A unique violation here (which the lock makes
   unreachable) is mapped to the same kind of ids-only refusal, raised ``from
   None`` so PostgreSQL's own message, which names the address, is not printed.

Every refusal ends with the runbook section that resolves it,
``docs/self-hosting/migrations.md#email-addresses-that-differ-only-in-case``.

No application import: a migration stays what it was the day it was written.

Core chain, extending the core head ``271f03a31742`` (generated with
``revision --autogenerate --head 271f03a31742``).  No module table is touched,
so a full checkout still has exactly two heads: this revision and
``modules_0002_warehouse_analysis``.

Revision ID: d12cbd384bbe
Revises: 271f03a31742
Create Date: 2026-10-01
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d12cbd384bbe"
down_revision: Union[str, None] = "271f03a31742"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The schema name comes from the deployment's own environment, never from a
# request.
_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")

_TABLE = "users"
_INDEX = "ix_users_email_lower"
#: ``pg_get_indexdef`` of the index this release builds, with ``%I`` for the
#: schema exactly as PostgreSQL quotes it.
_INDEXDEF = "CREATE UNIQUE INDEX ix_users_email_lower ON %I.users USING btree (lower((email)::text))"
_LOCK_TIMEOUT = "30s"
_MAX_GROUPS = 20
_RUNBOOK = (
    "See docs/self-hosting/migrations.md#email-addresses-that-differ-only-in-case"
)
_UNCHANGED = (
    "Nothing has been changed: the database is still at the revision it had "
    "before this upgrade, and the release you upgraded from runs against it as "
    "before."
)

_UNIQUE_VIOLATION = "23505"
_LOCK_NOT_AVAILABLE = "55P03"


def _pgcode(exc: BaseException) -> Union[str, None]:
    return getattr(getattr(exc, "orig", None), "pgcode", None)


def _qualified_table() -> str:
    preparer = op.get_bind().dialect.identifier_preparer
    return f"{preparer.quote_schema(_SCHEMA)}.{preparer.quote(_TABLE)}"


def _existing_index() -> Union[sa.Row, None]:
    """The index called ``ix_users_email_lower`` in the schema, if there is one."""
    return (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT i.indisvalid AS valid, i.indisunique AS is_unique, "
                "pg_get_indexdef(i.indexrelid) = format(:indexdef, :schema) "
                "AS same_definition "
                "FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = :index"
            ),
            {"indexdef": _INDEXDEF, "schema": _SCHEMA, "index": _INDEX},
        )
        .one_or_none()
    )


def _wrong_index_refusal() -> str:
    return "\n".join(
        [
            f"Refusing to upgrade schema {_SCHEMA}: it already has an index "
            f"named {_INDEX}, but not the valid, unique index on lower(email) "
            "this release builds (an index left behind by a CREATE INDEX "
            "CONCURRENTLY that failed is one way to get here).",
            "Nothing has been changed. Drop that index and run the upgrade "
            "again; the upgrade builds it itself:",
            f"  DROP INDEX {_SCHEMA}.{_INDEX};",
            _RUNBOOK,
        ]
    )


def _lock_refusal() -> str:
    return "\n".join(
        [
            f"Refusing to upgrade schema {_SCHEMA}: another session is writing "
            f"to {_TABLE} and still held its lock after {_LOCK_TIMEOUT}.",
            "Nothing has been changed. Run the upgrade again.",
            _RUNBOOK,
        ]
    )


def _duplicate_groups() -> list[list[str]]:
    """Each group of accounts whose addresses differ only in case, as ids.

    Grouped by ``lower(email)`` in SQL, the index's own expression.  Only the
    ids leave the database.
    """
    rows = op.get_bind().execute(
        sa.text(
            "SELECT array_agg(id::text ORDER BY created_at, id::text) "
            f"FROM {_qualified_table()} "
            "WHERE email IS NOT NULL "
            "GROUP BY lower(email) HAVING count(*) > 1 "
            "ORDER BY min(created_at), min(id::text)"
        )
    )
    return [list(ids) for (ids,) in rows]


def _duplicates_refusal(groups: list[list[str]]) -> str:
    count = len(groups)
    noun, verb = ("group", "has") if count == 1 else ("groups", "have")
    lines = [
        f"Refusing to upgrade schema {_SCHEMA}: {count} {noun} of accounts {verb} "
        "email addresses that differ only in letter case, and from this "
        "release an email address belongs to one account whatever its case.",
        "Accounts that share an address (user ids, one group per line, oldest "
        "first):",
    ]
    lines += ["  " + " ".join(ids) for ids in groups[:_MAX_GROUPS]]
    if count > _MAX_GROUPS:
        rest = count - _MAX_GROUPS
        lines.append(
            f"  ... and {rest} more {'group' if rest == 1 else 'groups'}; the "
            "query in the section below lists them all"
        )
    lines += [_UNCHANGED, _RUNBOOK]
    return "\n".join(lines)


def _build_race_refusal() -> str:
    return "\n".join(
        [
            f"Refusing to upgrade schema {_SCHEMA}: the unique index on "
            "lower(email) could not be built, because two accounts' email "
            "addresses differ only in letter case.",
            _UNCHANGED,
            "Run the upgrade again to list the accounts.",
            _RUNBOOK,
        ]
    )


def upgrade() -> None:
    bind = op.get_bind()

    existing = _existing_index()
    if existing is not None:
        if existing.valid and existing.is_unique and existing.same_definition:
            return
        raise RuntimeError(_wrong_index_refusal())

    bind.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
    try:
        bind.execute(sa.text(f"LOCK TABLE {_qualified_table()} IN SHARE MODE"))
    except sa.exc.OperationalError as exc:
        if _pgcode(exc) == _LOCK_NOT_AVAILABLE:
            raise RuntimeError(_lock_refusal()) from None
        raise
    bind.execute(sa.text("SET LOCAL lock_timeout TO DEFAULT"))

    groups = _duplicate_groups()
    if groups:
        raise RuntimeError(_duplicates_refusal(groups))

    try:
        op.create_index(
            _INDEX,
            _TABLE,
            [sa.literal_column("lower(email)")],
            unique=True,
            schema=_SCHEMA,
        )
    except sa.exc.IntegrityError as exc:
        if _pgcode(exc) == _UNIQUE_VIOLATION:
            raise RuntimeError(_build_race_refusal()) from None
        raise


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE, schema=_SCHEMA)
