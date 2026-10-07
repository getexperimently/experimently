"""The fake OIDC provider's address, TLS and issuer settings (#1075).

``modules/backend/tests/integration/api/fake_oidc_provider.py`` is the identity
provider of the SSO flow tests and of the PR QA Gate's dashboard sign-in. Three
optional settings let it stand in for a provider that another container or a
browser reaches over https: ``FAKE_OIDC_BIND``, the pair
``FAKE_OIDC_TLS_CERT``/``FAKE_OIDC_TLS_KEY``, and ``FAKE_OIDC_ISSUER``.

What this pins, each time against a provider started in its own process:

* with none of them set it is the provider those tests start today: plain
  http on 127.0.0.1, its endpoints at the root, ``iss`` ``http://127.0.0.1:<port>``;
* each setting does what it says, and half a TLS pair or an issuer that is not
  an http(s) URL stops it before it prints ``READY``;
* a sign-in round trip over https, with a CA and a certificate generated here
  (none is committed), succeeds for a client that trusts that CA and for no
  other, and a client that connects and sends nothing holds up no one else.
"""

from __future__ import annotations

import base64
import contextlib
import datetime
import hashlib
import http.client
import ipaddress
import json
import os
import secrets
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

PROVIDER_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "integration"
    / "api"
    / "fake_oidc_provider.py"
)
CLIENT_ID = "settings-client"
CLIENT_SECRET = "settings-secret"
EMAIL = "settings-user@fake-oidc.example.com"
REDIRECT_URI = "http://127.0.0.1:1/callback"  # never followed


def _env(settings: dict[str, str]) -> dict[str, str]:
    """This process's environment with only ``settings`` of the FAKE_OIDC_ ones."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_OIDC_")}
    return {**env, **settings}


def _args(port: int | None) -> list[str]:
    args = [sys.executable, str(PROVIDER_SCRIPT), CLIENT_ID, CLIENT_SECRET, EMAIL]
    return args if port is None else [*args, "--port", str(port)]


@contextlib.contextmanager
def _provider(settings: dict[str, str], port: int | None = None) -> Iterator[int]:
    """Run the provider with ``settings``; yields the port it printed."""
    proc = subprocess.Popen(
        _args(port),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(settings),
    )
    first_line: list[str] = []
    reader = threading.Thread(
        target=lambda: first_line.append(proc.stdout.readline()), daemon=True
    )
    reader.start()
    reader.join(timeout=20)
    line = first_line[0] if first_line else ""
    if not line.startswith("READY "):
        proc.kill()
        _, err = proc.communicate(timeout=5)
        pytest.fail(f"the fake OIDC provider did not start: {line!r} {err}")
    try:
        yield int(line.split()[1])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _refused_at_start(settings: dict[str, str]) -> str:
    """Run the provider with ``settings``; it must exit without READY. Its stderr."""
    result = subprocess.run(
        _args(None), capture_output=True, text=True, env=_env(settings), timeout=20
    )
    assert result.returncode != 0, result.stdout
    assert "READY" not in result.stdout
    return result.stderr


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _call(
    base: str,
    method: str,
    path: str,
    *,
    context: ssl.SSLContext | None = None,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: float = 10,
) -> tuple[int, http.client.HTTPMessage, bytes]:
    """One request to ``base`` + ``path``; redirects are returned, not followed."""
    url = urlparse(base)
    if url.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            url.hostname, url.port, timeout=timeout, context=context
        )
    else:
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=timeout)
    try:
        conn.request(method, url.path + path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, response.headers, response.read()
    finally:
        conn.close()


def _sign_in(
    base: str, context: ssl.SSLContext | None = None, timeout: float = 10
) -> tuple[dict, dict]:
    """Authorize, redeem the code with PKCE, read the user info.

    Returns the ID token's claims and the user info. ``base`` is the issuer:
    the endpoints are ``{base}/v1/...``, as the API builds them from sso_url.
    """
    verifier = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    query = urlencode(
        {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "state": "the-state",
            "nonce": "the-nonce",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    status, headers, body = _call(
        base, "GET", f"/v1/authorize?{query}", context=context, timeout=timeout
    )
    assert status == 302, body
    returned = parse_qs(urlparse(headers["Location"]).query)
    assert returned["state"] == ["the-state"]

    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    form = urlencode(
        {
            "grant_type": "authorization_code",
            "code": returned["code"][0],
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }
    )
    status, _, body = _call(
        base,
        "POST",
        "/v1/token",
        context=context,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body=form,
        timeout=timeout,
    )
    assert status == 200, body
    tokens = json.loads(body)
    payload = tokens["id_token"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))

    status, _, body = _call(
        base,
        "GET",
        "/v1/userinfo",
        context=context,
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=timeout,
    )
    assert status == 200, body
    return claims, json.loads(body)


def _reachable(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=3).close()
    except OSError:
        return False
    return True


def _non_loopback_address() -> str:
    """An IPv4 address of this host other than loopback, or skip.

    A UDP ``connect`` sends nothing; it only picks the address a packet to
    TEST-NET-1 would leave from.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            address = probe.getsockname()[0]
    except OSError as exc:
        pytest.skip(f"this host has no route off loopback: {exc}")
    if ipaddress.ip_address(address).is_loopback or address == "0.0.0.0":
        pytest.skip(f"this host has no address off loopback ({address})")
    return address


