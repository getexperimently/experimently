"""
List stored regex conditions that RE2 refuses or may now match differently.

Run after upgrading to the release in which regex conditions use RE2 syntax::

    python -m backend.scripts.check_regex_rules

It reads (and never writes) ``feature_flags.targeting_rules``,
``experiments.targeting_rules`` and ``segments.rules``, finds every ``regex``
/ ``match_regex`` condition in any stored shape, and prints one line per
finding with the row and the field path::

    feature_flag  3f0c...  checkout-v2  groups[0].conditions[1].value  REFUSED  invalid perl operator: (?<=

Findings:

``REFUSED``
    RE2 will not compile the pattern (lookaround, backreferences, ``\\Z``,
    ``(?x)``, a repetition over 1000, a very large Unicode repetition, ...).
    The rules holding it are not applied: a flag evaluates disabled with
    reason ``error``, a user is not eligible for the experiment, a user is not
    a segment member. Rewrite the pattern in RE2 syntax.
``ASCII_CLASS``
    The pattern uses ``\\w``, ``\\d``, ``\\s`` or ``\\b`` (or their negations),
    which RE2 matches against ASCII only. Use ``\\p{L}``, ``\\p{N}`` or
    ``[[:alpha:]]`` if non-ASCII values should match.
``DOLLAR``
    The pattern uses ``$``, which RE2 matches only at the very end of the
    value, not before a final newline.

Connection settings are the ``POSTGRES_*`` environment variables that
``backend.app.db.bootstrap`` reads. Exit status: 0 whether or not anything is
found (the report is advisory); 2 when the database cannot be read.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, List, Optional, Sequence, Tuple

from backend.app.core.pattern_match import compile_error, iter_rule_patterns

#: (entity label, table, label column, rules column)
SOURCES: Tuple[Tuple[str, str, str, str], ...] = (
    ("feature_flag", "feature_flags", "key", "targeting_rules"),
    ("experiment", "experiments", "name", "targeting_rules"),
    ("segment", "segments", "name", "rules"),
)

REFUSED = "REFUSED"
ASCII_CLASS = "ASCII_CLASS"
DOLLAR = "DOLLAR"

_ASCII_CLASSES = frozenset("wWdDsSbB")


@dataclass(frozen=True)
class Finding:
    entity: str
    row_id: str
    label: str
    path: str
    kind: str
    detail: str

    def line(self) -> str:
        return "\t".join(
            (self.entity, self.row_id, self.label, self.path, self.kind, self.detail)
        )


def _pattern_chars(pattern: str) -> Iterator[Tuple[str, bool, bool]]:
    """Yield ``(char, after_backslash, inside_brackets)`` for each character."""
    in_class = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            yield pattern[index + 1], True, in_class
            index += 2
            continue
        if char == "[" and not in_class:
            in_class = True
        elif char == "]" and in_class:
            in_class = False
        yield char, False, in_class
        index += 1


def classify(pattern: Any) -> List[Tuple[str, str]]:
    """``(kind, detail)`` for everything worth telling an operator about ``pattern``."""
    refusal = compile_error(pattern)
    if refusal is not None:
        return [(REFUSED, refusal)]
    classes = sorted(
        {
            c
            for c, backslashed, _ in _pattern_chars(pattern)
            if backslashed and c in _ASCII_CLASSES
        }
    )
    found: List[Tuple[str, str]] = []
    if classes:
        found.append(
            (ASCII_CLASS, "ASCII only: " + " ".join("\\" + c for c in classes))
        )
    if any(
        c == "$" and not backslashed and not in_class
        for c, backslashed, in_class in _pattern_chars(pattern)
    ):
        found.append((DOLLAR, "matches only at the very end of the value"))
    return found


def findings_for(
    entity: str, rows: Iterable[Tuple[Any, Any, Any]]
) -> Iterator[Finding]:
    """Findings for ``(id, label, rules)`` rows of one entity."""
    for row_id, label, rules in rows:
        for path, pattern in iter_rule_patterns(rules):
            for kind, detail in classify(pattern):
                yield Finding(entity, str(row_id), str(label or ""), path, kind, detail)


def read_rows(connection: Any, schema: str, table: str, label: str, column: str):
    from sqlalchemy import text

    statement = text(
        f'SELECT id, "{label}", "{column}" FROM "{schema}"."{table}" '
        f'WHERE "{column}" IS NOT NULL ORDER BY id'
    )
    return connection.execute(statement).all()


def scan(connection: Any, schema: str) -> List[Finding]:
    """Every finding in the database behind ``connection`` (read-only)."""
    found: List[Finding] = []
    for entity, table, label, column in SOURCES:
        found.extend(
            findings_for(entity, read_rows(connection, schema, table, label, column))
        )
    return found


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.check_regex_rules",
        description="List stored regex conditions that RE2 refuses or may match differently.",
    )
    parser.parse_args(argv)

    from sqlalchemy import create_engine

    from backend.app.db.bootstrap import database_url, schema_name

    schema = schema_name()
    engine = create_engine(database_url())
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            found = scan(connection, schema)
            connection.rollback()
    except Exception as exc:
        print(f"check_regex_rules: could not read the database: {exc}", file=sys.stderr)
        return 2
    finally:
        engine.dispose()

    for finding in found:
        print(finding.line())
    refused = sum(1 for f in found if f.kind == REFUSED)
    print(
        f"{len(found)} finding(s), {refused} refused by RE2 "
        f"(schema {schema!r}: feature_flags, experiments, segments).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
