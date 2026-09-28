"""The warehouse HTTP client reaches only published endpoints on public addresses."""

from __future__ import annotations

import socket
import time

import httpcore
import httpx
import pytest

from modules.backend.app.warehouse.deadlines import (
    CONNECT_SECONDS,
    READ_SECONDS,
    Deadline,
)
from modules.backend.app.warehouse.egress import (
    GuardedBackend,
    GuardedTransport,
    OutboundClient,
    _embedded_v4,
    is_published_endpoint,
    refused_address,
    snowflake_host,
)
from modules.backend.app.warehouse.errors import WarehouseError, WarehouseErrorCode
from modules.backend.tests.unit.warehouse.conftest import (
    FakeBackend,
    http_answer,
    public_resolver,
)

REFUSED = WarehouseErrorCode.DESTINATION_NOT_ALLOWED

#: Addresses a published name must never be connected to when it resolves to them.
PRIVATE_ADDRESSES = [
    "127.0.0.1",
    "127.1.2.3",
    "::1",
    "10.1.2.3",
    "172.16.0.1",
    "192.168.1.1",
    "169.254.169.254",
    "169.254.170.2",
    "100.64.0.1",
    "0.0.0.0",
    "224.0.0.1",
    "240.0.0.1",
    "255.255.255.255",
    "fd00::1",
    "fc00::1",
    "fe80::1",
    "::",
    "ff02::1",
    "::ffff:127.0.0.1",
    "::ffff:10.0.0.1",
    "::ffff:169.254.169.254",
    "64:ff9b::a9fe:a9fe",
    "2002:a9fe:a9fe::1",
    "::127.0.0.1",
]


class RecordingBackend(httpcore.NetworkBackend):
    """Connects for real only to the probe on loopback; records every attempt."""

    def __init__(self, probe_port: int) -> None:
        self._probe_port = probe_port
        self._real = httpcore.SyncBackend()
        self.connects = []

    def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        self.connects.append((host, port))
        if host in ("127.0.0.1", "::ffff:127.0.0.1", "::1", "localhost"):
            return self._real.connect_tcp(host, self._probe_port, timeout=1.0)
        raise httpcore.ConnectError("not attempted in tests")

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("no")

    def sleep(self, seconds):
        pass


def _wait_for_probe(probe) -> None:
    """Let the probe's accept thread count a connection, if one was made.

    The assertions are on zero accepted connections, so a connection that
    was made must have had the chance to be counted before they run.
    """
    for _ in range(10):
        if probe.accepted:
            return
        time.sleep(0.02)


@pytest.mark.parametrize("address", PRIVATE_ADDRESSES)
def test_private_addresses_refused(address, probe):
    """A published name resolving to a private address is never connected to.

    The resolver answers with the address (and, for loopback, the probe's
    port); the inner backend connects for real to loopback and records every
    other attempt.  Nothing may be attempted, and the probe accepts nothing.
    """
    inner = RecordingBackend(probe.port)

    def resolve(host, port):
        return [(address, probe.port)]

    deadline = Deadline(30)
    with OutboundClient(deadline, resolver=resolve, network_backend=inner) as client:
        with pytest.raises(WarehouseError) as err:
            client.request(
                "GET", "https://myorg-acct.snowflakecomputing.com/api/v2/statements"
            )
    _wait_for_probe(probe)
    assert probe.accepted == 0
    assert inner.connects == []
    assert err.value.code is REFUSED


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::ffff:127.0.0.1"])
def test_private_literal_hosts_refused_by_the_network_backend(host, probe):
    """The backend alone refuses loopback, by literal and by name, before connecting."""
    backend = GuardedBackend(Deadline(30))
    try:
        backend.connect_tcp(host, probe.port).close()
        outcome = "connected"
    except WarehouseError as err:
        outcome = err.code
    _wait_for_probe(probe)
    assert probe.accepted == 0
    assert outcome is REFUSED


def test_a_name_with_any_private_address_is_refused():
    """One private address among public ones is enough to refuse the name."""
    inner = FakeBackend([http_answer(200)])

    def resolve(host, port):
        return [("93.184.216.34", port), ("10.0.0.7", port)]

    with OutboundClient(
        Deadline(30), resolver=resolve, network_backend=inner
    ) as client:
        with pytest.raises(WarehouseError) as err:
            client.request(
                "GET", "https://bigquery.googleapis.com/bigquery/v2/projects"
            )
    assert err.value.code is REFUSED
    assert inner.connects == []


