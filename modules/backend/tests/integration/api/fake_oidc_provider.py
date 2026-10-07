"""A fake OIDC provider, run in its own process by ``test_sso_oidc_flow.py``.

Okta-shaped (``{sso_url}/v1/authorize``, ``/v1/token``, ``/v1/userinfo``) and
strict where a real provider is strict, because those are the properties the
flow test is about:

* ``/v1/authorize`` requires a PKCE S256 challenge and redirects back to the
  ``redirect_uri`` with a code and the ``state`` it was given.
* ``/v1/token`` redeems a code once, only with the verifier whose S256 is that
  code's challenge, only for the same ``redirect_uri``, and only with the
  client's credentials (Basic, as authlib sends them, or in the form, as the
  ``requests`` branch does). Anything else is ``400 invalid_grant``.
* ``/v1/userinfo`` answers only for an access token it issued.
* The token response carries an ID token with ``iss`` (its own base URL, as
  an Okta custom authorization server's is its ``sso_url``), ``aud`` (the
  client), ``exp`` and the ``nonce`` the authorize request carried -- unless
  ``FAKE_OIDC_ID_TOKEN`` says to misbehave: ``wrong-nonce``, ``wrong-iss``,
  ``wrong-aud``, ``expired`` or ``none``; or to vouch for the wrong person:
  ``unverified-email``, ``other-domain`` (the ID token's email is at another
  domain), ``userinfo-email-differs`` (user info names another address than
  the ID token) or ``sub-mismatch`` (user info's ``sub`` differs).
* Modes for the dashboard sign-in's error table (C2b): ``access-denied``
  (``/v1/authorize`` redirects back with ``error=access_denied`` and the
  state, and issues no code); ``no-email`` (the ID token and the user info
  carry NO email, and the ID token drops ``email_verified`` too -- the API
  refuses that as unverified, ``sso_unverified``); ``empty-email``,
  ``non-ascii-email`` and ``malformed-email`` (``email_verified`` true, and the
  email is ``""``, has a non-ASCII character, or has no ``@`` -- the API
  refuses those as invalid, ``sso_email``).
* ``GET /_mode?set=<mode>`` changes the mode of a running provider, so one
  process serves every journey of a browser test.

Usage: ``python fake_oidc_provider.py <client_id> <client_secret> <email>
[--port N]``. Prints ``READY <port>`` once it is listening; without
``--port`` it listens on a free port.

Where it listens and what it calls itself, all optional, so that it can stand
in for a provider another container or a browser reaches over https:

* ``FAKE_OIDC_BIND`` -- the IPv4 address it listens on (default ``127.0.0.1``).
* ``FAKE_OIDC_TLS_CERT`` and ``FAKE_OIDC_TLS_KEY`` -- PEM files; with both set
  it serves https and nothing else, with neither plain http (the default).
  One without the other is refused at start.
* ``FAKE_OIDC_ISSUER`` -- its issuer, the ``sso_url`` an SSO configuration
  names, e.g. ``https://localhost:28443/oauth2/default``. The ID token's
  ``iss`` is this value verbatim and the endpoints are under its path
  (``/oauth2/default/v1/authorize`` and so on); ``/_mode`` stays at the root.
  The default is ``<http or https>://<FAKE_OIDC_BIND>:<port>``, so with
  nothing set it is ``http://127.0.0.1:<port>``. Set it when binding a
  wildcard address such as ``0.0.0.0``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.server
import json
import os
import secrets
import ssl
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse

CLIENT_ID, CLIENT_SECRET, EMAIL = sys.argv[1], sys.argv[2], sys.argv[3]
ID_TOKEN_MODE = os.environ.get("FAKE_OIDC_ID_TOKEN", "good")
#: The user info's `groups`: FAKE_OIDC_GROUPS, comma-separated (default none).
GROUPS = [g for g in os.environ.get("FAKE_OIDC_GROUPS", "").split(",") if g]
BIND = os.environ.get("FAKE_OIDC_BIND", "127.0.0.1")
TLS_CERT = os.environ.get("FAKE_OIDC_TLS_CERT", "")
TLS_KEY = os.environ.get("FAKE_OIDC_TLS_KEY", "")
ISSUER = os.environ.get("FAKE_OIDC_ISSUER", "")  # the default needs the port
#: The issuer's path, under which every endpoint but /_mode is served.
PREFIX = ""

_codes: dict[str, dict[str, str]] = {}
_tokens: set[str] = set()
_lock = threading.Lock()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


_INVALID_EMAILS = {
    "empty-email": "",
    # U+212A KELVIN SIGN, which str.lower() folds to an ASCII "k".
    "non-ascii-email": "\u212aelvin@" + EMAIL.rpartition("@")[2],
    "malformed-email": "no-at-sign",
}


def _id_token(nonce: str) -> str:
    """An HS256 JWT. The API does not check its signature, by design."""
    claims = {
        "iss": ISSUER,
        "sub": f"sub-{EMAIL}",
        "aud": CLIENT_ID,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "nonce": nonce,
        "email": EMAIL,
        "email_verified": True,
    }
    if ID_TOKEN_MODE == "wrong-nonce":
        claims["nonce"] = "not-this-logins-nonce"
    elif ID_TOKEN_MODE == "wrong-iss":
        claims["iss"] = "https://someone-else.example.com"
    elif ID_TOKEN_MODE == "wrong-aud":
        claims["aud"] = "another-client"
    elif ID_TOKEN_MODE == "expired":
        claims["exp"] = int(time.time()) - 3600
    elif ID_TOKEN_MODE == "unverified-email":
        claims["email_verified"] = False
    elif ID_TOKEN_MODE == "other-domain":
        claims["email"] = "someone@elsewhere.example"
    elif ID_TOKEN_MODE == "no-email":
        del claims["email"]
        del claims["email_verified"]
    elif ID_TOKEN_MODE in _INVALID_EMAILS:
        claims["email"] = _INVALID_EMAILS[ID_TOKEN_MODE]
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(claims).encode())
    sig = hmac.new(b"fake-provider-key", f"{head}.{body}".encode(), hashlib.sha256)
    return f"{head}.{body}.{_b64(sig.digest())}"


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the test's output clean
        pass

    def _send(self, status: int, body: dict, headers: dict | None = None) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _refuse(self, error: str, description: str) -> None:
        self._send(400, {"error": error, "error_description": description})

    def _endpoint(self, path: str) -> str:
        """``path`` without the issuer's path; "" when it is not under it."""
        if not PREFIX:
            return path
        return path[len(PREFIX) :] if path.startswith(PREFIX + "/") else ""

    def do_GET(self) -> None:
        global ID_TOKEN_MODE
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/_mode":
            if query.get("set"):
                ID_TOKEN_MODE = query["set"]
            return self._send(200, {"mode": ID_TOKEN_MODE})
        endpoint = self._endpoint(url.path)
        if endpoint == "/v1/authorize":
            if query.get("client_id") != CLIENT_ID:
                return self._refuse("unauthorized_client", "unknown client")
            if query.get("response_type") != "code":
                return self._refuse("unsupported_response_type", "code only")
            if query.get("code_challenge_method") != "S256" or not query.get(
                "code_challenge"
            ):
                return self._refuse("invalid_request", "PKCE S256 is required")
            if ID_TOKEN_MODE == "access-denied":
                target = (
                    query["redirect_uri"]
                    + "?"
                    + urlencode(
                        {"error": "access_denied", "state": query.get("state", "")}
                    )
                )
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            code = secrets.token_urlsafe(16)
            with _lock:
                _codes[code] = {
                    "challenge": query["code_challenge"],
                    "redirect_uri": query["redirect_uri"],
                    "nonce": query.get("nonce", ""),
                }
            target = (
                query["redirect_uri"]
                + "?"
                + urlencode({"code": code, "state": query.get("state", "")})
            )
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if endpoint == "/v1/userinfo":
            auth = self.headers.get("Authorization", "")
            with _lock:
                known = auth.startswith("Bearer ") and auth[7:] in _tokens
            if not known:
                return self._send(401, {"error": "invalid_token"})
            info = {"sub": f"sub-{EMAIL}", "email": EMAIL, "name": "Fake User"}
            if ID_TOKEN_MODE == "no-email":
                del info["email"]
            elif ID_TOKEN_MODE == "userinfo-email-differs":
                info["email"] = "not-" + EMAIL
            elif ID_TOKEN_MODE == "sub-mismatch":
                info["sub"] = "someone-else"
            return self._send(200, {**info, "groups": GROUPS})
        return self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self._endpoint(urlparse(self.path).path) != "/v1/token":
            return self._send(404, {"error": "not_found"})
        length = int(self.headers.get("Content-Length") or 0)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}

        client_id, client_secret = form.get("client_id"), form.get("client_secret")
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            client_id, _, client_secret = (
                base64.b64decode(auth[6:]).decode().partition(":")
            )
        if (client_id, client_secret) != (CLIENT_ID, CLIENT_SECRET):
            return self._send(401, {"error": "invalid_client"})

        with _lock:
            entry = _codes.pop(form.get("code", ""), None)
        if entry is None:
            return self._refuse("invalid_grant", "unknown or already used code")
        if form.get("redirect_uri") != entry["redirect_uri"]:
            return self._refuse("invalid_grant", "redirect_uri mismatch")
        verifier = form.get("code_verifier")
        if not verifier or _s256(verifier) != entry["challenge"]:
            return self._refuse("invalid_grant", "PKCE verification failed")

        token = secrets.token_urlsafe(16)
        with _lock:
            _tokens.add(token)
        body = {"access_token": token, "token_type": "Bearer", "expires_in": 3600}
        if ID_TOKEN_MODE != "none":
            body["id_token"] = _id_token(entry["nonce"])
        return self._send(200, body)


def main() -> None:
    global ISSUER, PREFIX
    if bool(TLS_CERT) != bool(TLS_KEY):
        sys.exit("FAKE_OIDC_TLS_CERT and FAKE_OIDC_TLS_KEY: set both or neither")
    if ISSUER:
        issuer = urlparse(ISSUER)
        if issuer.scheme not in ("http", "https") or not issuer.netloc:
            sys.exit(f"FAKE_OIDC_ISSUER must be an http(s) URL, not {ISSUER!r}")
        PREFIX = issuer.path.rstrip("/")
    port = 0
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    server = http.server.ThreadingHTTPServer((BIND, port), Handler)
    if TLS_CERT:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(TLS_CERT, TLS_KEY)
        # The handshake happens on the connection's first read, in its own
        # thread, so a client that connects and says nothing blocks no other.
        server.socket = context.wrap_socket(
            server.socket, server_side=True, do_handshake_on_connect=False
        )
    if not ISSUER:
        scheme = "https" if TLS_CERT else "http"
        ISSUER = f"{scheme}://{BIND}:{server.server_port}"
    print(f"READY {server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
