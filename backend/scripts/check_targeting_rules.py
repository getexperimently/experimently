"""
List stored feature-flag targeting rules that a create or an update now refuses.

Run after upgrading to the release in which flag targeting rules are validated
when saved (#535)::

    python -m backend.scripts.check_targeting_rules

Stored rules are not re-judged: they are evaluated as before, and a flag whose
rules are listed here keeps working. But a ``PUT`` that sends those rules back
unchanged answers 422, so fix them (or leave ``targeting_rules`` out of the
request). The report reads, and never writes, ``feature_flags.targeting_rules``
and prints one tab-separated line per flag it lists::

    feature_flag  3f0c...  checkout-v2  groups[0].conditions[1].operator  unknown operator

The reason is the text the API answers with. A problem that belongs to the
rules as a whole has the path ``targeting_rules``. Two kinds of line:

* rules the API now refuses, with the API's own path and reason;
* legacy (list-shaped) rules holding a condition whose operator is not ``eq``,
  ``ne``, ``gt``, ``lt``, ``contains`` or ``in`` (or that has none). Such a
  rule matches no user (#733); the line says so, with the path of the first
  such condition. Every other legacy row gets the API's list refusal.

Connection settings are the ``POSTGRES_*`` environment variables that
``backend.app.db.bootstrap`` reads. Exit status: 0 whether or not anything is
listed (the report is advisory); 2 when the database cannot be read.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, List, Optional, Sequence, Tuple

from backend.app.core.targeting_adapter import (
    TargetingRulesError,
    validate_flag_targeting,
)
from backend.app.services.feature_flag_service import _LEGACY_OPERATORS

ENTITY = "feature_flag"

#: The path printed for a problem that belongs to the rules as a whole.
WHOLE_RULES_PATH = "targeting_rules"

#: The reason printed for a legacy rule that matches no user.
LEGACY_MATCHES_NO_USER = (
    "legacy condition whose operator is not eq, ne, gt, lt, contains or in; "
    "its rule matches no user"
)

#: The reason printed for a stored value the check itself could not read.
NOT_CHECKED = "could not be checked"


@dataclass(frozen=True)
class Finding:
    row_id: str
    key: str
    path: str
    reason: str

    def line(self) -> str:
        return "\t".join((ENTITY, self.row_id, self.key, self.path, self.reason))

    @property
    def matches_no_user(self) -> bool:
        return self.reason == LEGACY_MATCHES_NO_USER


def legacy_no_match_path(rules: List[Any]) -> Optional[str]:
    """Path of the first legacy condition that cannot match, or ``None``.

    Mirrors ``FeatureFlagService._evaluate_rule``: only a ``context`` rule
    reads conditions, and a condition matches only through one of
    ``_LEGACY_OPERATORS``.
    """
    for ri, rule in enumerate(rules):
        if not isinstance(rule, dict) or rule.get("type", "") != "context":
            continue
        conditions = rule.get("conditions", [])
        if not isinstance(conditions, list):
            continue
        for ci, condition in enumerate(conditions):
            if not isinstance(condition, dict):
                continue
            if condition.get("operator", "") not in _LEGACY_OPERATORS:
                return f"[{ri}].conditions[{ci}].operator"
    return None


def finding_for(row_id: Any, key: Any, rules: Any) -> Optional[Finding]:
    """The line for one stored flag, or ``None`` when the API accepts its rules."""
    row_id, key = str(row_id), str(key or "")
    if isinstance(rules, list):
        path = legacy_no_match_path(rules)
        if path is not None:
            return Finding(row_id, key, path, LEGACY_MATCHES_NO_USER)
    try:
        validate_flag_targeting(rules)
    except TargetingRulesError as err:
        return Finding(row_id, key, err.path or WHOLE_RULES_PATH, err.code)
    except Exception:
        return Finding(row_id, key, WHOLE_RULES_PATH, NOT_CHECKED)
    return None


def findings_for(rows: Iterable[Tuple[Any, Any, Any]]) -> Iterator[Finding]:
    """Findings for ``(id, key, targeting_rules)`` rows."""
    for row_id, key, rules in rows:
        found = finding_for(row_id, key, rules)
        if found is not None:
            yield found


def read_rows(connection: Any, schema: str) -> List[Tuple[Any, Any, Any]]:
    from sqlalchemy import text

    statement = text(
        f'SELECT id, "key", "targeting_rules" FROM "{schema}"."feature_flags" '
        'WHERE "targeting_rules" IS NOT NULL ORDER BY id'
    )
    return [tuple(row) for row in connection.execute(statement).all()]


def scan(connection: Any, schema: str) -> List[Finding]:
    """Every finding in the database behind ``connection`` (read-only)."""
    return list(findings_for(read_rows(connection, schema)))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.check_targeting_rules",
        description=(
            "List stored feature-flag targeting rules that a create or an "
            "update now refuses."
        ),
    )
    parser.parse_args(argv)

    from sqlalchemy import create_engine

    from backend.app.db.bootstrap import database_url, schema_name

    schema = schema_name()
    try:
        engine = create_engine(database_url())
    except Exception as exc:
        print(
            "check_targeting_rules: could not read the database "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 2
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            found = scan(connection, schema)
            connection.rollback()
    except Exception as exc:
        print(
            "check_targeting_rules: could not read the database "
            f"({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 2
    finally:
        engine.dispose()

    for finding in found:
        print(finding.line())
    no_match = sum(1 for f in found if f.matches_no_user)
    print(
        f"{len(found)} flag(s) listed: {len(found) - no_match} with rules the API "
        f"now refuses, {no_match} with a legacy rule that matches no user "
        f"(schema {schema!r}).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
