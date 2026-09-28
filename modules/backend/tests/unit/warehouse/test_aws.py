"""boto3 clients reach only the fixed regional endpoints, on public addresses.

No test here can reach AWS: ``socket.getaddrinfo`` is replaced for the
duration of each test, so every name -- in the hook and in botocore's own
HTTP layer -- resolves to the answer the test chose, and the credentials are
dummies.
"""

from __future__ import annotations

import socket
import time

import boto3
import pytest

from modules.backend.app.warehouse.aws import (
    AWS_REGIONS,
    BeforeSendGuard,
    aws_endpoint_host,
    boto_config,
    make_client,
)
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
    assert config.retries == {"max_attempts": 2, "mode": "standard"}
    assert config.proxies == {}


def test_region_list_is_the_committed_data():
    assert len(AWS_REGIONS) == 34
    assert aws_endpoint_host("athena", "eu-west-1") == "athena.eu-west-1.amazonaws.com"
