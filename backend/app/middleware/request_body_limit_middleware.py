"""One limit on the size of every request body, answered 413.

The limit is ``MAX_REQUEST_BODY_SIZE`` in ``backend/app/main.py``, passed in
when the layer is registered there. Two checks, for the two ways a client can
send a body:

* **Declared.** A ``Content-Length`` above the limit is answered 413 at once,
  before anything reads the body.
* **Counted.** Every request body, declared or chunked, is counted as the
  application reads it. The read that takes the count past the limit raises
  ``HTTPException(413)``, and nothing reads further.

It raises ``starlette.exceptions.HTTPException`` and nothing else on purpose:
FastAPI's body parsing re-raises that one exception and turns any other into a
400 ("There was an error parsing the body"). Starlette's exception middleware,
between every user middleware and the router, answers it.

A ``Content-Length`` that does not parse as a non-negative integer is not
answered here: the request goes on to the counted check, which holds whatever
the header says.

Both answers carry ``Connection: close``, so the server reads nothing more from
a client that may still be sending.

A plain ASGI layer, not ``BaseHTTPMiddleware``: it has to see each body message
as it arrives, and it buffers nothing itself.
"""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_CLOSE = {"Connection": "close"}


def _declared_length(scope: Scope) -> int | None:
    """The request's ``Content-Length``, or None when it is absent or unparsable."""
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                length = int(value)
            except ValueError:
                return None
            return length if length >= 0 else None
    return None


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_size: int) -> None:
        self.app = app
        self.max_body_size = max_body_size
        self.detail = f"Request body larger than {max_body_size} bytes"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _declared_length(scope)
        if declared is not None and declared > self.max_body_size:
            response = JSONResponse(
                {"detail": self.detail}, status_code=413, headers=_CLOSE
            )
            await response(scope, receive, send)
            return

        received = 0

        async def counted_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_size:
                    raise HTTPException(413, detail=self.detail, headers=_CLOSE)
            return message

        await self.app(scope, counted_receive, send)
