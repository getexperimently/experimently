"""A browser has to be able to see a rate-limited login (#85).

Two separate faults made the dashboard report "Can't reach the API" when the
real answer was "too many attempts, try again in a minute":

* the limiter counted the browser's CORS **preflight**.  `/api/v1/auth/login`
  allows ten requests a minute per IP and a browser sends one `OPTIONS` before
  every cross-origin `POST`, so ten preflights on their own were enough to
  429 the first login attempt the user actually made;
* the 429 came from a middleware **outside** `CORSMiddleware`, so it carried
  no `Access-Control-Allow-Origin`.  A browser refuses to hand the page a
  cross-origin response without it, and reports a network failure instead --
  which is indistinguishable, in the dashboard, from the API being down.

The second one is about *ordering*, and ordering in Starlette runs the
opposite way to how it reads: `add_middleware` inserts at the front of
`app.user_middleware`, and the stack is built by wrapping in reverse of that
list, so the **last** registration is the outermost layer.  The comment in
`main.py` asserted the opposite for as long as this bug existed.
"""

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from backend.app.middleware.rate_limiter import (
    RATE_LIMIT_CONFIG,
    RateLimitMiddleware,
    SlidingWindowRateLimiter,
)
from backend.app.middleware.security_middleware import SecurityHeadersMiddleware

LOGIN = "/api/v1/auth/login"
ORIGIN = "http://localhost:3100"

#: What a browser sends before a cross-origin POST.
PREFLIGHT_HEADERS = {
    "Origin": ORIGIN,
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
}


#: Mirrors `main.py`'s own kwargs. `expose_headers` in particular: it is what
#: a browser will let the page read, so a test that drops it cannot notice
#: `Retry-After` disappearing from the real app.
CORS_KWARGS = {
    "allow_origins": [ORIGIN],
    "allow_credentials": True,
    "allow_methods": ["GET", "POST", "PUT", "DELETE", "PATCH"],
    "allow_headers": ["Authorization", "Content-Type", "X-API-Key"],
    "expose_headers": [
        "X-Request-ID",
        "Retry-After",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Window",
    ],
}


def _routes() -> FastAPI:
    """A bare app with the login route, and nothing mounted on it."""
    app = FastAPI()

    @app.post(LOGIN)
    async def login():
        return {"ok": True}

    @app.options(LOGIN)
    async def login_options():
        return {"ok": True}

    return app


def _limiter(app):
    """The limiter, wrapping *app*, counting in memory.

    Constructed rather than registered, for two reasons. `add_middleware`
    records a class and its kwargs and builds the instance lazily at the first
    request, so there is nothing to reach into beforehand -- an earlier version
    of this file walked `app.middleware_stack` after calling
    `build_middleware_stack()`, patched whatever it found, and then Starlette
    built a fresh stack at request time and discarded it.

    That version passed here and failed in CI, which is the tell: with no
    Redis running, `RedisRateLimiter` falls back to a per-instance in-memory
    counter, so the patch being a no-op was invisible. CI has redis, so all
    four apps in this file shared one key -- `ratelimit:testclient:<path>` --
    with each other and with the previous run's leftovers, and the budget was
    already spent before the first assertion.

    Constructing it also makes the nesting explicit instead of relying on
    registration order, which is the thing
    `test_cors_is_the_outermost_middleware_of_the_real_app` pins on the real
    application anyway.
    """
    middleware = RateLimitMiddleware(app, enabled=True)
    middleware._limiter = SlidingWindowRateLimiter()
    return middleware


def _app(cors_last: bool = True):
    """RateLimit + CORS only -- **two** of the five layers `main.py` mounts.

    Enough to exercise the ordering these tests are about, and not a stand-in
    for the real stack: `test_cors_is_the_outermost_middleware_of_the_real_app`
    is what holds `main.py` itself.

    ``cors_last=True`` is the shipped nesting, CORS outermost.
    """
    routes = _routes()
    if cors_last:
        return CORSMiddleware(_limiter(routes), **CORS_KWARGS)
    return _limiter(CORSMiddleware(routes, **CORS_KWARGS))


