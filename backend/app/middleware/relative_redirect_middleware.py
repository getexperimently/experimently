"""A redirect that points back at us keeps the client's own origin (#86).

Ten collection routes are declared with a trailing slash
(`/api/v1/experiments/`, `/api/v1/feature-flags/`, ...) and clients routinely
omit it, so Starlette's `redirect_slashes` answers 307 -- building the target
as an **absolute** URL from the request scope:

    redirect_url = URL(scope=redirect_scope)
    response = RedirectResponse(url=str(redirect_url))

Measured against the real app:

    GET /api/v1/experiments   (Host: api.example.com)
      -> 307  Location: http://api.example.com/api/v1/experiments/

Two things go wrong with that header:

* **The authority comes from `Host`.** Behind any proxy that rewrites it, the
  browser follows the redirect to a different origin. A cross-origin redirect
  is where the browser drops `Authorization`, the API answers 401, and the
  dashboard reads that as an expired session and logs itself out.
* **The scheme is whatever the app saw.** `docker-entrypoint.sh` passes
  `--proxy-headers`, so behind the ALB uvicorn reads `X-Forwarded-Proto` and
  this comes out `https`. Anywhere that header is absent -- a direct hit on
  the task port, a proxy that does not set it, a local `docker run` -- it is
  `http`, and a browser following it sends the bearer token in cleartext.

A **relative** `Location` has neither failure: the browser resolves it against
the origin it is already talking to, so the scheme and authority are by
construction the ones the client chose.

The rule: **rewrite a Location whose authority is the one the request came in
on; leave every other Location exactly as the application wrote it.** An SSO
login redirect hands the browser to an identity provider on another host and
must survive untouched.

That rule replaced a path-shape heuristic -- "the target differs from the
request path by exactly a trailing slash" -- which was wrong twice and in
opposite directions:

* it compared the wire-form request path against a `Location` that
  `RedirectResponse` quotes with `safe=":/%#?=@[]!$&'()*+,;"`, so `%40` in the
  request was `@` in the header and the comparison failed. Measured:
  `GET /users/a%40b.com/` came back `Location:
  http://api.example.com/users/a@b.com` -- absolute, Host-derived, failing
  open on exactly the routes most likely to carry an encoded segment;
* and a genuinely cross-origin redirect one slash away from the request path
  matched it. Measured: a handler at `/a` returning
  `https://www.example.com/a/` came back as `Location: /a/`, which the router
  redirects back to `/a`, which redirects again -- an infinite loop, and a
  canonical-host redirect silently defeated.

Comparing authorities has neither failure mode, needs no encoding rules, and
is a property a reader can check by inspection.

**This does not make `Host` trustworthy** -- it makes one consumer of it stop
mattering. `modules/.../sso.py` still builds the OIDC `redirect_uri` from
`request.base_url`, which is the same untrusted header in a place that hands
an attacker-influenced callback to an identity provider. That is #220, and it
wants `TrustedHostMiddleware` or a configured public origin, not another
patch here.

Pure ASGI, not `BaseHTTPMiddleware`: this sits on every request in the app to
edit one header on a rare redirect, and the base class pays a task group, two
anyio memory object streams and a request copy for each one. Measured, best of
5 x 2000 calls: 5.0 us/req with nothing mounted, 5.5 us/req with this, 136.0
us/req with an equivalent `BaseHTTPMiddleware`.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Every status that carries a `Location`, so a change of Starlette's default
#: is covered rather than silently unhandled. Safe to cover all of them
#: because the rule is about the authority, not the status: a 301 that points
#: at this origin is as much ours to make relative as a 307.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _request_authority(scope: Scope) -> str:
    """The `Host` the client addressed, lower-cased; empty if it sent none."""
    for name, value in scope.get("headers") or ():
        if name == b"host":
            return value.decode("latin-1").strip().lower()
    return ""


def _relative_if_ours(location: str, authority: str) -> str | None:
    """The path-only form of *location*, or None to leave it alone."""
    if not authority:
        return None  # nothing to compare against; do not guess
    try:
        _scheme, netloc, path, query, fragment = urlsplit(location)
    except ValueError:
        # An unparseable Location -- `http://[::1/...`, a typo'd IPv6
        # authority in an SSO config -- must not turn a working redirect into
        # a 500. Leave it exactly as the application wrote it.
        return None
    if not netloc:
        return None  # already relative
    if netloc.lower() != authority:
        return None  # somewhere else entirely; not ours to touch
    return urlunsplit(("", "", path, query, fragment))


class RelativeSlashRedirectMiddleware:
    """Make a self-referential `Location` relative, keeping path and query."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if (
                message["type"] == "http.response.start"
                and message["status"] in _REDIRECT_STATUSES
            ):
                # Read the Host only here. Every request pays for what runs
                # outside this branch, and only a redirect needs it.
                headers = MutableHeaders(scope=message)
                location = headers.get("location")
                if location:
                    replacement = _relative_if_ours(location, _request_authority(scope))
                    if replacement is not None:
                        headers["location"] = replacement
            await send(message)

        await self.app(scope, receive, send_wrapper)
