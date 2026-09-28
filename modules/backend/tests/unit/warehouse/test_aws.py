"""boto3 clients reach only the fixed regional endpoints, on public addresses.

No test here can reach AWS: ``socket.getaddrinfo`` is replaced for the
duration of each test, so every name -- in the hook and in botocore's own
HTTP layer -- resolves to the answer the test chose, and the credentials are
dummies.
"""

from __future__ import annotations

import socket
import threading
import time

import boto3
import pytest

from modules.backend.app.warehouse import aws as make_client_module
from modules.backend.app.warehouse.aws import (
    AWS_REGIONS,
    BeforeSendGuard,
    aws_endpoint_host,
    boto_config,
    make_client,
)
from modules.backend.app.warehouse.aws import call as aws_call
from modules.backend.app.warehouse.deadlines import Deadline
from modules.backend.app.warehouse.errors import WarehouseError, WarehouseErrorCode
from modules.backend.tests.unit.warehouse.conftest import FakeClock

REFUSED = WarehouseErrorCode.DESTINATION_NOT_ALLOWED


@pytest.fixture
def aws_env(monkeypatch):
    for name in (
        "AWS_PROFILE",
        "AWS_SESSION_TOKEN",
        "AWS_ENDPOINT_URL",
        "AWS_ENDPOINT_URL_STS",
        "AWS_USE_FIPS_ENDPOINT",
        "AWS_USE_DUALSTACK_ENDPOINT",
        "HTTPS_PROXY",
        "https_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def _session():
    return boto3.session.Session(
        aws_access_key_id="AKIDUMMYDUMMYDUMMY00",
        aws_secret_access_key="dummy-secret",
        region_name="us-east-1",
    )


def _resolve_everything_to(monkeypatch, address: str, port: int) -> list:
    """Every lookup answers ``address:port``; returns the list of names looked up."""
    looked_up = []
    family = socket.AF_INET6 if ":" in address else socket.AF_INET

    def fake_getaddrinfo(host, service, *args, **kwargs):
        looked_up.append(host)
        sockaddr = (
            (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
        )
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return looked_up


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "169.254.169.254"])
def test_boto_before_send_refuses_private(address, probe, aws_env, monkeypatch):
    """The STS endpoint name resolving to a private address: the call is refused
    before botocore sends it, and (for loopback) the probe accepts nothing."""
    port = probe.port if address == "127.0.0.1" else 443
    looked_up = _resolve_everything_to(monkeypatch, address, port)
    client = make_client(_session(), "sts", "us-east-1")
    try:
        client.get_caller_identity()
        outcome = "sent"
    except WarehouseError as err:
        outcome = err.code
    except Exception as exc:  # botocore's own failure, once it has sent
        outcome = type(exc).__name__
    for _ in range(10):
        if probe.accepted:
            break
        time.sleep(0.02)
    assert probe.accepted == 0
    assert outcome is REFUSED
    assert looked_up and set(looked_up) == {"sts.us-east-1.amazonaws.com"}


def test_boto_before_send_lets_a_public_address_through(aws_env, monkeypatch):
    """Positive control: a public answer passes the hook (the send is then stopped
    by a later handler, so nothing leaves the machine)."""
    _resolve_everything_to(monkeypatch, "93.184.216.34", 443)
    client = make_client(_session(), "sts", "us-east-1")
    seen = []

    class Stop(Exception):
        pass

    def stop(request, **kwargs):
        seen.append(request.url)
        raise Stop()

    client.meta.events.register("before-send", stop)
    with pytest.raises(Stop):
        client.get_caller_identity()
    assert seen == ["https://sts.us-east-1.amazonaws.com/"]


def test_boto_hook_refuses_another_host():
    guard = BeforeSendGuard(
        "sts.us-east-1.amazonaws.com", resolver=lambda h, p: [("93.184.216.34", p)]
    )

    class Request:
        url = "https://sts.us-east-1.amazonaws.com.example.com/"

    with pytest.raises(WarehouseError) as err:
        guard(Request())
    assert err.value.code is REFUSED


def test_boto_hook_refuses_after_the_deadline():
    clock = FakeClock()
    deadline = Deadline(10, clock=clock)
    guard = BeforeSendGuard(
        "athena.us-east-1.amazonaws.com",
        deadline=deadline,
        resolver=lambda h, p: [("93.184.216.34", p)],
    )

    class Request:
        url = "https://athena.us-east-1.amazonaws.com/"

    guard(Request())
    clock.advance(10)
    with pytest.raises(WarehouseError) as err:
        guard(Request())
    assert err.value.code is WarehouseErrorCode.TIME_LIMIT


