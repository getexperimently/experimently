"""The HTTP client warehouse connectors use: published endpoints, public addresses.

Three checks stand between a connector and the network, and each holds on its
own:

1. **The destination** (:class:`GuardedTransport`): ``https`` on port 443 to a
   host that is one of the warehouses' published endpoints --
   ``bigquery.googleapis.com``, ``oauth2.googleapis.com`` or an
   ``<org>-<account>.snowflakecomputing.com`` name built from a well-formed
   account identifier.  Anything else is ``destination_not_allowed`` before a
   name is resolved.
2. **The resolved address** (:class:`GuardedBackend`, the httpcore network
   backend): the name is resolved once, **every** address it resolves to must
   be public, and the connection is made to one of those checked addresses --
   never by resolving the name again.  Loopback, private (RFC 1918), shared
   (100.64/10), link-local (169.254/16, including 169.254.169.254 and
   169.254.170.2), multicast, reserved and
   unspecified addresses are refused, and so are IPv6 unique-local (fc00::/7)
   and link-local (fe80::/10) addresses and any IPv6 address that embeds one of
   the refused IPv4 addresses (IPv4-mapped, NAT64, 6to4, Teredo).  TLS still
   verifies the certificate against the original host name.
3. **The answer**: a 3xx is ``redirect_refused`` and is never followed; the
   body is read in chunks, with the total deadline checked before every read,
   and refused past :data:`MAX_RESPONSE_BYTES`.

The client ignores the environment (``trust_env=False``): no proxy variable can
route a request around the address check.

Every socket read and write made through :class:`GuardedBackend` is capped at
``min(per-call limit, remaining)`` of the operation's :class:`Deadline`, and
refused once it is spent -- that is the in-thread total deadline (see
:mod:`.deadlines`).
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Mapping, Optional, Tuple

import httpcore
import httpx

from modules.backend.app.warehouse.deadlines import (
    CONNECT_SECONDS,
    READ_SECONDS,
    Deadline,
)
from modules.backend.app.warehouse.errors import (
    WarehouseError,
    WarehouseErrorCode,
    sanitised,
)

#: The fixed Google endpoints: the BigQuery API and the OAuth token endpoint.
GOOGLE_HOSTS = frozenset({"bigquery.googleapis.com", "oauth2.googleapis.com"})

#: A Snowflake account identifier in the organisation-account form only
#: (``MYORG-MYACCOUNT``).  Locators, regions, URLs and ``privatelink`` names
#: do not match.
SNOWFLAKE_ACCOUNT = re.compile(r"[A-Za-z][A-Za-z0-9]*-[A-Za-z0-9_]{1,255}")

#: The host :func:`snowflake_host` builds from such an account.
SNOWFLAKE_HOST = re.compile(r"[a-z][a-z0-9]*-[a-z0-9-]{1,255}\.snowflakecomputing\.com")

#: A response body larger than this is refused (``result_invalid``).
MAX_RESPONSE_BYTES = 16 * 1024 * 1024

_REFUSED_V4_EXTRA = (
    ipaddress.ip_network("100.64.0.0/10"),  # shared address space (CGNAT)
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")

#: ``(host, port) -> [(address, port), ...]``.  Tests pass their own.
Resolver = Callable[[str, int], List[Tuple[str, int]]]


def snowflake_host(account: str) -> str:
    """The published host for a Snowflake organisation-account identifier.

    Refuses (``destination_not_allowed``) anything that is not exactly that
    form: a locator, a URL, a ``privatelink`` name, a port, a trailing newline.
    """
    if not isinstance(account, str) or not SNOWFLAKE_ACCOUNT.fullmatch(account):
        raise WarehouseError(
            WarehouseErrorCode.DESTINATION_NOT_ALLOWED, warehouse="snowflake"
        )
    return account.lower().replace("_", "-") + ".snowflakecomputing.com"


def is_published_endpoint(host: str) -> bool:
    """Whether ``host`` is one of the warehouses' published endpoints."""
    if not isinstance(host, str):
        return False
    name = host.lower()
    return name in GOOGLE_HOSTS or SNOWFLAKE_HOST.fullmatch(name) is not None


def _embedded_v4(address: ipaddress.IPv6Address) -> Optional[ipaddress.IPv4Address]:
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address in _NAT64 or address in _NAT64_LOCAL:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return address.teredo[1]
    # IPv4-compatible (deprecated) ::a.b.c.d
    if int(address) >> 32 == 0 and int(address) > 1:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


