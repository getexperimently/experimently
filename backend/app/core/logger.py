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
import os
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
    stream: Any = None,
) -> None:
    """Configure structlog **and** the standard library for the application.

    Should be called once at startup (e.g. from ``main.py``). Safe to call
    multiple times — each call replaces the previous configuration.

    Both structlog loggers (``get_logger``) and plain ``logging.getLogger``
    loggers (the majority of the codebase, plus uvicorn, sqlalchemy, ...) are
    rendered by the same :class:`structlog.stdlib.ProcessorFormatter` on a
    single root handler, so with ``json_logs=True`` **every** line the process
    writes is one JSON object (``LOG_FORMAT=json`` in production/containers)
    and with ``json_logs=False`` every line is the coloured console format.

    Args:
        log_level: Python log-level name (``"DEBUG"``, ``"INFO"``, etc.).
        json_logs: ``True`` for JSON output (production/CloudWatch),
            ``False`` for colourised dev output.
        service_name: Value added to every log event under the ``service``
            key for log-aggregation filtering.
        stream: Destination stream (defaults to ``sys.stdout``).
    """
    numeric_level: int = getattr(logging, log_level.upper(), logging.INFO)
    stream = stream or sys.stdout

    def _add_service(logger: Any, method: str, event_dict: dict) -> dict:
        event_dict.setdefault("service", service_name)
        return event_dict

    # Processors shared by structlog events and foreign (stdlib) records.
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        _inject_context,
        _add_service,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_logs:
        renderer: Any = structlog.processors.JSONRenderer()
        # Turn exc_info into a string field ("exception") for JSON output.
        pre_render: list = [structlog.processors.format_exc_info]
    else:
        renderer = structlog.dev.ConsoleRenderer()
        pre_render = []

    structlog.configure(
        processors=shared_processors
        + [
            # Hand the event dict to the stdlib handler/formatter below.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # Processors applied to every record right before rendering.
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta]
        + pre_render
        + [renderer],
        # Processors applied to records that did NOT originate from structlog.
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(numeric_level)

    # uvicorn installs its own handlers (plain text, propagate=False). Route
    # them through the root handler so access/error lines share the format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        for existing in list(uv_logger.handlers):
            uv_logger.removeHandler(existing)
        uv_logger.propagate = True


def log_format_from_env(default: str = "console") -> str:
    """Resolve ``LOG_FORMAT`` (``json`` | ``console``) from the environment."""
    value = os.environ.get("LOG_FORMAT", "").strip().lower()
    if value in ("json", "console", "text"):
        return "json" if value == "json" else "console"
    return default


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """Return a structlog BoundLogger bound to *name*.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        A structlog ``BoundLogger`` instance.
    """
    return structlog.get_logger(name)