@pytest.mark.parametrize(
    "service,region",
    [
        ("s3", "us-east-1"),
        ("sts", "cn-north-1"),
        ("athena", "us-gov-west-1"),
        ("glue", "local"),
    ],
)
def test_only_fixed_services_and_regions(service, region, aws_env):
    with pytest.raises(WarehouseError) as err:
        make_client(_session(), service, region)
    assert err.value.code is REFUSED


def test_a_configured_endpoint_override_is_refused(aws_env, monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://127.0.0.1:4566")
    with pytest.raises(WarehouseError) as err:
        make_client(_session(), "sts", "us-east-1")
    assert err.value.code is REFUSED


def test_boto_config_has_fixed_limits_and_no_proxies():
    config = boto_config()
    assert config.connect_timeout == 5
    assert config.read_timeout == 30
    assert config.retries == {"total_max_attempts": 2, "mode": "standard"}
    assert config.proxies == {}


class _SilentServer:
    """Accepts TCP connections on 127.0.0.1 and never sends a byte."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self.held = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, OSError):
                continue
            self.held.append(conn)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(2)
        for conn in self.held:
            conn.close()
        self._sock.close()


def test_boto_limits_follow_the_deadline():
    """With 2 s left: connect and read limits of 2 s and a single attempt; with
    plenty left, the fixed 5 s / 30 s and two attempts; with none, time_limit."""
    clock = FakeClock()
    deadline = Deadline(100, clock=clock)
    roomy = boto_config(deadline)
    assert (roomy.connect_timeout, roomy.read_timeout) == (5, 30)
    assert roomy.retries == {"total_max_attempts": 2, "mode": "standard"}
    clock.advance(98)
    tight = boto_config(deadline)
    assert tight.connect_timeout == pytest.approx(2)
    assert tight.read_timeout == pytest.approx(2)
    assert tight.retries == {"total_max_attempts": 1, "mode": "standard"}
    clock.advance(2)
    with pytest.raises(WarehouseError) as err:
        boto_config(deadline)
    assert err.value.code is WarehouseErrorCode.TIME_LIMIT


def test_boto_call_with_two_seconds_left_is_bounded_by_them(aws_env, monkeypatch):
    """A call to an endpoint that never answers, with 2 s left on the deadline,
    ends within a few seconds -- not the fixed 5 s + 30 s x 2 attempts.

    The deadline's clock is fake (it says 2 s are left); the wait is botocore's
    own socket limits, which is what is under test.  Every name resolves to a
    local listener that accepts and never answers; the address check is given a
    public answer so the call reaches botocore's send.
    """
    server = _SilentServer()
    try:
        _resolve_everything_to(monkeypatch, "127.0.0.1", server.port)
        clock = FakeClock()
        deadline = Deadline(60, clock=clock)
        clock.advance(58)
        started = time.monotonic()
        with pytest.raises(WarehouseError) as err:
            aws_call(
                _session(),
                "sts",
                "us-east-1",
                "get_caller_identity",
                deadline=deadline,
                resolver=lambda host, port: [("93.184.216.34", port)],
            )
        elapsed = time.monotonic() - started
    finally:
        server.close()
    assert err.value.code in (
        WarehouseErrorCode.TIME_LIMIT,
        WarehouseErrorCode.UNREACHABLE,
    )
    assert server.held, "the call never reached the listener"
    # One attempt and one connection, each wait capped at the 2 s left
    # (measured about 2.2 s); the fixed limits take over 60 s here.
    assert len(server.held) == 1
    assert elapsed < 5.0, f"took {elapsed:.1f} s with 2 s left"


def test_boto_client_errors_are_coded(aws_env, monkeypatch):
    """An AWS error answer maps by its structured Code; its message is dropped."""
    from botocore.stub import Stubber

    _resolve_everything_to(monkeypatch, "93.184.216.34", 443)
    session = _session()
    real_make = make_client_module.make_client

    def stubbed(*args, **kwargs):
        client = real_make(*args, **kwargs)
        stubber = Stubber(client)
        stubber.add_client_error(
            "get_caller_identity",
            service_error_code="AccessDenied",
            service_message="not for you: MESSAGE-TEXT-91",
            http_status_code=403,
        )
        stubber.activate()
        return client

    monkeypatch.setattr(make_client_module, "make_client", stubbed)
    with pytest.raises(WarehouseError) as err:
        aws_call(
            session, "sts", "us-east-1", "get_caller_identity", deadline=Deadline(30)
        )
    assert err.value.code is WarehouseErrorCode.PERMISSION_DENIED
    assert err.value.vendor_code == "AccessDenied"
    assert "MESSAGE-TEXT-91" not in repr(err.value) + err.value.message
    assert err.value.__context__ is None


def test_region_list_is_the_committed_data():
    assert len(AWS_REGIONS) == 34
    assert aws_endpoint_host("athena", "eu-west-1") == "athena.eu-west-1.amazonaws.com"
