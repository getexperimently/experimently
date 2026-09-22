"""The trailing-slash redirect must not move the client to another origin (#86).

Ten collection routes are declared with a trailing slash and clients routinely
omit it, so Starlette answers 307 -- with an **absolute** URL built from the
request scope, i.e. from the `Host` header and whatever scheme the app saw:

    GET /api/v1/experiments   (Host: api.example.com)
      -> 307  Location: http://api.example.com/api/v1/experiments/

A browser following a redirect to a different origin drops `Authorization`;
the API answers 401 and the dashboard logs itself out. And an `http://`
target carries the bearer token in cleartext.

The narrowness is the risky part of the fix, so it is what most of this file
tests: an SSO login redirect to an identity provider must come through
untouched, or making the dashboard's session survive would break logging in.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

from backend.app.middleware.relative_redirect_middleware import (
    RelativeSlashRedirectMiddleware,
)

#: Somewhere a redirect legitimately points that is NOT this service.
IDP = "https://idp.example.com/authorize?client_id=abc&state=xyz"


@pytest.fixture
def client() -> TestClient:
    """An app with every kind of redirect and the middleware mounted."""
    app = FastAPI()

    @app.get("/collection/")
    async def collection():
        return {"ok": True}

    @app.get("/noslash")
    async def noslash():
        """Declared WITHOUT a slash, so the router strips one instead."""
        return {"ok": True}

    @app.get("/users/{uid}")
    async def user(uid: str):
        """Declared WITHOUT a slash, so a slashed request is redirected down.

        A path parameter is the realistic carrier of percent-encoding.
        """
        return {"uid": uid}

    @app.get("/canonical-one-slash-away")
    async def canonical_one_slash_away():
        """Cross-origin, and its path is the request path plus a slash."""
        return RedirectResponse(
            url="https://www.example.com/canonical-one-slash-away/", status_code=301
        )

    @app.get("/canonical/")
    async def canonical():
        """A cross-origin redirect to the SAME path -- a canonical-host 301."""
        return RedirectResponse(
            url="https://www.example.com/canonical/", status_code=301
        )

    @app.get("/already-relative")
    async def already_relative():
        return RedirectResponse(url="/somewhere/else", status_code=307)

    @app.get("/sso/login")
    async def sso_login():
        # What modules/.../sso.py does: hand the browser to the IdP.
        return RedirectResponse(url=IDP, status_code=307)

    @app.get("/elsewhere")
    async def elsewhere():
        return RedirectResponse(url="https://cdn.example.com/a/b", status_code=308)

    app.add_middleware(RelativeSlashRedirectMiddleware)
    return TestClient(app, follow_redirects=False)


@pytest.mark.regression
def test_the_slash_redirect_is_relative(client):
    resp = client.get("/collection", headers={"Host": "api.example.com"})

    assert resp.status_code == 307, (
        f"expected the trailing-slash redirect, got {resp.status_code} -- "
        "if this is 404 the redirect is gone and the rest proves nothing"
    )
    location = resp.headers["location"]
    assert location == "/collection/", location
    assert "://" not in location, (
        f"Location is absolute ({location!r}), so a proxy that rewrites Host "
        "sends the browser cross-origin and it drops Authorization"
    )


@pytest.mark.regression
def test_a_hostile_host_header_cannot_move_the_client(client):
    """The header is attacker-controlled on any path that reaches the app."""
    resp = client.get("/collection", headers={"Host": "evil.example.net"})

    assert resp.status_code == 307
    assert resp.headers["location"] == "/collection/"
    assert "evil.example.net" not in resp.headers["location"]


@pytest.mark.regression
def test_the_query_string_survives(client):
    resp = client.get("/collection?status=ACTIVE&limit=50")

    assert resp.status_code == 307
    assert resp.headers["location"] == "/collection/?status=ACTIVE&limit=50"


@pytest.mark.regression
def test_an_sso_redirect_is_left_alone(client):
    """The one that would break login if the rewrite were not narrow.

    `/api/v1/auth/sso/oidc/{provider}/login` hands the browser to an identity
    provider on another host. Rewriting that to a path would point it back at
    this API and no one could sign in.
    """
    resp = client.get("/sso/login")

    assert resp.status_code == 307
    assert resp.headers["location"] == IDP


@pytest.mark.regression
def test_any_other_cross_origin_redirect_is_left_alone(client):
    resp = client.get("/elsewhere")

    assert resp.status_code == 308
    assert resp.headers["location"] == "https://cdn.example.com/a/b"


@pytest.mark.regression
def test_the_real_app_still_redirects_relatively():
    """Pins `main.py`, not a constructed app.

    The constructed app above proves the middleware; this proves it is
    mounted, and mounted somewhere it can see the router's redirect.
    """
    from backend.app.main import app

    real = TestClient(app, follow_redirects=False)
    resp = real.get(
        "/api/v1/experiments",
        headers={"Authorization": "Bearer x", "Host": "api.example.com"},
    )

    assert resp.status_code == 307, resp.status_code
    assert resp.headers["location"] == "/api/v1/experiments/", resp.headers.get(
        "location"
    )


@pytest.mark.regression
def test_the_other_direction_is_relative_too(client):
    """The router strips a slash as well as adding one.

    `/noslash/` against a route declared `/noslash` redirects down, and only
    the second branch of `_is_slash_redirect` covers it -- inverting that
    branch used to leave the whole suite green.
    """
    resp = client.get("/noslash/", headers={"Host": "api.example.com"})

    assert resp.status_code == 307, resp.status_code
    assert resp.headers["location"] == "/noslash"


@pytest.mark.regression
@pytest.mark.parametrize(
    "encoded",
    [
        "a%40b.com",  # @ -- in RedirectResponse's `safe` set, so it comes back literal
        "a%2Bb",  # +
        "a%2Cb",  # ,
        "a%20b",  # space -- NOT in the safe set, so it stays encoded
    ],
)
def test_a_percent_encoded_path_segment_is_still_rewritten(client, encoded):
    """The case a path-shape comparison could not get right.

    `RedirectResponse` quotes with `safe=":/%#?=@[]!$&'()*+,;"` over the
    already-unquoted `scope["path"]`, so `%40` in the request is a literal `@`
    in the header while `raw_path` still holds `%40`. Comparing those two
    strings failed, and the absolute Host-derived Location shipped:

        GET /users/a%40b.com/  ->  http://api.example.com/users/a@b.com

    The first version of this test asserted only `"://" not in location` and
    accepted two spellings, and it used `%20` -- the one class that happens to
    round-trip. It could not see the bug it was written for.
    """
    resp = client.get(f"/users/{encoded}/", headers={"Host": "api.example.com"})

    assert resp.status_code == 307, resp.status_code
    location = resp.headers["location"]
    assert "://" not in location, f"absolute Location leaked through: {location!r}"
    assert location.startswith("/users/"), location


@pytest.mark.regression
def test_a_cross_origin_redirect_one_slash_away_is_left_alone(client):
    """The redirect loop, one slash further out than the one first fixed.

    Excluding only the identical-path case left this: a handler at `/a`
    returning `https://www.example.com/a/` was rewritten to `/a/`, which the
    router redirects back to `/a`, which redirects again. Comparing
    authorities instead of path shapes removes the whole class.
    """
    resp = client.get("/canonical-one-slash-away", headers={"Host": "api.example.com"})

    assert resp.status_code == 301
    assert (
        resp.headers["location"] == "https://www.example.com/canonical-one-slash-away/"
    )


@pytest.mark.regression
def test_a_cross_origin_redirect_to_the_same_path_is_not_a_slash_redirect(client):
    """Rewriting it produces a redirect to itself, i.e. a loop.

    `_is_slash_redirect("/a/", "/a/")` was True, because
    `"/a/".rstrip("/") + "/"` is `"/a/"`. A canonical-host 301 came back as
    `Location: /canonical/` and the client re-requested the same URL until it
    gave up.
    """
    resp = client.get("/canonical/")

    assert resp.status_code == 301
    assert resp.headers["location"] == "https://www.example.com/canonical/"


@pytest.mark.regression
def test_a_malformed_location_is_passed_through_not_raised():
    """`urlsplit` raises on some authorities; a 500 is worse than the bug.

    `modules/.../sso.py` builds its redirect from an admin-supplied
    `authorization_endpoint`, so a typo'd IPv6 authority there would turn
    "SSO redirects to the IdP" into "the login route 500s".

    Driven at the ASGI layer rather than through `TestClient`: httpx refuses
    to parse such a header itself (`Invalid URL in location header`), so a
    client-level test cannot tell "the middleware raised" from "the client
    rejected it" -- and the thing under test is precisely whether the
    middleware raises.
    """
    import asyncio

    bad = b"http://[::1/idp/authorize"

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [(b"location", bad)],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    # A `Host` header, or `_relative_if_ours` returns before it ever calls
    # `urlsplit` and the guard under test is not reached. The first version of
    # this test had `"headers": []`: removing the try/except left all sixteen
    # tests green, which is how the gap was found.
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/sso/login",
        "raw_path": b"/sso/login",
        "headers": [(b"host", b"api.example.com")],
    }

    asyncio.run(RelativeSlashRedirectMiddleware(app)(scope, receive, send))

    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 302
    assert dict(start["headers"])[b"location"] == bad, (
        "the unparseable Location was altered; it must pass through exactly "
        "as the application wrote it"
    )


@pytest.mark.regression
def test_an_already_relative_location_is_untouched(client):
    resp = client.get("/already-relative")

    assert resp.status_code == 307
    assert resp.headers["location"] == "/somewhere/else"


@pytest.mark.regression
def test_the_middleware_is_mounted():
    """Presence, not position.

    An earlier version asserted `registered[-1] is RelativeSlashRedirect...`,
    which pins a line's ordinal rather than a property of the system: the
    rewrite only edits an outgoing header, so every registration position
    produces an identical response. Moving it outermost kept the behavioural
    test green and failed the ordinal one -- a red test naming a reason that
    was not real, in the way of the next person who legitimately needs an
    innermost layer.
    """
    from backend.app.main import app

    registered = [m.cls for m in app.user_middleware]
    assert RelativeSlashRedirectMiddleware in registered, (
        f"not mounted: {[cls.__name__ for cls in registered]}"
    )