def _limiter_only_app():
    """The limiter with nothing in front of it.

    `CORSMiddleware` answers any request carrying
    `Access-Control-Request-Method` itself and passes it no further, so in the
    shipped stack a preflight never reaches the limiter. That makes the
    end-to-end test pass whether or not the limiter skips preflights -- which
    is how this was first written, and it is a gate that passes for the wrong
    reason. The limiter's own rule is pinned here, where nothing shields it.
    """
    return _limiter(_routes())


@pytest.fixture
def login_limit() -> int:
    limit, _window = RATE_LIMIT_CONFIG[LOGIN]
    return limit


def test_the_login_limit_is_small_enough_for_this_to_matter(login_limit):
    """Guard against the tests below passing because the limit is enormous.

    They exhaust it by hand; if the configured limit ever became 10_000 they
    would stop exercising anything and still pass.
    """
    assert 1 < login_limit <= 100, (
        f"{LOGIN} is limited to {login_limit}/window; these tests assume a "
        "limit small enough to exhaust in a loop"
    )


@pytest.mark.regression
def test_the_limiter_does_not_count_a_preflight(login_limit):
    """#85: a preflight carries no credentials and is not an attempt."""
    client = TestClient(_limiter_only_app())
    codes = [
        client.options(LOGIN, headers=PREFLIGHT_HEADERS).status_code
        for _ in range(login_limit + 5)
    ]
    assert all(code < 400 for code in codes), f"a preflight was refused: {codes}"

    first_real_attempt = client.post(LOGIN)
    assert first_real_attempt.status_code == 200, (
        f"{login_limit + 5} preflights left the first real login at "
        f"{first_real_attempt.status_code}"
    )


@pytest.mark.regression
def test_a_bare_options_is_still_counted(login_limit):
    """The exemption is for preflights, not for a verb.

    Starlette's CORSMiddleware only intercepts an `OPTIONS` carrying both an
    `Origin` and `Access-Control-Request-Method`; a bare one passes through it
    to the router. Keying the skip on the method alone therefore made every
    such request unlimited and unrecorded -- an exemption a client obtains by
    choosing a verb.
    """
    client = TestClient(_limiter_only_app())
    codes = [client.options(LOGIN).status_code for _ in range(login_limit + 2)]
    assert 429 in codes, (
        f"{login_limit + 2} bare OPTIONS requests were all allowed against a "
        f"limit of {login_limit}: {codes}"
    )


@pytest.mark.regression
def test_preflights_do_not_spend_the_login_budget(login_limit):
    """The user-visible property, through the stack `main.py` builds.

    Here the ordering is what does the work -- CORS answers the preflight --
    so this stays green if the limiter's `OPTIONS` rule is removed.  It is the
    end of the chain, not the pin on any one link.
    """
    client = TestClient(_app())
    codes = [
        client.options(LOGIN, headers=PREFLIGHT_HEADERS).status_code
        for _ in range(login_limit + 5)
    ]
    assert all(code < 400 for code in codes), f"a preflight was refused: {codes}"

    first_real_attempt = client.post(LOGIN, headers={"Origin": ORIGIN})
    assert first_real_attempt.status_code == 200, (
        f"{login_limit + 5} preflights left the first real login at "
        f"{first_real_attempt.status_code}"
    )


@pytest.mark.regression
def test_a_rate_limited_login_is_readable_by_the_browser(login_limit):
    """#85: the 429 must carry the CORS header, or the page sees a network error."""
    client = TestClient(_app())
    for _ in range(login_limit):
        client.post(LOGIN, headers={"Origin": ORIGIN})

    refused = client.post(LOGIN, headers={"Origin": ORIGIN})
    assert refused.status_code == 429, "the limit was not reached"
    assert refused.headers.get("access-control-allow-origin") == ORIGIN, (
        "the 429 has no Access-Control-Allow-Origin, so a browser reports it "
        "as a network failure rather than handing the page the status"
    )


