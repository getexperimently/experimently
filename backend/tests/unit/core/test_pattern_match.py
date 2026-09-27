"""
``backend/app/core/pattern_match.py``: regex conditions, evaluated with RE2.

These pin the engine (RE2, not Python's ``re``), the syntax and semantics a
stored pattern now gets, the input-length rule, the compile options, the
failure cache, and that nothing identifying a pattern or a value leaks out of
the exception the rules engine raises.
"""

from __future__ import annotations

import pytest

from backend.app.core import pattern_match
from backend.app.core.pattern_match import (
    MAX_REGEX_INPUT,
    PatternResult,
    PatternUnevaluable,
    UnevaluableReason,
    compile_error,
    evaluate,
    iter_rule_patterns,
    pattern_options,
    search,
)

pytestmark = pytest.mark.unit

MATCH = PatternResult.MATCH
NO_MATCH = PatternResult.NO_MATCH
UNEVALUABLE = PatternResult.UNEVALUABLE


class _Recorder:
    """Stands in for the module logger; keeps each formatted warning."""

    def __init__(self):
        self.messages = []

    def warning(self, message, *args):
        self.messages.append(message % args)


@pytest.fixture
def warnings_logged(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(pattern_match, "logger", recorder)
    return recorder.messages


@pytest.fixture(autouse=True)
def _fresh_cache():
    pattern_match.clear_compiled_patterns()
    pattern_match._reported.clear()
    yield
    pattern_match.clear_compiled_patterns()
    pattern_match._reported.clear()


# -- the engine ---------------------------------------------------------------


@pytest.mark.regression
def test_a_backreference_is_refused():
    """Python's ``re`` accepts ``(a)\\1``; RE2 refuses it. Only RE2 passes this."""
    assert compile_error(r"(a)\1") is not None
    assert evaluate(r"(a)\1", "aa") is UNEVALUABLE


@pytest.mark.regression
def test_patterns_are_compiled_by_re2():
    compiled = pattern_match._compiled(r"^a+$")
    assert type(compiled).__module__.split(".")[0] == "re2", type(compiled)


def test_the_compile_options():
    options = pattern_options()
    assert options.max_mem == pattern_match.PATTERN_MEMORY_BYTES == 2 << 20
    assert options.log_errors is False
    assert pattern_match.MAX_COMPILED_PATTERNS == 128


# -- syntax and semantics -----------------------------------------------------

#: Where RE2 answers differently from Python's ``re``. RE2's answer is the
#: intended one; the release notes describe each.
DIVERGENT = [
    pytest.param(r"^\w+$", "café", NO_MATCH, id="w-is-ascii"),
    pytest.param(r"^\d+$", "٣٤", NO_MATCH, id="d-is-ascii"),
    pytest.param(r"^a\sb$", "a b", NO_MATCH, id="s-is-ascii"),
    pytest.param(r"\bcaf\b", "café", MATCH, id="word-boundary-is-ascii"),
    pytest.param(r"a$", "a\n", NO_MATCH, id="dollar-before-final-newline"),
    pytest.param(r"^[[:alpha:]]+$", "abc", MATCH, id="posix-class-supported"),
]

#: Unchanged between the two engines.
UNCHANGED = [
    pytest.param(r"(?i)@ACME\.COM$", "bob@acme.com", MATCH, id="case-insensitive"),
    pytest.param(r"(?s)^a.b$", "a\nb", MATCH, id="dot-all"),
    pytest.param(r"^(?P<user>[a-z]+)@", "bob@acme.com", MATCH, id="named-group"),
    pytest.param(r"acme", "x acme y", MATCH, id="search-not-anchored"),
    pytest.param(r"^acme", "x acme", NO_MATCH, id="anchored"),
    pytest.param(
        r"^\+1-\d{3}-\d{3}-\d{4}$", "+1-555-123-4567", MATCH, id="phone-example"
    ),
    pytest.param(
        r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
        "a.b+c@example.io",
        MATCH,
        id="email-example",
    ),
    pytest.param(r"^\p{L}+$", "café", MATCH, id="unicode-letters"),
    pytest.param(r"^a$", "a", MATCH, id="dollar-at-end"),
    pytest.param(r"@competitor\.com$", "bob@competitor.com", MATCH, id="suffix"),
]


@pytest.mark.parametrize("pattern,value,expected", DIVERGENT + UNCHANGED)
def test_semantics(pattern, value, expected):
    assert evaluate(pattern, value) is expected


def test_a_non_string_value_is_compared_as_text():
    assert evaluate(r"^\d+$", 17) is MATCH
    assert evaluate(r"^True$", True) is MATCH


#: Constructs RE2 refuses (Python's ``re`` accepts every one of them).
REFUSED = [
    pytest.param(r"(?=a)a", id="lookahead"),
    pytest.param(r"(?!a)b", id="negative-lookahead"),
    pytest.param(r"(?<=a)b", id="lookbehind"),
    pytest.param(r"(?<!a)b", id="negative-lookbehind"),
    pytest.param(r"(a)\1", id="backreference"),
    pytest.param(r"(?P<x>a)(?P=x)", id="named-backreference"),
    pytest.param(r"a\Z", id="backslash-Z"),
    pytest.param(r"(?x) a", id="verbose-flag"),
    pytest.param(r"(?u)a", id="unicode-flag"),
    pytest.param(r"(?a)a", id="ascii-flag"),
    pytest.param(r"\N{EM DASH}", id="named-character"),
    pytest.param(r"a{1001}", id="repetition-over-1000"),
    pytest.param(r"[\p{L}\p{N}]{1,300}", id="large-unicode-repetition"),
    pytest.param(r"[a-", id="unterminated-class"),
]


@pytest.mark.parametrize("pattern", REFUSED)
def test_refused_constructs(pattern):
    message = compile_error(pattern)
    assert message, pattern
    assert evaluate(pattern, "a") is UNEVALUABLE
    with pytest.raises(PatternUnevaluable) as info:
        search(pattern, "a")
    assert info.value.reason is UnevaluableReason.REFUSED


def test_the_refusal_is_re2s_own_text():
    assert compile_error(r"(?<=a)b") == "invalid perl operator: (?<="
    assert compile_error(r"[\p{L}\p{N}]{1,300}") == "pattern too large - compile failed"


def test_a_pattern_that_is_not_a_string_is_unevaluable():
    assert compile_error(42) == "pattern is not a string"
    assert evaluate(None, "a") is UNEVALUABLE
    with pytest.raises(PatternUnevaluable) as info:
        search(["a"], "a")
    assert info.value.reason is UnevaluableReason.NOT_A_STRING


def _domains(count: int) -> str:
    return "@(" + "|".join(f"d{i}\\.example\\.com" for i in range(count)) + ")$"


#: Realistic patterns: every one must compile under the chosen memory budget.
REALISTIC = [
    pytest.param(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", id="email"),
    pytest.param(
        r"^\+?[0-9]{1,3}[-. ]?[0-9]{3}[-. ]?[0-9]{3,4}[-. ]?[0-9]{4}$", id="phone"
    ),
    pytest.param(r"@acme\.com$", id="suffix"),
    pytest.param(r"(?i)@acme\.com$", id="suffix-case-insensitive"),
    pytest.param(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", id="uuid"
    ),
    pytest.param(
        r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
        r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
        r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$",
        id="semver",
    ),
    pytest.param(_domains(1000), id="1000-domain-alternation"),
    pytest.param(r"^\p{L}{1,100}$", id="unicode-letters-1-100"),
    pytest.param(r"\b(premium|enterprise|beta)\b", id="word-list"),
]


@pytest.mark.parametrize("pattern", REALISTIC)
def test_realistic_patterns_compile_under_the_memory_budget(pattern):
    assert compile_error(pattern) is None


def test_the_domain_alternation_matches_at_the_input_limit():
    value = "x" * (MAX_REGEX_INPUT - len("@d999.example.com")) + "@d999.example.com"
    assert len(value) == MAX_REGEX_INPUT
    assert evaluate(_domains(1000), value) is MATCH


# -- input length -------------------------------------------------------------


@pytest.mark.regression
def test_a_value_of_exactly_the_limit_is_evaluated():
    assert evaluate(r"^[a-z]+$", "a" * MAX_REGEX_INPUT) is MATCH
    assert evaluate(r"^[a-z]+$", "a" * (MAX_REGEX_INPUT - 1) + "!") is NO_MATCH


@pytest.mark.regression
def test_a_value_over_the_limit_is_not_evaluated():
    """Not truncated: the limit's worth of a's would match."""
    over = "a" * MAX_REGEX_INPUT + "!"
    assert evaluate(r"^[a-z]+$", over) is UNEVALUABLE
    assert evaluate(r"^[a-z]+$", "a" * (MAX_REGEX_INPUT + 1)) is UNEVALUABLE
    with pytest.raises(PatternUnevaluable) as info:
        search(r"^[a-z]+$", over)
    assert info.value.reason is UnevaluableReason.INPUT_LENGTH


# -- values that cannot be encoded -------------------------------------------


@pytest.mark.regression
def test_a_lone_surrogate_is_unevaluable_not_an_encoding_error():
    assert evaluate(r"a", "\ud800") is UNEVALUABLE
    with pytest.raises(PatternUnevaluable) as info:
        search(r"a", "x\ud800y")
    assert info.value.reason is UnevaluableReason.INPUT_ENCODING


def test_a_lone_surrogate_in_the_pattern_is_refused():
    assert compile_error("a\ud800") is not None


# -- the failure cache --------------------------------------------------------


def test_a_refused_pattern_is_compiled_once(monkeypatch):
    calls = []
    real = pattern_match._compile_uncached

    def counting(pattern):
        calls.append(pattern)
        return real(pattern)

    monkeypatch.setattr(pattern_match, "_compile_uncached", counting)
    for _ in range(3):
        assert evaluate(r"(?<=a)b", "ab") is UNEVALUABLE
    assert compile_error(r"(?<=a)b")
    assert calls == [r"(?<=a)b"]


def test_an_accepted_pattern_is_compiled_once(monkeypatch):
    calls = []
    real = pattern_match._compile_uncached
    monkeypatch.setattr(
        pattern_match, "_compile_uncached", lambda p: calls.append(p) or real(p)
    )
    for _ in range(3):
        assert evaluate(r"^b", "b") is MATCH
    assert calls == [r"^b"]


# -- nothing identifying leaks ------------------------------------------------

PATTERN_MARK = r"(?<=PATTERNMARK)x"
VALUE_MARK = "VALUEMARK"


@pytest.mark.parametrize(
    "pattern,value",
    [
        (PATTERN_MARK, VALUE_MARK),
        (r"PATTERNMARK", VALUE_MARK * MAX_REGEX_INPUT),
        (r"PATTERNMARK", VALUE_MARK + "\ud800"),
    ],
    ids=["refused", "too-long", "surrogate"],
)
def test_the_exception_carries_neither_pattern_nor_value(
    pattern, value, warnings_logged
):
    with pytest.raises(PatternUnevaluable) as info:
        search(pattern, value)
    exc = info.value
    for text in (str(exc), repr(exc), " ".join(map(str, exc.args))):
        assert "PATTERNMARK" not in text
        assert VALUE_MARK not in text
    assert str(exc) == "pattern condition could not be evaluated"

    pattern_match.report_unevaluable(exc, f"flag:leak-check-{exc.reason.value}")
    assert warnings_logged, "the first occurrence is logged"
    for message in warnings_logged:
        assert "PATTERNMARK" not in message
        assert VALUE_MARK not in message


def test_it_is_logged_once_per_pattern_and_place(warnings_logged):
    exc = PatternUnevaluable(
        UnevaluableReason.REFUSED, pattern_match.pattern_digest("once")
    )
    for _ in range(3):
        pattern_match.report_unevaluable(exc, "flag:once-a")
    pattern_match.report_unevaluable(exc, "flag:once-b")
    assert len(warnings_logged) == 2
    assert all(exc.digest in message for message in warnings_logged)


# -- finding patterns in stored rules ----------------------------------------


def test_patterns_are_found_in_every_stored_shape():
    dashboard = {
        "logical_operator": "AND",
        "groups": [
            {
                "logical_operator": "NOT",
                "conditions": [
                    {"attribute": "email", "operator": "regex", "value": "@a\\.com$"},
                    {"attribute": "country", "operator": "equals", "value": "US"},
                ],
            }
        ],
    }
    native = {
        "rules": [
            {
                "id": "r1",
                "rule": {
                    "operator": "and",
                    "conditions": [],
                    "groups": [
                        {
                            "operator": "or",
                            "conditions": [
                                {
                                    "attribute": "e",
                                    "operator": "match_regex",
                                    "value": "^b",
                                }
                            ],
                        }
                    ],
                },
            }
        ],
        "default_rule": {
            "id": "d",
            "rule": {
                "operator": "and",
                "conditions": [
                    {"attribute": "e", "operator": "MATCH_REGEX", "value": 7}
                ],
            },
        },
    }
    segment = {
        "operator": "and",
        "conditions": [{"attribute": "e", "operator": "match_regex", "value": "c$"}],
    }
    assert list(iter_rule_patterns(dashboard)) == [
        ("groups[0].conditions[0].value", "@a\\.com$")
    ]
    assert list(iter_rule_patterns(native)) == [
        ("rules[0].rule.groups[0].conditions[0].value", "^b"),
        ("default_rule.rule.conditions[0].value", 7),
    ]
    assert list(iter_rule_patterns(segment)) == [("conditions[0].value", "c$")]
    assert list(iter_rule_patterns(None)) == []
    assert list(iter_rule_patterns([{"type": "context", "conditions": []}])) == []
