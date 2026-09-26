"""A route's unhandled exception becomes a 500 every middleware can see (#72).

Starlette answers an unhandled exception from ``ServerErrorMiddleware``, the
outermost layer of all -- outside CORS, the request id and the security headers.
The 500 it sends therefore carries none of them, and a dashboard on another
origin cannot read it: the browser reports a CORS failure and the dashboard says
"Can't reach the API" about an API that is up.

Registering a handler with ``@app.exception_handler(Exception)`` does not help:
Starlette gives a handler for ``Exception`` or ``500`` to that same outermost
layer (measured on Starlette 1.6.0 and 1.7.0).

So this layer sits innermost of the user middleware. When the route raises
before a response has started, it sends the plain 500 itself -- the same status,
body and content type ``ServerErrorMiddleware`` would send -- so the response
passes back out through CORS, the request id and the security headers. Then it
re-raises. With the response already started, ``ServerErrorMiddleware`` sends
nothing more, but the server still logs the traceback ("Exception in ASGI
application") and a TestClient that raises server exceptions still raises.

Only exceptions from the route and what is inside it are covered: one raised by
another middleware happens outside this layer and still gets the bare 500.
"""

from __future__ import annotations

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class UnhandledErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            if not started:
                response = PlainTextResponse("Internal Server Error", status_code=500)
                await response(scope, receive, send)
            raise
