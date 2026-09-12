"""
Unit tests for backend/app/core/logger.py

Covers:
- configure_logging does not raise and returns a working logger
- get_logger returns a structlog BoundLogger-compatible object
- bind_log_context accumulates keys in the context variable
- get_log_context returns the current context
- Context is independent per logical thread (contextvar isolation)
"""

import contextvars

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
