"""boto3 clients for the AWS services a connector uses, on fixed endpoints only.

:func:`make_client` is the one way a connector gets a boto3 client:

* only ``sts``, ``athena`` and ``glue``, only in a region from
  :data:`AWS_REGIONS` (committed data: botocore's regions for those services);
* boto3's own regional endpoint -- ``endpoint_url`` is never set, and a client
  whose resolved endpoint is anything but ``https://<service>.<region>.amazonaws.com``
  (an ``AWS_ENDPOINT_URL`` variable, a FIPS or dual-stack setting) is refused;
* no environment proxy (``proxies={}``);
* :func:`boto_config`'s fixed limits;
* a ``before-send`` hook (:class:`BeforeSendGuard`) that refuses the call
  unless the request's host is that endpoint, every address it resolves to is
  public (the same rule as :func:`.egress.refused_address`), and the
  operation's deadline has time left.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlsplit

from botocore.config import Config

from modules.backend.app.warehouse.deadlines import (
    CONNECT_SECONDS,
    READ_SECONDS,
    Deadline,
)
from modules.backend.app.warehouse.egress import (
    Resolver,
    refused_address,
    system_resolver,
)
from modules.backend.app.warehouse.errors import WarehouseError, WarehouseErrorCode

#: The services a connector may call.
AWS_SERVICES = frozenset({"sts", "athena", "glue"})

#: botocore's regions for athena, sts and glue in the ``aws`` partition
#: (identical lists; 34 regions as of botocore 1.43).
AWS_REGIONS = frozenset(
    {
        "af-south-1",
        "ap-east-1",
        "ap-east-2",
        "ap-northeast-1",
        "ap-northeast-2",
        "ap-northeast-3",
        "ap-south-1",
        "ap-south-2",
        "ap-southeast-1",
        "ap-southeast-2",
        "ap-southeast-3",
        "ap-southeast-4",
        "ap-southeast-5",
        "ap-southeast-6",
        "ap-southeast-7",
        "ca-central-1",
        "ca-west-1",
        "eu-central-1",
        "eu-central-2",
        "eu-north-1",
        "eu-south-1",
        "eu-south-2",
        "eu-west-1",
        "eu-west-2",
        "eu-west-3",
        "il-central-1",
        "me-central-1",
        "me-south-1",
        "mx-central-1",
        "sa-east-1",
        "us-east-1",
        "us-east-2",
        "us-west-1",
        "us-west-2",
    }
)


def aws_endpoint_host(service: str, region: str) -> str:
    """``<service>.<region>.amazonaws.com``, for an allowed service and region."""
    if service not in AWS_SERVICES or region not in AWS_REGIONS:
        raise WarehouseError(
            WarehouseErrorCode.DESTINATION_NOT_ALLOWED, warehouse="athena"
        )
    return f"{service}.{region}.amazonaws.com"


def boto_config() -> Config:
    """Connect within 5 s, each read within 30 s, two attempts, no proxies."""
    return Config(
        connect_timeout=CONNECT_SECONDS,
        read_timeout=READ_SECONDS,
        retries={"max_attempts": 2, "mode": "standard"},
        proxies={},
    )


class BeforeSendGuard:
    """The botocore ``before-send`` handler: destination, address and deadline."""

    def __init__(
        self,
        expected_host: str,
        *,
        deadline: Optional[Deadline] = None,
        resolver: Optional[Resolver] = None,
    ) -> None:
        self.expected_host = expected_host
        self._deadline = deadline
        self._resolve: Resolver = resolver or system_resolver

    def __call__(self, request: Any, **kwargs: Any) -> None:
        if self._deadline is not None:
            self._deadline.check()
        parts = urlsplit(request.url)
        if (
            parts.scheme != "https"
            or parts.port not in (None, 443)
            or (parts.hostname or "").lower() != self.expected_host
        ):
            raise WarehouseError(
                WarehouseErrorCode.DESTINATION_NOT_ALLOWED, warehouse="athena"
            )
        resolve_failed = False
        addresses = []
        try:
            addresses = list(self._resolve(self.expected_host, 443))
        except (OSError, UnicodeError):
            resolve_failed = True
        if resolve_failed or not addresses:
            raise WarehouseError(WarehouseErrorCode.UNREACHABLE, warehouse="athena")
        if any(refused_address(address) for address, _ in addresses):
            raise WarehouseError(
                WarehouseErrorCode.DESTINATION_NOT_ALLOWED, warehouse="athena"
            )
        # Returning None lets botocore send the request itself.
        return


def make_client(
    session: Any,
    service: str,
    region: str,
    *,
    deadline: Optional[Deadline] = None,
    resolver: Optional[Resolver] = None,
) -> Any:
    """A boto3 client for ``service`` in ``region`` with the guard installed.

    ``session`` is a ``boto3.session.Session``; the caller decides whose
    credentials it holds.
    """
    host = aws_endpoint_host(service, region)
    client = session.client(service, region_name=region, config=boto_config())
    if client.meta.endpoint_url.rstrip("/") != f"https://{host}":
        raise WarehouseError(
            WarehouseErrorCode.DESTINATION_NOT_ALLOWED, warehouse="athena"
        )
    client.meta.events.register(
        "before-send", BeforeSendGuard(host, deadline=deadline, resolver=resolver)
    )
    return client


__all__ = [
    "AWS_REGIONS",
    "AWS_SERVICES",
    "BeforeSendGuard",
    "aws_endpoint_host",
    "boto_config",
    "make_client",
]