def test_a_public_address_is_connected_to_by_address_with_the_original_name_for_tls():
    """Positive control: a public answer is used, by the checked address."""
    inner = FakeBackend([http_answer(200, b"{}")])
    with OutboundClient(
        Deadline(30), resolver=public_resolver("93.184.216.34"), network_backend=inner
    ) as client:
        response = client.request(
            "GET", "https://bigquery.googleapis.com/bigquery/v2/projects"
        )
    assert response.status_code == 200
    assert inner.connects == [("93.184.216.34", 443)]
    assert inner.tls_hostnames == ["bigquery.googleapis.com"]


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:1/x?",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::ffff:127.0.0.1]/",
        "https://10.0.0.1/",
        "http://bigquery.googleapis.com/bigquery/v2/projects",
        "https://bigquery.googleapis.com:8443/",
        "https://user:pw@bigquery.googleapis.com/",
        "https://bigquery.googleapis.com.example.com/",
        "https://storage.googleapis.com/",
        "https://myorg-acct.privatelink.snowflakecomputing.com/",
        "https://xy12345.us-east-1.snowflakecomputing.com/",
        "https://myorg-acct.snowflakecomputing.com.example.com/",
        "https://example.com/",
    ],
)
def test_hosts_outside_the_published_endpoints_refused(url):
    """Refused before any name is resolved or any connection made."""
    resolved = []

    def resolve(host, port):
        resolved.append(host)
        return [("93.184.216.34", port)]

    inner = FakeBackend([http_answer(200)])
    with OutboundClient(
        Deadline(30), resolver=resolve, network_backend=inner
    ) as client:
        with pytest.raises(WarehouseError) as err:
            client.request("GET", url)
    assert err.value.code is REFUSED
    assert resolved == []
    assert inner.connects == []


@pytest.mark.parametrize(
    "account",
    [
        "myorg-acct.privatelink",
        "xy12345.us-east-1",
        "xy12345",
        "myorg-acct.snowflakecomputing.com",
        "myorg-acct:443",
        "myorg-acct/x",
        "myorg-acct@example.com",
        "myorg-acct\n",
        "myorg-acct ",
        "127.0.0.1",
        "-acct",
        "1org-acct",
        "myorg-",
        "",
    ],
)
def test_snowflake_account_pattern_refuses_hosts(account):
    with pytest.raises(WarehouseError) as err:
        snowflake_host(account)
    assert err.value.code is REFUSED


def test_snowflake_account_builds_its_published_host():
    host = snowflake_host("MyOrg-My_Account1")
    assert host == "myorg-my-account1.snowflakecomputing.com"
    assert is_published_endpoint(host)
    assert is_published_endpoint("bigquery.googleapis.com")
    assert is_published_endpoint("oauth2.googleapis.com")
    assert not is_published_endpoint("myorg-acct.privatelink.snowflakecomputing.com")


@pytest.mark.parametrize("address", PRIVATE_ADDRESSES + ["not-an-address", "1.2.3"])
def test_refused_address_classifies_private(address):
    assert refused_address(address)


@pytest.mark.parametrize(
    "address,embedded",
    [
        ("::ffff:10.0.0.1", "10.0.0.1"),
        ("64:ff9b::a9fe:a9fe", "169.254.169.254"),
        ("64:ff9b:1::a00:1", "10.0.0.1"),
        ("2002:a9fe:a9fe::1", "169.254.169.254"),
        ("2001:0:4136:e378:8000:63bf:f5ff:fffe", "10.0.0.1"),
        ("::127.0.0.1", "127.0.0.1"),
    ],
)
def test_embedded_ipv4_is_checked_on_its_own(address, embedded):
    """The embedded IPv4 address is extracted and classified independently of
    how the standard library classifies the IPv6 form (on 3.11 these forms are
    also reserved or private; that is not relied on)."""
    import ipaddress

    assert str(_embedded_v4(ipaddress.IPv6Address(address))) == embedded
    assert refused_address(embedded)


@pytest.mark.parametrize(
    "address", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"]
)
def test_refused_address_passes_public(address):
    assert not refused_address(address)


def test_redirect_not_followed():
    """A 3xx is refused and never followed, even if the client were told to follow."""
    inner = FakeBackend(
        [
            http_answer(
                302, headers=[("Location", "https://oauth2.googleapis.com/token")]
            ),
            http_answer(200, b"{}"),
        ]
    )
    with OutboundClient(
        Deadline(30), resolver=public_resolver(), network_backend=inner
    ) as client:
        client.http.follow_redirects = True
        with pytest.raises(WarehouseError) as err:
            client.request(
                "GET", "https://bigquery.googleapis.com/bigquery/v2/projects"
            )
    assert err.value.code is WarehouseErrorCode.REDIRECT_REFUSED
    assert len(inner.connects) == 1
    request_lines = [w for w in inner.requests_written if w.startswith(b"GET ")]
    assert len(request_lines) == 1