def _certificates(directory: Path) -> tuple[Path, Path, Path]:
    """A CA, and a server certificate it signed for localhost and 127.0.0.1.

    Returns the paths of the CA certificate, the server certificate and the
    server key, all under ``directory``. The CA's key is never written.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    start, end = now - datetime.timedelta(minutes=5), now + datetime.timedelta(hours=1)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake OIDC test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(end)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(end)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_path = directory / "ca.pem"
    cert_path = directory / "server.pem"
    key_path = directory / "server-key.pem"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca_path, cert_path, key_path


def _trusting(ca: Path) -> ssl.SSLContext:
    """A client context whose only trust anchor is ``ca``."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(ca))
    return context


@pytest.fixture
def certificates(tmp_path: Path) -> tuple[Path, Path, Path]:
    return _certificates(tmp_path)


class TestDefaults:
    def test_with_nothing_set_it_is_todays_provider(self):
        """Plain http on 127.0.0.1, endpoints at the root, iss its base URL."""
        with _provider({}) as port:
            base = f"http://127.0.0.1:{port}"
            claims, info = _sign_in(base)
            assert claims["iss"] == base
            assert claims["nonce"] == "the-nonce"
            assert info["email"] == EMAIL
            status, _, body = _call(base, "GET", "/_mode")
            assert (status, json.loads(body)) == (200, {"mode": "good"})

    def test_with_nothing_set_it_listens_on_loopback_only(self):
        address = _non_loopback_address()
        with _provider({}) as port:
            assert _reachable("127.0.0.1", port)
            assert not _reachable(address, port)


class TestBind:
    def test_it_listens_on_the_address_named(self):
        """And names itself by it, while FAKE_OIDC_ISSUER is unset."""
        address = _non_loopback_address()
        with _provider({"FAKE_OIDC_BIND": address}) as port:
            assert _reachable(address, port)
            assert not _reachable("127.0.0.1", port)
            claims, _ = _sign_in(f"http://{address}:{port}")
            assert claims["iss"] == f"http://{address}:{port}"

    def test_an_address_this_host_lacks_stops_it(self):
        """192.0.2.1 is TEST-NET-1: no host has it, so bind() must fail."""
        err = _refused_at_start({"FAKE_OIDC_BIND": "192.0.2.1"})
        assert "assign requested address" in err


