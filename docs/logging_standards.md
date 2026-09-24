# Logging Standards

Logging is **structlog**, configured once in `backend/app/core/logger.py`.
In production every event renders as a single-line JSON object, which is what
CloudWatch Logs Insights expects; in development it renders as colourised text
through structlog's `dev` renderer. The switch is `json_logs`.

## Getting a logger

```python
from backend.app.core.logger import get_logger

logger = get_logger(__name__)
```

Pass structured data as **keyword arguments**, not string interpolation and
not `extra={...}`:

```python
logger.info("experiment assigned", experiment_key=key, variant=variant.name)
logger.warning("cache miss", cache="evaluation", key=cache_key)
logger.error("failed to reach the warehouse", warehouse="snowflake", exc_info=True)
```

Every keyword becomes its own JSON field, so `variant="control"` is queryable
in Logs Insights. Interpolating it into the message (`f"variant {variant}"`)
buries it in a string and is not.

## Fields on every line

Added by the shared processor chain, without the caller doing anything:

| field | source |
|---|---|
| `timestamp` | `TimeStamper(fmt="iso")` |
| `level` | `add_log_level` |
| `event` | the message — structlog's name for it, not `message` |
| `logger` | `add_logger_name` |
| `service` | `_add_service`, the configured service name |
| `exception` | `format_exc_info`, only in JSON mode and only when `exc_info` is set |

## Per-request fields

`RequestIDMiddleware` binds these to the async context, so **every** log line
emitted while handling a request carries them, with no bound logger passed
around:

| field | value |
|---|---|
| `request_id` | also returned to the client as the `X-Request-ID` header |
| `path` | the request path |
| `method` | the HTTP method |

To add your own for the rest of a request:

```python
from backend.app.core.logger import bind_log_context

bind_log_context(user_id=str(user.id), workspace_id=str(ws.id))
```

`request_id` is the field to correlate on. It appears on every line of a
request and is handed back to the caller in the response header, so a user
reporting an error can quote it.

## Levels

| level | use |
|---|---|
| `DEBUG` | detail for local debugging; not enabled in production |
| `INFO` | normal operational events — an assignment made, a rollout stage advanced |
| `WARNING` | something recoverable that may need attention — a cache miss on a hot path, a retry |
| `ERROR` | an operation failed and a user saw it; include `exc_info=True` |
| `CRITICAL` | the service cannot continue |

## What must never be logged

No credentials, API keys, tokens, password hashes, or PHI.

**Know which half of the system masks.** `LoggingMiddleware` runs request and
response bodies through `backend/app/utils/masking.py`, which blanks
`password`, `token`, `api_key`, `secret`, `credential`, `authorization`,
`access_token`, `refresh_token`, `private_key` and friends, and partially
masks emails, phone numbers, credit card numbers and IP addresses. See
[Logging Middleware](middleware/logging.md).

That masking applies to what the **middleware** logs. A keyword you pass to
`logger.info(...)` yourself does **not** go through it — it lands in CloudWatch
verbatim. So the rule for your own call sites stands: log the identifier, not
the object. A `User` or a tracking payload carries an email address or an
attribute you did not mean to persist.