def test_client_ignores_environment_proxies(monkeypatch):
    """No proxy variable routes a request around the address check."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    inner = FakeBackend([http_answer(200, b"{}")])
    with OutboundClient(
        Deadline(30), resolver=public_resolver(), network_backend=inner
    ) as client:
        assert client.http.trust_env is False
        client.request("GET", "https://bigquery.googleapis.com/bigquery/v2/projects")
    assert inner.connects == [("93.184.216.34", 443)]


def test_transport_uses_the_guarded_backend():
    """httpx builds its own pool; the transport must have replaced it with ours."""
    transport = GuardedTransport(Deadline(30))
    pool = transport._pool
    assert isinstance(pool, httpcore.ConnectionPool)
    assert pool._network_backend is transport.network_backend
    assert isinstance(transport.network_backend, GuardedBackend)


def test_every_outbound_client_has_fixed_limits():
    """Connect 5 s, each read and write 30 s, capped by what the deadline has left."""
    with OutboundClient(Deadline(30)) as client:
        timeout = client.http.timeout
        assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (
            CONNECT_SECONDS,
            READ_SECONDS,
            READ_SECONDS,
            CONNECT_SECONDS,
        )
        assert client.http.follow_redirects is False
        assert client.http.trust_env is False

    per_call = Deadline(12).http_timeout()
    for value in (per_call.connect, per_call.read, per_call.write, per_call.pool):
        assert value is not None and 0 < value <= 12
    assert per_call.read == pytest.approx(12, abs=0.5)


def test_upstream_response_too_large_is_refused():
    inner = FakeBackend([http_answer(200, b"x" * 2048)])
    with OutboundClient(
        Deadline(30),
        resolver=public_resolver(),
        network_backend=inner,
        max_response_bytes=1024,
    ) as client:
        with pytest.raises(WarehouseError) as err:
            client.request("GET", "https://bigquery.googleapis.com/x")
    assert err.value.code is WarehouseErrorCode.RESULT_INVALID


def test_unreachable_is_coded():
    inner = FakeBackend([])  # every connect fails
    with OutboundClient(
        Deadline(30), resolver=public_resolver(), network_backend=inner
    ) as client:
        with pytest.raises(WarehouseError) as err:
            client.request("GET", "https://bigquery.googleapis.com/x")
    assert err.value.code is WarehouseErrorCode.UNREACHABLE
    assert err.value.__context__ is None and err.value.__cause__ is None


def test_resolution_failure_is_coded():
    def resolve(host, port):
        raise socket.gaierror("no such name")

    with OutboundClient(
        Deadline(30), resolver=resolve, network_backend=FakeBackend()
    ) as client:
        with pytest.raises(WarehouseError) as err:
            client.request("GET", "https://bigquery.googleapis.com/x")
    assert err.value.code is WarehouseErrorCode.UNREACHABLE


def test_httpx_timeout_type_is_what_the_client_passes():
    # Guard against an httpx upgrade that changes the Timeout shape the client
    # and Deadline.http_timeout rely on.
    assert isinstance(Deadline(30).http_timeout(), httpx.Timeout)


# --- Encoded answers: never decoded, the limit counted on the wire -------------

_EXPANDED_BYTES = 50_000_000


@pytest.fixture(scope="module")
def gzip_body() -> bytes:
    """About 50 KB on the wire that would be 50 MB once decoded."""
    import gzip

    return gzip.compress(b"\0" * _EXPANDED_BYTES, compresslevel=9)


@pytest.fixture
def decoder_calls(monkeypatch):
    """Records the size of every output of httpx's gzip decoder."""
    from httpx import _decoders

    calls = []
    original = _decoders.GZipDecoder.decode

    def spy(self, data):
        out = original(self, data)
        calls.append(len(out))
        return out

    monkeypatch.setattr(_decoders.GZipDecoder, "decode", spy)
    return calls


def test_requests_ask_for_identity_encoding():
    """Every request says Accept-Encoding: identity, whatever the caller passed."""
    inner = FakeBackend([http_answer(200, b"{}")])
    with OutboundClient(
        Deadline(30), resolver=public_resolver(), network_backend=inner
    ) as client:
        client.request(
            "GET",
            "https://bigquery.googleapis.com/x",
            headers={"Accept-Encoding": "gzip, br", "X-Other": "1"},
        )
    sent = b"".join(inner.requests_written).lower()
    assert b"accept-encoding: identity\r\n" in sent
    assert b"gzip" not in sent
    assert b"x-other: 1\r\n" in sent


def test_encoded_answer_refused_before_decoding(gzip_body, decoder_calls):
    """An answer with Content-Encoding: gzip is result_invalid; nothing is decoded."""
    assert len(gzip_body) < 100_000
    inner = FakeBackend(
        [http_answer(200, gzip_body, headers=[("Content-Encoding", "gzip")])]
    )
    with OutboundClient(
        Deadline(30), resolver=public_resolver(), network_backend=inner
    ) as client:
        with pytest.raises(WarehouseError) as err:
            client.request("GET", "https://bigquery.googleapis.com/x")
    assert err.value.code is WarehouseErrorCode.RESULT_INVALID
    assert decoder_calls == []


def test_body_limit_counts_bytes_on_the_wire(gzip_body, decoder_calls):
    """The body reader never decodes: it returns the bytes as sent, so a small
    encoded body cannot become a large one in memory.  Checked here on the
    reader alone, without the encoding refusal in front of it."""
    response = httpx.Response(
        200,
        headers={"Content-Encoding": "gzip"},
        stream=httpx.ByteStream(gzip_body),
    )
    with OutboundClient(Deadline(30), max_response_bytes=1_000_000) as client:
        body = client._read_body(response)
    assert decoder_calls == []
    assert body == gzip_body
