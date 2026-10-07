"""
Unit tests for backend/app/core/logger.py

Covers:
- configure_logging does not raise and returns a working logger
- get_logger returns a structlog BoundLogger-compatible object
- bind_log_context accumulates keys in the context variable
- get_log_context returns the current context
- Context is independent per logical thread (contextvar isolation)
"""

import contextlib
import contextvars
import io
import json
import logging
from unittest.mock import patch

import pytest


def test_configure_logging_sets_level():
    from backend.app.core.logger import configure_logging, get_logger

    # Should not raise for any combination of parameters
    configure_logging(log_level="DEBUG", json_logs=False)
    logger = get_logger("test_configure_logging")
    assert logger is not None


def test_configure_logging_json_mode():
    from backend.app.core.logger import configure_logging, get_logger

    configure_logging(log_level="INFO", json_logs=True, service_name="test-svc")
    logger = get_logger("test_json_mode")
    assert logger is not None


def test_get_logger_returns_bound_logger():
    from backend.app.core.logger import get_logger

    logger = get_logger("my.test.module")
    assert logger is not None
    # structlog bound loggers have an .info method
    assert callable(getattr(logger, "info", None))


def test_bind_log_context_accumulates():
    # Reset context by setting an empty dict in a fresh token
    import backend.app.core.logger as _mod
    from backend.app.core.logger import bind_log_context, get_log_context

    token = _mod._log_context.set({})

    try:
        bind_log_context(request_id="abc123")
        bind_log_context(user_id="user-1")
        ctx = get_log_context()
        assert ctx["request_id"] == "abc123"
        assert ctx["user_id"] == "user-1"
    finally:
        _mod._log_context.reset(token)


def test_bind_log_context_overwrites_existing_key():
    import backend.app.core.logger as _mod
    from backend.app.core.logger import bind_log_context, get_log_context

    token = _mod._log_context.set({})

    try:
        bind_log_context(request_id="first")
        bind_log_context(request_id="second")
        ctx = get_log_context()
        assert ctx["request_id"] == "second"
    finally:
        _mod._log_context.reset(token)


def test_get_log_context_empty_by_default():
    import backend.app.core.logger as _mod
    from backend.app.core.logger import get_log_context

    token = _mod._log_context.set({})

    try:
        ctx = get_log_context()
        assert isinstance(ctx, dict)
    finally:
        _mod._log_context.reset(token)


def test_bind_log_context_multiple_keys_at_once():
    import backend.app.core.logger as _mod
    from backend.app.core.logger import bind_log_context, get_log_context

    token = _mod._log_context.set({})

    try:
        bind_log_context(request_id="xyz", path="/health", method="GET")
        ctx = get_log_context()
        assert ctx["request_id"] == "xyz"
        assert ctx["path"] == "/health"
        assert ctx["method"] == "GET"
    finally:
        _mod._log_context.reset(token)


def test_get_logger_accepts_module_name():
    from backend.app.core.logger import get_logger

    # __name__ is a common call pattern — must not raise
    logger = get_logger(__name__)
    assert logger is not None


# ---------------------------------------------------------------------------
# current_request_id: the id a response body may show
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "bound,expected",
    [
        ("prb-b-123", "prb-b-123"),
        ("a" * 128, "a" * 128),
        ("a" * 129, None),
        ("abc\n", None),
        ("<b>x</b>", None),
        ("", None),
        (12345, None),
        (None, None),
    ],
)
def test_current_request_id_shows_only_a_well_formed_id(bound, expected):
    import backend.app.core.logger as _mod
    from backend.app.core.logger import current_request_id

    token = _mod._log_context.set({"request_id": bound})
    try:
        assert current_request_id() == expected
    finally:
        _mod._log_context.reset(token)


@pytest.mark.regression
def test_current_request_id_is_none_without_a_bound_id():
    import backend.app.core.logger as _mod
    from backend.app.core.logger import current_request_id

    token = _mod._log_context.set({})
    try:
        assert current_request_id() is None
    finally:
        _mod._log_context.reset(token)


# ---------------------------------------------------------------------------
# failure_detail: the fixed sentence a failed request answers
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "bound,expected",
    [
        ("prb-398-1", "Could not store the event (request ID: prb-398-1)."),
        ("a" * 129, "Could not store the event."),
        ("<b>x</b>", "Could not store the event."),
        (None, "Could not store the event."),
    ],
)
def test_failure_detail_adds_only_a_well_formed_request_id(bound, expected):
    import backend.app.core.logger as _mod
    from backend.app.core.logger import failure_detail

    token = _mod._log_context.set({"request_id": bound})
    try:
        assert failure_detail("Could not store the event") == expected
    finally:
        _mod._log_context.reset(token)


