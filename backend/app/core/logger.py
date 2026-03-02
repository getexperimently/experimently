"""
Structured logging configuration using structlog.

* In production (``json_logs=True``) every log event is rendered as a
  single-line JSON object.  This is what CloudWatch Logs Insights expects.
* In development (``json_logs=False``) log events are rendered as
  human-readable colourised text via structlog's ``dev`` renderer.

Context variable support
------------------------
``bind_log_context`` and ``get_log_context`` let middleware or request
handlers attach fields (``request_id``, ``user_id``, …) that are then
automatically included in **every** log line produced during that request,
without callers having to pass a bound logger around.
"""

import contextvars
import logging
import sys
from typing import Any

import structlog

# ---------------------------------------------------------------------------
# Per-request context variable
# ---------------------------------------------------------------------------

_log_context: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "log_context", default={}
)


def bind_log_context(**kwargs: Any) -> None:
    """Merge *kwargs* into the current async-task log context.

    Later calls to this function for the same key will overwrite earlier ones.
    """
    current = _log_context.get().copy()
    current.update(kwargs)
    _log_context.set(current)


def get_log_context() -> dict:
    """Return a copy of the current async-task log context."""
    return _log_context.get().copy()


# ---------------------------------------------------------------------------
# structlog context-variable processor
# ---------------------------------------------------------------------------


def _inject_context(
    logger: Any,
    method: str,
    event_dict: dict,
) -> dict:
    """structlog processor: inject per-request context into every log event."""
    event_dict.update(_log_context.get())
    return event_dict


# ---------------------------------------------------------------------------
# Public configuration helpers
# ---------------------------------------------------------------------------


def configure_logging(
    log_level: str = "INFO",
    json_logs: bool = True,
    service_name: str = "experimentation-platform",
) -> None:
    """Configure structlog for the application.

    Should be called once at startup (e.g. from the FastAPI lifespan or
    ``main.py``).  Safe to call multiple times — each call replaces the
    previous configuration.

    Args:
        log_level: Python log-level name (``"DEBUG"``, ``"INFO"``, etc.).
        json_logs: ``True`` for JSON output (production/CloudWatch),
            ``False`` for colourised dev output.
        service_name: Value added to every log event under the ``service``
            key for log-aggregation filtering.
    """
    numeric_level: int = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        _inject_context,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_logs:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Also configure the standard-library root logger so that third-party
    # libraries that use ``logging.getLogger(...)`` are captured.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """Return a structlog BoundLogger bound to *name*.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        A structlog ``BoundLogger`` instance.
    """
    return structlog.get_logger(name)