def refused_address(value: str) -> bool:
    """True for any address a warehouse connection must not be made to.

    Anything that does not parse as an IP address is refused too.
    """
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(address, ipaddress.IPv6Address):
        embedded = _embedded_v4(address)
        if embedded is not None and refused_address(str(embedded)):
            return True
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or not address.is_global
    ):
        return True
    if isinstance(address, ipaddress.IPv4Address):
        return any(address in network for network in _REFUSED_V4_EXTRA)
    return False


def system_resolver(host: str, port: int) -> List[Tuple[str, int]]:
    """Resolve with the system resolver: every TCP address, in its order."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [(str(info[4][0]), int(info[4][1])) for info in infos]


class _DeadlineStream(httpcore.NetworkStream):
    """A network stream whose every read and write is bounded by a Deadline."""

    def __init__(self, inner: httpcore.NetworkStream, deadline: Deadline) -> None:
        self._inner = inner
        self._deadline = deadline

    def read(self, max_bytes: int, timeout: Optional[float] = None) -> bytes:
        return self._inner.read(max_bytes, self._deadline.cap(timeout))

    def write(self, buffer: bytes, timeout: Optional[float] = None) -> None:
        self._inner.write(buffer, self._deadline.cap(timeout))

    def close(self) -> None:
        self._inner.close()

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> httpcore.NetworkStream:
        inner = self._inner.start_tls(
            ssl_context, server_hostname, self._deadline.cap(timeout)
        )
        return _DeadlineStream(inner, self._deadline)

    def get_extra_info(self, info: str) -> Any:
        return self._inner.get_extra_info(info)


class GuardedBackend(httpcore.NetworkBackend):
    """An httpcore network backend that connects only to checked public addresses."""

    def __init__(
        self,
        deadline: Deadline,
        *,
        resolver: Optional[Resolver] = None,
        inner: Optional[httpcore.NetworkBackend] = None,
    ) -> None:
        self._deadline = deadline
        self._resolve: Resolver = resolver or system_resolver
        self._inner = inner or httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Optional[Iterable[Any]] = None,
    ) -> httpcore.NetworkStream:
        self._deadline.check()
        resolve_failed = False
        addresses: List[Tuple[str, int]] = []
        try:
            addresses = list(self._resolve(host, port))
        except (OSError, UnicodeError):
            resolve_failed = True
        if resolve_failed or not addresses:
            raise WarehouseError(WarehouseErrorCode.UNREACHABLE)
        # Every address must pass, not just the one we would use: a name that
        # resolves to a public and a private address is refused outright.
        if any(refused_address(address) for address, _ in addresses):
            raise WarehouseError(WarehouseErrorCode.DESTINATION_NOT_ALLOWED)
        last_error: Optional[BaseException] = None
        for address, address_port in addresses:
            try:
                stream = self._inner.connect_tcp(
                    address,
                    address_port,
                    timeout=self._deadline.cap(
                        CONNECT_SECONDS
                        if timeout is None
                        else min(timeout, CONNECT_SECONDS)
                    ),
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
                continue
            return _DeadlineStream(stream, self._deadline)
        if isinstance(last_error, httpcore.ConnectTimeout):
            raise httpcore.ConnectTimeout("connect")
        raise httpcore.ConnectError("connect")

    def connect_unix_socket(
        self,
        path: str,
        timeout: Optional[float] = None,
        socket_options: Optional[Iterable[Any]] = None,
    ) -> httpcore.NetworkStream:
        raise WarehouseError(WarehouseErrorCode.DESTINATION_NOT_ALLOWED)

    def sleep(self, seconds: float) -> None:
        self._deadline.sleep(seconds)


def _check_destination(url: httpx.URL) -> None:
    if url.scheme != "https":
        raise WarehouseError(WarehouseErrorCode.DESTINATION_NOT_ALLOWED)
    if url.port not in (None, 443):
        raise WarehouseError(WarehouseErrorCode.DESTINATION_NOT_ALLOWED)
    if url.userinfo:
        raise WarehouseError(WarehouseErrorCode.DESTINATION_NOT_ALLOWED)
    if not is_published_endpoint(url.host):
        raise WarehouseError(WarehouseErrorCode.DESTINATION_NOT_ALLOWED)


class GuardedTransport(httpx.HTTPTransport):
    """httpx's own transport over a :class:`GuardedBackend`, with destination checks.

    The destination is checked on every request, so a client built on this
    transport cannot reach another host whatever its own settings; a 3xx
    answer is refused here, so it cannot be followed either.
    """

    def __init__(
        self,
        deadline: Deadline,
        *,
        resolver: Optional[Resolver] = None,
        network_backend: Optional[httpcore.NetworkBackend] = None,
        destination_check: Callable[[httpx.URL], None] = _check_destination,
    ) -> None:
        super().__init__(verify=True, trust_env=False, retries=0)
        self._destination_check = destination_check
        self.network_backend = GuardedBackend(
            deadline, resolver=resolver, inner=network_backend
        )
        # httpx.HTTPTransport takes no network backend of its own; the pool it
        # built is replaced by the same pool over the guarded backend.
        # test_transport_uses_the_guarded_backend pins that this took effect.
        self._pool.close()
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=4,
            max_keepalive_connections=4,
            keepalive_expiry=5.0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=self.network_backend,
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._destination_check(request.url)
        response = super().handle_request(request)
        if 300 <= response.status_code < 400:
            response.close()
            raise WarehouseError(
                WarehouseErrorCode.REDIRECT_REFUSED, http_status=response.status_code
            )
        return response


@dataclass(frozen=True)
class OutboundResponse:
    """A fully read, size-bounded answer: status, headers and body bytes."""

    status_code: int
    headers: Mapping[str, str]
    content: bytes

    def json(self) -> Any:
        """The body as JSON; ``result_invalid`` when it is not."""
        parsed: Any = None
        failed = False
        try:
            parsed = json.loads(self.content)
        except (ValueError, UnicodeDecodeError):
            failed = True
        if failed:
            raise WarehouseError(WarehouseErrorCode.RESULT_INVALID)
        return parsed


def http_client_timeout() -> httpx.Timeout:
    """The client-wide limits; each call is further capped by its deadline."""
    return httpx.Timeout(
        connect=CONNECT_SECONDS,
        read=READ_SECONDS,
        write=READ_SECONDS,
        pool=CONNECT_SECONDS,
    )


class OutboundClient:
    """The HTTP client a connector uses for one operation, under one Deadline.

    Use it as a context manager, in the executor's worker thread.  Failures
    are :class:`WarehouseError` only: a refused destination, a redirect, the
    deadline, an unreachable host.  A non-2xx answer is returned, not raised,
    so the adapter can map the vendor's structured code
    (:func:`~.errors.error_for_status`).
    """

    def __init__(
        self,
        deadline: Deadline,
        *,
        warehouse: Optional[str] = None,
        resolver: Optional[Resolver] = None,
        network_backend: Optional[httpcore.NetworkBackend] = None,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        transport: Optional[GuardedTransport] = None,
    ) -> None:
        self.deadline = deadline
        self.warehouse = warehouse
        self._max_response_bytes = max_response_bytes
        self.transport = transport or GuardedTransport(
            deadline, resolver=resolver, network_backend=network_backend
        )
        self.http = httpx.Client(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=http_client_timeout(),
        )

    def __enter__(self) -> "OutboundClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.http.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Mapping[str, str]] = None,
        content: Optional[bytes] = None,
        json_body: Any = None,
    ) -> OutboundResponse:
        """Send one request and read the whole answer within the deadline."""
        failure: Optional[WarehouseError] = None
        try:
            timeout = self.deadline.http_timeout()
            with self.http.stream(
                method,
                url,
                headers=headers,
                params=params,
                content=content,
                json=json_body,
                timeout=timeout,
            ) as response:
                body = self._read_body(response)
                return OutboundResponse(
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content=body,
                )
        except WarehouseError as exc:
            failure = exc
        except httpx.TimeoutException:
            failure = WarehouseError(WarehouseErrorCode.TIME_LIMIT)
        except (httpx.HTTPError, httpx.InvalidURL, OSError):
            failure = WarehouseError(WarehouseErrorCode.UNREACHABLE)
        # Raised here, outside the handlers, so no upstream exception is
        # chained onto what we raise.
        assert failure is not None
        failure.warehouse = failure.warehouse or (
            self.warehouse
            if self.warehouse in ("bigquery", "snowflake", "athena")
            else None
        )
        raise sanitised(failure)

    def _read_body(self, response: httpx.Response) -> bytes:
        chunks: List[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > self._max_response_bytes:
                raise WarehouseError(WarehouseErrorCode.RESULT_INVALID)
            chunks.append(chunk)
        return b"".join(chunks)


__all__ = [
    "GOOGLE_HOSTS",
    "MAX_RESPONSE_BYTES",
    "GuardedBackend",
    "GuardedTransport",
    "OutboundClient",
    "OutboundResponse",
    "Resolver",
    "http_client_timeout",
    "is_published_endpoint",
    "refused_address",
    "snowflake_host",
    "system_resolver",
]