class TestIssuer:
    def test_its_path_is_where_the_endpoints_are(self):
        port = _free_port()
        root = f"http://127.0.0.1:{port}"
        issuer = f"{root}/oauth2/default"
        with _provider({"FAKE_OIDC_ISSUER": issuer}, port=port):
            claims, _ = _sign_in(issuer)
            assert claims["iss"] == issuer
            # Not at the root, nor under a path that only starts the same way.
            for base in (root, f"{root}/oauth2", f"{root}/oauth2/defaultx"):
                assert _call(base, "GET", "/v1/authorize")[0] == 404, base
                assert _call(base, "POST", "/v1/token", body="")[0] == 404, base
                assert _call(base, "GET", "/v1/userinfo")[0] == 404, base
            # The test control stays at the root.
            assert _call(root, "GET", "/_mode?set=wrong-nonce")[0] == 200
            claims, _ = _sign_in(issuer)
            assert claims["nonce"] == "not-this-logins-nonce"

    @pytest.mark.parametrize(
        "issuer",
        ["localhost:28443/oauth2/default", "ftp://localhost/oauth2", "https:///x"],
    )
    def test_one_that_is_not_an_http_url_stops_it(self, issuer):
        err = _refused_at_start({"FAKE_OIDC_ISSUER": issuer})
        assert "FAKE_OIDC_ISSUER must be an http(s) URL" in err


class TestTLS:
    def test_round_trip_with_a_generated_ca(self, certificates):
        """The shape of an Okta custom authorization server's sso_url."""
        ca, cert, key = certificates
        port = _free_port()
        issuer = f"https://localhost:{port}/oauth2/default"
        settings = {
            "FAKE_OIDC_TLS_CERT": str(cert),
            "FAKE_OIDC_TLS_KEY": str(key),
            "FAKE_OIDC_ISSUER": issuer,
        }
        with _provider(settings, port=port):
            claims, info = _sign_in(issuer, context=_trusting(ca))
            assert claims["iss"] == issuer
            assert claims["nonce"] == "the-nonce"
            assert info["email"] == EMAIL

            # A client without that CA is refused at the handshake...
            with pytest.raises(ssl.SSLCertVerificationError):
                _call(issuer, "GET", "/v1/userinfo", context=_trusting(_other_ca(ca)))
            # ...and nothing answers plain http on the same port.
            with pytest.raises((http.client.HTTPException, OSError)):
                _call(f"http://localhost:{port}/oauth2/default", "GET", "/v1/userinfo")

            # It still serves after both.
            _sign_in(issuer, context=_trusting(ca))

    def test_without_an_issuer_it_names_itself_https(self, certificates):
        ca, cert, key = certificates
        settings = {"FAKE_OIDC_TLS_CERT": str(cert), "FAKE_OIDC_TLS_KEY": str(key)}
        with _provider(settings) as port:
            base = f"https://127.0.0.1:{port}"
            claims, _ = _sign_in(base, context=_trusting(ca))
            assert claims["iss"] == base

    def test_a_silent_connection_holds_up_no_one(self, certificates):
        """The handshake is the connection's own thread's work, not the server's."""
        ca, cert, key = certificates
        settings = {"FAKE_OIDC_TLS_CERT": str(cert), "FAKE_OIDC_TLS_KEY": str(key)}
        with _provider(settings) as port:
            with socket.create_connection(("127.0.0.1", port), timeout=10):
                claims, _ = _sign_in(
                    f"https://127.0.0.1:{port}", context=_trusting(ca), timeout=5
                )
            assert claims["iss"] == f"https://127.0.0.1:{port}"

    @pytest.mark.parametrize("half", ["FAKE_OIDC_TLS_CERT", "FAKE_OIDC_TLS_KEY"])
    def test_half_a_pair_stops_it(self, half, certificates):
        _, cert, key = certificates
        path = cert if half == "FAKE_OIDC_TLS_CERT" else key
        err = _refused_at_start({half: str(path)})
        assert "set both or neither" in err


def _other_ca(ca: Path) -> Path:
    """Another CA's certificate, beside ``ca``: one that signed nothing here."""
    directory = ca.parent / "other"
    directory.mkdir(exist_ok=True)
    return _certificates(directory)[0]
