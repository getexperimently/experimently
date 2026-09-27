"""`python -m backend.scripts.check_regex_rules` -- the post-upgrade report."""

from __future__ import annotations

import pytest

from backend.app.core import pattern_match
from backend.scripts import check_regex_rules as check

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _fresh_cache():
    pattern_match.clear_compiled_patterns()
    yield
    pattern_match.clear_compiled_patterns()


def _dashboard(*patterns):
    return {
        "logical_operator": "AND",
        "groups": [
            {
                "logical_operator": "AND",
                "conditions": [
                    {"attribute": "email", "operator": "regex", "value": p}
                    for p in patterns
                ],
            }
        ],
    }


def test_one_refused_and_one_ascii_class_pattern():
    rows = [
        ("id-1", "checkout", _dashboard(r"(?<=@)acme\.com", r"^\w+@acme")),
        ("id-2", "clean", _dashboard(r"@acme\.com")),
        ("id-3", "no-rules", None),
    ]
    lines = [f.line() for f in check.findings_for("feature_flag", rows)]
    assert lines == [
        "feature_flag\tid-1\tcheckout\tgroups[0].conditions[0].value"
        "\tREFUSED\tinvalid perl operator: (?<=",
        "feature_flag\tid-1\tcheckout\tgroups[0].conditions[1].value"
        "\tASCII_CLASS\tASCII only: \\w",
    ]


@pytest.mark.parametrize(
    "pattern,kinds",
    [
        (r"@acme\.com$", ["DOLLAR"]),
        (r"price \$5", []),
        (r"[$]", []),
        (r"^\d+\s\S$", ["ASCII_CLASS", "DOLLAR"]),
        (r"\\w", []),
        (r"\bword\b", ["ASCII_CLASS"]),
        (r"[\p{L}\p{N}]{1,300}", ["REFUSED"]),
        (r"^[a-z]+$", ["DOLLAR"]),
        (r"(?i)^acme", []),
    ],
)
def test_classify(pattern, kinds):
    assert [kind for kind, _ in check.classify(pattern)] == kinds


def test_a_non_string_pattern_is_reported_as_refused():
    assert check.classify(123) == [("REFUSED", "pattern is not a string")]


def test_the_report_uses_the_evaluation_options():
    """A pattern too large for the evaluator must be reported, not passed."""
    assert pattern_match.compile_error(r"[\p{L}\p{N}]{1,300}") is not None
    assert check.classify(r"[\p{L}\p{N}]{1,300}")[0][0] == "REFUSED"


def test_every_source_is_read(monkeypatch):
    seen = []

    def fake_rows(connection, schema, table, label, column):
        seen.append((schema, table, label, column))
        return [("row", "name", _dashboard("(?x)a"))]

    monkeypatch.setattr(check, "read_rows", fake_rows)
    found = check.scan(object(), "exp")
    assert [f.entity for f in found] == ["feature_flag", "experiment", "segment"]
    assert seen == [
        ("exp", "feature_flags", "key", "targeting_rules"),
        ("exp", "experiments", "name", "targeting_rules"),
        ("exp", "segments", "name", "rules"),
    ]