@pytest.mark.regression
def test_failure_detail_ends_the_sentence_without_a_bound_id():
    import backend.app.core.logger as _mod
    from backend.app.core.logger import failure_detail

    token = _mod._log_context.set({})
    try:
        assert (
            failure_detail("Could not store this event")
            == "Could not store this event."
        )
    finally:
        _mod._log_context.reset(token)


# ---------------------------------------------------------------------------
# The level a rendered line carries: what the error-log alarm counts (#811)
# ---------------------------------------------------------------------------

# The ApiErrorLogs metric filter counts the lines matching
#     { ($.level = "error") || ($.level = "critical") }
# (infrastructure/cdk/stacks/fargate_service_stack.py, pinned in
# infrastructure/tests/test_standing_alarms.py). CloudWatch compares the
# values case-sensitively, so a line whose level is "ERROR" is not counted.


@contextlib.contextmanager
def _json_lines():
    """Every record rendered as the production JSON line, into a buffer.

    The unit conftest replaces ``logging.getLogger`` with a mock, which
    ``configure_logging`` and structlog's stdlib logger factory both call, so
    the real one is put back for the duration; the root handlers and the
    structlog configuration are restored afterwards.
    """
    import structlog

    from backend.app.core.logger import configure_logging

    def real_get_logger(name=None):
        return logging.Logger.manager.getLogger(name) if name else logging.root

    root = logging.root
    handlers, root_level = list(root.handlers), root.level
    saved = structlog.get_config()
    buffer = io.StringIO()
    with patch("logging.getLogger", real_get_logger):
        configure_logging(log_level="INFO", json_logs=True, stream=buffer)
        try:
            yield buffer
        finally:
            for handler in list(root.handlers):
                root.removeHandler(handler)
            for handler in handlers:
                root.addHandler(handler)
            root.setLevel(root_level)
            structlog.configure(**saved)


def _stdlib(name, method):
    def emit():
        logger = logging.Logger.manager.getLogger(name)
        if method == "exception":
            try:
                raise ValueError("probe")
            except ValueError:
                logger.exception("probe line")
        else:
            getattr(logger, method)("probe line")

    return emit


def _structlog(method):
    def emit():
        from backend.app.core.logger import get_logger

        logger = get_logger("probe.structlog")
        if method == "exception":
            try:
                raise ValueError("probe")
            except ValueError:
                logger.exception("probe line")
        else:
            getattr(logger, method)("probe line")

    return emit


def _unexpected_failure():
    from backend.app.core.logger import unexpected_failure

    unexpected_failure(
        ValueError("probe"),
        "Probe",
        "Could not probe",
        logger=logging.Logger.manager.getLogger("probe.failure"),
    )


@pytest.mark.regression
@pytest.mark.parametrize(
    "emit,expected",
    [
        (_stdlib("probe.stdlib", "error"), "error"),
        (_stdlib("probe.stdlib", "critical"), "critical"),
        (_stdlib("probe.stdlib", "exception"), "error"),
        # An exception in a request handler that nothing caught.
        (_stdlib("uvicorn.error", "error"), "error"),
        (_structlog("error"), "error"),
        (_structlog("critical"), "critical"),
        (_structlog("exception"), "error"),
        # A handler's 500 through unexpected_failure is one error line.
        (_unexpected_failure, "error"),
        # Not counted.
        (_stdlib("probe.stdlib", "warning"), "warning"),
        (_structlog("warning"), "warning"),
        (_stdlib("probe.stdlib", "info"), "info"),
    ],
    ids=[
        "stdlib-error",
        "stdlib-critical",
        "stdlib-exception",
        "uvicorn-error",
        "structlog-error",
        "structlog-critical",
        "structlog-exception",
        "unexpected_failure",
        "stdlib-warning",
        "structlog-warning",
        "stdlib-info",
    ],
)
def test_a_rendered_line_carries_the_level_the_error_log_alarm_counts(emit, expected):
    """The logger's half of the error-log alarm (#811).

    The metric filter matches the JSON ``level`` field against the lower-case
    values ``"error"`` and ``"critical"``. A line rendered by
    ``configure_logging(json_logs=True)`` -- what the API writes in staging and
    production -- must carry exactly those values for error and critical
    records, and a value outside them for every lower level. A logger that
    wrote ``"ERROR"`` would make the alarm count nothing, as it did while the
    filter matched the term ``ERROR`` against lines whose level is ``"error"``.
    """
    with _json_lines() as buffer:
        emit()

    (line,) = [json.loads(text) for text in buffer.getvalue().splitlines() if text]
    assert line["level"] == expected, line