def test_the_old_order_is_what_produced_the_bug(login_limit):
    """The counter-example, so the assertion above cannot pass for free.

    With CORS registered first -- the order `main.py` used -- the 429 is
    returned by a layer outside it and has no CORS header at all.
    """
    client = TestClient(_app(cors_last=False))
    for _ in range(login_limit):
        client.post(LOGIN, headers={"Origin": ORIGIN})

    refused = client.post(LOGIN, headers={"Origin": ORIGIN})
    assert refused.status_code == 429
    assert "access-control-allow-origin" not in refused.headers


@pytest.mark.regression
def test_cors_is_the_outermost_middleware_of_the_real_app():
    """Pin the ordering in `main.py` itself.

    The behavioural tests above build their own app, so nothing else would
    notice a future `add_middleware` call landing after the CORS one and
    pushing it back inside.  `user_middleware` is outermost-first.
    """
    from backend.app.main import app

    registered = [m.cls for m in app.user_middleware]
    names = [cls.__name__ for cls in registered]

    assert registered.count(CORSMiddleware) == 1, (
        f"expected exactly one CORSMiddleware, the stack is {names}"
    )
    assert RateLimitMiddleware in registered, (
        f"the rate limiter is not mounted, so this proves nothing: {names}"
    )
    # Index 0, not `index(CORS) < index(RateLimit)`. The weaker form was
    # written to survive a fixture that mounted middleware on the shared app;
    # that fixture is fixed, and the weaker form does not pin the property.
    # Measured: registering one more middleware after CORS gives
    # ['New', 'CORS', 'RateLimit'] -- CORS is no longer outermost, but the
    # comparison still holds. A layer added outside CORS that short-circuits
    # (an auth gate, an IP allow-list, a body-size limit) returns a response
    # with no Access-Control-Allow-Origin, which is #85 verbatim.
    assert registered[0] is CORSMiddleware, (
        "CORSMiddleware must be registered LAST so it is the outermost layer "
        "and every response from the ones below it carries the CORS headers; "
        f"the stack, outermost first, is {names}"
    )


@pytest.mark.regression
def test_the_429_keeps_its_security_headers():
    """The limiter short-circuits, so anything nested inside it never runs.

    That is the same defect the CORS reorder fixes, for the other header set:
    `SecurityHeadersMiddleware` used to sit inside the limiter, so the one
    response on this path a hostile client is most likely to see went out with
    no `X-Content-Type-Options`, no `X-Frame-Options` and no CSP.
    """
    from backend.app.main import app

    registered = [m.cls for m in app.user_middleware]
    names = [cls.__name__ for cls in registered]
    assert SecurityHeadersMiddleware in registered, f"not mounted: {names}"
    assert registered.index(SecurityHeadersMiddleware) < registered.index(
        RateLimitMiddleware
    ), (
        "SecurityHeadersMiddleware must be registered after the rate limiter, "
        "so it is outside it and the 429 passes back out through it; the "
        f"stack, outermost first, is {names}"
    )


@pytest.mark.regression
def test_the_browser_may_read_retry_after():
    """Reading the status is not the same as being told how long to wait.

    `Retry-After` is not CORS-safelisted, so without it in `expose_headers`
    the page gets `undefined` and can only say "try again shortly" -- one
    field short of what #85 asks for.
    """
    from fastapi.middleware.cors import CORSMiddleware as _CORS

    from backend.app.main import app

    cors = next(m for m in app.user_middleware if m.cls is _CORS)
    exposed = {h.lower() for h in cors.kwargs.get("expose_headers", [])}
    for header in ("retry-after", "x-ratelimit-limit", "x-ratelimit-window"):
        assert header in exposed, (
            f"{header} is not exposed, so the dashboard cannot read it off a "
            f"429; exposed: {sorted(exposed)}"
        )
