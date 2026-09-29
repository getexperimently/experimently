"""The BigQuery connector: a service-account key, the BigQuery REST API, and limits.

Disabled until verified (:mod:`.connectors`): the code is complete, but no
deployment can use it until a check against a real BigQuery project has
passed and :data:`~.connectors.ENABLED_CONNECTORS` names it.

Credentials
-----------
The customer pastes a service-account JSON key.
:func:`parse_service_account_json` accepts only ``"type": "service_account"``
with a well-formed ``client_email``, a ``private_key_id`` and an unencrypted
PKCS#8 RSA ``private_key``.  If the key carries ``token_uri`` it must be
exactly :data:`TOKEN_URL`, and ``universe_domain`` exactly ``googleapis.com``.
Only four fields are kept -- ``client_email``, ``private_key_id``,
``private_key`` and ``project_id`` (:meth:`ServiceAccountKey.to_blob`) -- so
nothing else in the pasted key, and in particular none of its URLs, is ever
stored or used.

Sign-in
-------
:class:`BigQueryAdapter` signs an RS256 assertion with PyJWT (``iss`` the
service account, ``scope`` BigQuery, ``aud`` the token URL, one hour) and
POSTs it to the constant :data:`TOKEN_URL`.  The access token is kept in
memory until five minutes before it expires.  A refused sign-in is
``auth_failed``, or ``key_revoked`` when Google says the key's client is
disabled or deleted; only the ``error`` field of the answer is read.

Queries
-------
1. ``jobs.insert`` with ``dryRun: true``.  ``statistics.query.statementType``
   must be ``SELECT`` (else ``not_a_select``) and
   ``statistics.query.totalBytesProcessed`` at most the connection's byte cap
   (else ``bytes_limit``).  Nothing runs or bills.
2. ``jobs.insert`` for real, under a job id we generate, with
   ``maximumBytesBilled`` (the byte cap), ``jobTimeoutMs`` (the query limit,
   never more than the time left), ``labels``, ``useLegacySql: false`` and the
   connection's location.  ``jobs.query`` is never used, so every query is a
   job with an id we know before it starts.
3. ``jobs.getQueryResults`` is polled (each wait at most 10 s) until the job
   completes, then ``jobs.get`` reads the bytes billed.
4. If the operation's deadline arrives first, ``jobs.cancel`` is sent and the
   query fails with ``time_limit``.  Cancellation is asynchronous on
   BigQuery's side and a cancelled job may still be billed for what it read.

The deadline is the executor's in-thread :class:`~.deadlines.Deadline`.  Polls
stop :data:`CANCEL_RESERVE_SECONDS` before it, so the cancel is normally sent
within the total; if a slow answer has used that reserve, the cancel gets its
own :data:`CANCEL_RESERVE_SECONDS`, which is the most a query can run past its
total.

Every request goes through :class:`~.egress.OutboundClient`, to
``oauth2.googleapis.com`` or ``bigquery.googleapis.com`` only.  Errors are
mapped from Google's structured ``reason`` and the HTTP status
(:data:`REASON_CODES`); no message text from Google is read into anything we
raise, return or log.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Final, List, Mapping, Optional, Tuple
from urllib.parse import quote, urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from modules.backend.app.core.warehouse_identifiers import (
    BIGQUERY,
    validate_table_parts,
)
from modules.backend.app.services.warehouse_query_builder import BuiltQuery
from modules.backend.app.warehouse.deadlines import Deadline, Sleeper
from modules.backend.app.warehouse.egress import OutboundClient, OutboundResponse
from modules.backend.app.warehouse.errors import (
    WarehouseError,
    WarehouseErrorCode,
    error_for_status,
    log_warehouse_error,
    sanitised,
)

WAREHOUSE: Final = "bigquery"

#: The only token endpoint a key is ever exchanged at.
TOKEN_URL: Final = "https://oauth2.googleapis.com/token"
#: The only universe a pasted key may name.
UNIVERSE_DOMAIN: Final = "googleapis.com"
#: The BigQuery REST API root.
API_ROOT: Final = "https://bigquery.googleapis.com/bigquery/v2"
SCOPE: Final = "https://www.googleapis.com/auth/bigquery"
GRANT_TYPE: Final = "urn:ietf:params:oauth:grant-type:jwt-bearer"
#: Seconds an assertion is valid (Google's maximum).
ASSERTION_LIFETIME_SECONDS: Final = 3600
#: A cached access token is not used within this many seconds of its expiry.
TOKEN_REFRESH_MARGIN_SECONDS: Final = 300
#: The largest service-account JSON accepted, in bytes.
MAX_SERVICE_ACCOUNT_JSON_BYTES: Final = 16 * 1024
#: The smallest RSA key accepted.
MIN_RSA_KEY_BITS: Final = 2048
#: Each ``getQueryResults`` call waits at most this long for the job.
POLL_TIMEOUT_MS: Final = 10_000
#: Seconds between polls that returned early without a finished job.
POLL_PAUSE_SECONDS: Final = 0.5
#: Polls stop this many seconds before the deadline, to leave time to cancel.
CANCEL_RESERVE_SECONDS: Final = 5.0
#: Result pages read for one query (a result is at most 51 rows).
MAX_RESULT_PAGES: Final = 5
MAX_RESULT_ROWS: Final = 1000
#: Labels set on every job, so the customer can find them in their billing.
JOB_LABELS: Final = {"experimently": "analysis"}
#: A cheap statement for the connection test's dry run.
CONNECTION_TEST_SQL: Final = "SELECT 1 AS ok"

# Field patterns, applied only with fullmatch.
BILLING_PROJECT: Final = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
LOCATION: Final = re.compile(r"[A-Za-z]+(-[a-z]+[0-9]*)*")
CLIENT_EMAIL: Final = re.compile(
    r"[a-z0-9-]{6,30}@[a-z0-9-]+\.iam\.gserviceaccount\.com"
)
PRIVATE_KEY_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,128}")
#: The PEM header of an unencrypted PKCS#8 key (split so no scanner reads
#: this line as a key).
_PKCS8_BEGIN: Final = "-----BEGIN " + "PRIVATE KEY-----"
_JOB_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,1024}")
_INT64_TEXT: Final = re.compile(r"[0-9]{1,19}")
_FIELD_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,299}")
_TYPE_NAME: Final = re.compile(r"[A-Z0-9_]{1,32}")
_ACCESS_TOKEN: Final = re.compile(r"[A-Za-z0-9._~+/=-]{1,4096}")

_C = WarehouseErrorCode

#: Google's structured error ``reason`` -> our code.  Anything else falls
#: back on the HTTP status (:func:`~.errors.error_for_status`).
REASON_CODES: Final[Mapping[str, WarehouseErrorCode]] = {
    "accessDenied": _C.PERMISSION_DENIED,
    "notFound": _C.OBJECT_NOT_FOUND,
    "bytesBilledLimitExceeded": _C.BYTES_LIMIT,
    "timeout": _C.TIME_LIMIT,
    "stopped": _C.CANCELLED,
    "responseTooLarge": _C.RESULT_INVALID,
    "authError": _C.AUTH_FAILED,
}

#: The token endpoint's ``error`` values that mean the key itself is unusable.
REVOKED_KEY_ERRORS: Final = frozenset({"disabled_client", "deleted_client"})


# -- the pasted key -----------------------------------------------------------


class BigQueryConfigRefused(ValueError):
    """A BigQuery connection field was refused (422).  ``code`` is from a fixed set.

    The message is fixed per code and never contains what was submitted.
    """

    MESSAGES: Final = {
        "invalid_service_account": (
            "The service-account key isn't valid. Paste the whole JSON key file "
            "downloaded from IAM & Admin > Service accounts > Keys."
        ),
        "unsupported_credential_type": (
            "This is not a service-account key. Create a service account and "
            "download a JSON key for it (IAM & Admin > Service accounts > Keys); "
            "user credentials and workload identity configurations aren't supported."
        ),
        "token_endpoint_not_allowed": (
            "The key names a sign-in endpoint other than Google's "
            "(https://oauth2.googleapis.com/token). Only keys for Google Cloud's "
            "public endpoints are supported."
        ),
        "invalid_billing_project": (
            "Use the billing project's ID (6-30 lower-case letters, digits and "
            "hyphens), e.g. my-analytics-project."
        ),
        "invalid_location": "Use a BigQuery location such as US, EU or europe-west2.",
    }

    def __init__(self, code: str, field: str) -> None:
        if code not in self.MESSAGES:
            raise ValueError("unknown refusal code")
        self.code = code
        self.field = field
        self.message = self.MESSAGES[code]
        super().__init__(self.message)

    def to_body(self) -> Dict[str, str]:
        return {"code": self.code, "field": self.field, "message": self.message}


def _refuse(code: str, field: str = "service_account_json") -> BigQueryConfigRefused:
    return BigQueryConfigRefused(code, field)


@dataclass(frozen=True, repr=False)
class ServiceAccountKey:
    """The four fields of a service-account key that are kept."""

    client_email: str
    private_key_id: str
    private_key: str
    project_id: Optional[str]

    #: The exact keys of :meth:`to_blob`.
    FIELDS: Final = ("client_email", "private_key_id", "private_key", "project_id")

    def to_blob(self) -> bytes:
        """The plaintext to encrypt and store: exactly the four fields."""
        return json.dumps(
            {name: getattr(self, name) for name in self.FIELDS},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @classmethod
    def from_blob(cls, blob: bytes) -> "ServiceAccountKey":
        """Read a stored blob back.  Anything but the four fields is ``internal``."""
        data: Any = None
        try:
            data = json.loads(bytes(blob).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, TypeError):
            data = None
        if not isinstance(data, dict) or set(data) != set(cls.FIELDS):
            raise WarehouseError(_C.INTERNAL, warehouse=WAREHOUSE)
        if not all(
            isinstance(data[name], str)
            for name in ("client_email", "private_key_id", "private_key")
        ) or not (data["project_id"] is None or isinstance(data["project_id"], str)):
            raise WarehouseError(_C.INTERNAL, warehouse=WAREHOUSE)
        return cls(
            client_email=data["client_email"],
            private_key_id=data["private_key_id"],
            private_key=data["private_key"],
            project_id=data["project_id"],
        )

    @property
    def cache_key(self) -> str:
        """A digest identifying this key, for the token cache."""
        return hashlib.sha256(self.to_blob()).hexdigest()

    def __repr__(self) -> str:
        return f"ServiceAccountKey(client_email={self.client_email!r})"


def _no_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    seen: Dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate key")
        seen[key] = value
    return seen


def _fullmatch(pattern: "re.Pattern[str]", value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def check_token_endpoint(data: Mapping[str, Any]) -> None:
    """Refuse a key naming any token endpoint or universe but Google's own."""
    if "token_uri" in data and data["token_uri"] != TOKEN_URL:
        raise _refuse("token_endpoint_not_allowed")
    if "universe_domain" in data and data["universe_domain"] != UNIVERSE_DOMAIN:
        raise _refuse("token_endpoint_not_allowed")


def _load_rsa_key(pem: object) -> Optional[RSAPrivateKey]:
    if not isinstance(pem, str) or not pem.lstrip().startswith(_PKCS8_BEGIN):
        return None
    try:
        key = load_pem_private_key(pem.encode("ascii"), password=None)
    except Exception:
        # Any parse failure refuses; its text is not kept.
        return None
    if not isinstance(key, RSAPrivateKey) or key.key_size < MIN_RSA_KEY_BITS:
        return None
    return key


def parse_service_account_json(text: object) -> ServiceAccountKey:
    """Check a pasted service-account JSON key and keep its four fields.

    Raises :class:`BigQueryConfigRefused` with ``invalid_service_account``,
    ``unsupported_credential_type`` or ``token_endpoint_not_allowed``.
    """
    raw: bytes
    if isinstance(text, str):
        raw = text.encode("utf-8", errors="replace")
    elif isinstance(text, (bytes, bytearray)):
        raw = bytes(text)
    else:
        raise _refuse("invalid_service_account")
    if len(raw) > MAX_SERVICE_ACCOUNT_JSON_BYTES:
        raise _refuse("invalid_service_account")
    data: Any = None
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (ValueError, UnicodeDecodeError, RecursionError):
        data = None
    if not isinstance(data, dict):
        raise _refuse("invalid_service_account")

    kind = data.get("type")
    if kind in ("authorized_user", "external_account", "impersonated_service_account"):
        raise _refuse("unsupported_credential_type")
    if kind != "service_account":
        raise _refuse("invalid_service_account")
    check_token_endpoint(data)

    email = data.get("client_email")
    key_id = data.get("private_key_id")
    pem = data.get("private_key")
    project = data.get("project_id")
    if not _fullmatch(CLIENT_EMAIL, email) or not _fullmatch(PRIVATE_KEY_ID, key_id):
        raise _refuse("invalid_service_account")
    if project is not None and not _fullmatch(BILLING_PROJECT, project):
        raise _refuse("invalid_service_account")
    if _load_rsa_key(pem) is None:
        raise _refuse("invalid_service_account")
    return ServiceAccountKey(
        client_email=email, private_key_id=key_id, private_key=pem, project_id=project
    )


# -- the connection -----------------------------------------------------------


@dataclass(frozen=True)
class BigQueryConnection:
    """The non-secret parameters and limits of one BigQuery connection."""

    billing_project: str
    location: str
    max_bytes_per_query: int
    query_timeout_seconds: int

    def __post_init__(self) -> None:
        if not _fullmatch(BILLING_PROJECT, self.billing_project):
            raise _refuse("invalid_billing_project", "billing_project")
        if not _fullmatch(LOCATION, self.location):
            raise _refuse("invalid_location", "location")
        for name in ("max_bytes_per_query", "query_timeout_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class DryRun:
    statement_type: str
    total_bytes_processed: int


@dataclass(frozen=True)
class QueryResult:
    """What a finished query returned: the rows and the job's metadata."""

    rows: Tuple[Dict[str, Optional[str]], ...]
    job_id: str
    location: str
    total_bytes_processed: int
    total_bytes_billed: Optional[int]
    elapsed_ms: Optional[int]


# -- the token cache ----------------------------------------------------------


class AccessTokenCache:
    """Access tokens in memory, by key digest, until shortly before they expire."""

    def __init__(self, clock: Optional[Callable[[], float]] = None) -> None:
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._tokens: Dict[str, Tuple[str, float]] = {}

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._tokens.get(key)
            if entry is None:
                return None
            token, usable_until = entry
            if self._clock() >= usable_until:
                del self._tokens[key]
                return None
            return token

    def put(self, key: str, token: str, expires_in: int) -> None:
        usable_until = self._clock() + expires_in - TOKEN_REFRESH_MARGIN_SECONDS
        with self._lock:
            self._tokens[key] = (token, usable_until)

    def discard(self, key: str) -> None:
        with self._lock:
            self._tokens.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._tokens.clear()


_TOKEN_CACHE = AccessTokenCache()


# -- helpers for answers ------------------------------------------------------


def _int64(value: Any) -> Optional[int]:
    """BigQuery's JSON int64 (a digit string, sometimes a number) or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and _INT64_TEXT.fullmatch(value):
        return int(value)
    return None


def _invalid() -> WarehouseError:
    return WarehouseError(_C.RESULT_INVALID, warehouse=WAREHOUSE)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _reason_of(body: Mapping[str, Any]) -> Optional[str]:
    """The first ``error.errors[].reason`` of a Google API error body."""
    errors = _mapping(body.get("error")).get("errors")
    if isinstance(errors, list) and errors:
        reason = _mapping(errors[0]).get("reason")
        if isinstance(reason, str):
            return reason
    return None


def _error_for_reason(reason: Any, status: int = 400) -> WarehouseError:
    return error_for_status(
        status, warehouse=WAREHOUSE, vendor_code=reason, codes=REASON_CODES
    )


def decode_rows(page: Mapping[str, Any]) -> List[Dict[str, Optional[str]]]:
    """``getQueryResults`` rows as dicts of column name -> text (or None).

    Only flat, non-repeated columns are accepted; every cell must be a string
    or null, which is how BigQuery's JSON carries every scalar type.
    """
    fields = _mapping(page.get("schema")).get("fields")
    if not isinstance(fields, list) or not fields:
        raise _invalid()
    names: List[str] = []
    for field in fields:
        field = _mapping(field)
        name = field.get("name")
        if not _fullmatch(_FIELD_NAME, name) or name in names:
            raise _invalid()
        if field.get("type") in ("RECORD", "STRUCT") or field.get("mode") == "REPEATED":
            raise _invalid()
        names.append(name)
    rows = page.get("rows", [])
    if not isinstance(rows, list):
        raise _invalid()
    decoded: List[Dict[str, Optional[str]]] = []
    for row in rows:
        cells = _mapping(row).get("f")
        if not isinstance(cells, list) or len(cells) != len(names):
            raise _invalid()
        values: Dict[str, Optional[str]] = {}
        for name, cell in zip(names, cells):
            if not isinstance(cell, dict) or "v" not in cell:
                raise _invalid()
            value = cell["v"]
            if value is not None and not isinstance(value, str):
                raise _invalid()
            values[name] = value
        decoded.append(values)
    return decoded


# -- the adapter --------------------------------------------------------------


ClientFactory = Callable[[Deadline], OutboundClient]


def _default_client(deadline: Deadline) -> OutboundClient:
    return OutboundClient(deadline, warehouse=WAREHOUSE)


class BigQueryAdapter:
    """One BigQuery connection's calls, each made within the caller's Deadline.

    Call it from the warehouse executor's worker thread: every method takes
    the :class:`~.deadlines.Deadline` the executor created for the job.
    """

    def __init__(
        self,
        connection: BigQueryConnection,
        key: ServiceAccountKey,
        *,
        client_factory: Optional[ClientFactory] = None,
        token_cache: Optional[AccessTokenCache] = None,
        wall_clock: Optional[Callable[[], float]] = None,
        job_id_factory: Optional[Callable[[], str]] = None,
        sleeper: Optional[Sleeper] = None,
    ) -> None:
        self.connection = connection
        self._key = key
        self._client_factory = client_factory or _default_client
        self._tokens = token_cache if token_cache is not None else _TOKEN_CACHE
        self._wall_clock = wall_clock or time.time
        self._job_id = job_id_factory or (lambda: "experimently_" + uuid.uuid4().hex)
        self._sleeper = sleeper

    def __repr__(self) -> str:
        return f"BigQueryAdapter(billing_project={self.connection.billing_project!r})"

    # -- sign-in ---------------------------------------------------------

    def _assertion(self) -> str:
        now = int(self._wall_clock())
        claims = {
            "iss": self._key.client_email,
            "scope": SCOPE,
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + ASSERTION_LIFETIME_SECONDS,
        }
        signed: Optional[str] = None
        try:
            signed = jwt.encode(
                claims,
                self._key.private_key,
                algorithm="RS256",
                headers={"kid": self._key.private_key_id},
            )
        except Exception:
            signed = None
        if signed is None:
            # A stored key that no longer signs: nothing the caller can fix here.
            raise WarehouseError(_C.INTERNAL, warehouse=WAREHOUSE)
        return signed

    def access_token(self, client: OutboundClient) -> str:
        """A bearer token for this key: cached, or exchanged at :data:`TOKEN_URL`."""
        cached = self._tokens.get(self._key.cache_key)
        if cached is not None:
            return cached
        form = urlencode({"grant_type": GRANT_TYPE, "assertion": self._assertion()})
        response = client.request(
            "POST",
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=form.encode("ascii"),
        )
        if response.status_code != 200:
            raise self._token_error(response)
        body = _mapping(response.json())
        token = body.get("access_token")
        token_type = body.get("token_type")
        expires_in = body.get("expires_in")
        if (
            not _fullmatch(_ACCESS_TOKEN, token)
            or not isinstance(token_type, str)
            or token_type.lower() != "bearer"
            or isinstance(expires_in, bool)
            or not isinstance(expires_in, int)
            or expires_in <= 0
        ):
            raise _invalid()
        self._tokens.put(self._key.cache_key, token, expires_in)
        return token

    @staticmethod
    def _token_error(response: OutboundResponse) -> WarehouseError:
        """``key_revoked`` or ``auth_failed``, from the ``error`` field alone."""
        error: Any = None
        try:
            error = _mapping(json.loads(response.content)).get("error")
        except (ValueError, UnicodeDecodeError, RecursionError):
            error = None
        code = _C.KEY_REVOKED if error in REVOKED_KEY_ERRORS else _C.AUTH_FAILED
        return WarehouseError(
            code,
            warehouse=WAREHOUSE,
            vendor_code=error if isinstance(error, str) else None,
            http_status=response.status_code,
        )

    # -- the API ---------------------------------------------------------

    def _call(
        self,
        client: OutboundClient,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, str]] = None,
        body: Any = None,
    ) -> Mapping[str, Any]:
        token = self.access_token(client)
        response = client.request(
            method,
            API_ROOT + path,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            json_body=body,
        )
        if not 200 <= response.status_code < 300:
            if response.status_code == 401:
                # A token Google no longer accepts is not used again.
                self._tokens.discard(self._key.cache_key)
            reason: Optional[str] = None
            try:
                reason = _reason_of(_mapping(json.loads(response.content)))
            except (ValueError, UnicodeDecodeError, RecursionError):
                reason = None
            raise _error_for_reason(reason, response.status_code)
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise _invalid()
        return parsed

    def _project_path(self) -> str:
        return "/projects/" + quote(self.connection.billing_project, safe="")

    def _query_configuration(self, sql: str) -> Dict[str, Any]:
        return {
            "query": sql,
            "useLegacySql": False,
            "maximumBytesBilled": str(self.connection.max_bytes_per_query),
        }

    def dry_run(self, client: OutboundClient, sql: str) -> DryRun:
        """``jobs.insert`` with ``dryRun``: the statement type and bytes; nothing runs."""
        job = self._call(
            client,
            "POST",
            self._project_path() + "/jobs",
            body={
                "jobReference": {
                    "projectId": self.connection.billing_project,
                    "location": self.connection.location,
                },
                "configuration": {
                    "dryRun": True,
                    "labels": dict(JOB_LABELS),
                    "query": self._query_configuration(sql),
                },
            },
        )
        self._raise_job_error(job)
        query_stats = _mapping(_mapping(job.get("statistics")).get("query"))
        statement_type = query_stats.get("statementType")
        processed = _int64(query_stats.get("totalBytesProcessed"))
        if not isinstance(statement_type, str) or processed is None:
            raise _invalid()
        return DryRun(statement_type=statement_type, total_bytes_processed=processed)

    def _check_dry_run(self, dry: DryRun) -> None:
        if dry.statement_type != "SELECT":
            raise WarehouseError(_C.NOT_A_SELECT, warehouse=WAREHOUSE)
        if dry.total_bytes_processed > self.connection.max_bytes_per_query:
            raise WarehouseError(_C.BYTES_LIMIT, warehouse=WAREHOUSE)

    @staticmethod
    def _raise_job_error(job: Mapping[str, Any]) -> None:
        error = _mapping(_mapping(job.get("status")).get("errorResult"))
        if error:
            raise _error_for_reason(error.get("reason"))

    def _new_job_id(self) -> str:
        job_id = self._job_id()
        if not _fullmatch(_JOB_ID, job_id):
            raise WarehouseError(_C.INTERNAL, warehouse=WAREHOUSE)
        return job_id

    def _insert(
        self, client: OutboundClient, sql: str, job_id: str, deadline: Deadline
    ) -> None:
        # The job stops itself at the query limit, or earlier if less of the
        # operation's total is left.
        seconds = min(
            self.connection.query_timeout_seconds,
            max(1, math.floor(deadline.remaining())),
        )
        job = self._call(
            client,
            "POST",
            self._project_path() + "/jobs",
            body={
                "jobReference": {
                    "projectId": self.connection.billing_project,
                    "jobId": job_id,
                    "location": self.connection.location,
                },
                "configuration": {
                    "jobTimeoutMs": str(seconds * 1000),
                    "labels": dict(JOB_LABELS),
                    "query": self._query_configuration(sql),
                },
            },
        )
        reference = _mapping(job.get("jobReference"))
        if reference.get("jobId") != job_id:
            raise _invalid()
        self._raise_job_error(job)

    def _job_path(self, job_id: str) -> str:
        return self._project_path() + "/jobs/" + quote(job_id, safe="")

    def _poll_budget_ms(self, deadline: Deadline) -> int:
        """Milliseconds the next poll may wait; ``time_limit`` when none is left."""
        usable = deadline.remaining() - CANCEL_RESERVE_SECONDS
        if usable <= 0:
            raise WarehouseError(_C.TIME_LIMIT, warehouse=WAREHOUSE)
        return max(1, min(POLL_TIMEOUT_MS, int(usable * 1000)))

    def _wait(
        self, client: OutboundClient, job_id: str, deadline: Deadline
    ) -> List[Dict[str, Optional[str]]]:
        """Poll until the job completes; read every page of its rows."""
        path = self._project_path() + "/queries/" + quote(job_id, safe="")
        params = {"location": self.connection.location, "maxResults": "1000"}
        while True:
            page = self._call(
                client,
                "GET",
                path,
                params={**params, "timeoutMs": str(self._poll_budget_ms(deadline))},
            )
            if page.get("jobComplete") is True:
                break
            if deadline.remaining() - CANCEL_RESERVE_SECONDS <= POLL_PAUSE_SECONDS:
                raise WarehouseError(_C.TIME_LIMIT, warehouse=WAREHOUSE)
            deadline.sleep(POLL_PAUSE_SECONDS, sleeper=self._sleeper)
        rows = decode_rows(page)
        pages = 1
        token = page.get("pageToken")
        while token is not None:
            if not isinstance(token, str) or pages >= MAX_RESULT_PAGES:
                raise _invalid()
            page = self._call(
                client,
                "GET",
                path,
                params={**params, "pageToken": token, "timeoutMs": "0"},
            )
            rows.extend(decode_rows(page))
            pages += 1
            token = page.get("pageToken")
            if len(rows) > MAX_RESULT_ROWS:
                raise _invalid()
        return rows

    def _cancel(self, client: OutboundClient, job_id: str, deadline: Deadline) -> None:
        """Ask BigQuery to cancel the job; best effort, never raises."""
        failure: Optional[WarehouseError] = None
        own: Optional[OutboundClient] = None
        try:
            target = client
            if deadline.remaining() < 1.0:
                # The reserve was used up by a slow answer: the cancel gets
                # its own short budget rather than not being sent.
                own = self._client_factory(Deadline(CANCEL_RESERVE_SECONDS))
                target = own
            self._call(
                target,
                "POST",
                self._job_path(job_id) + "/cancel",
                params={"location": self.connection.location},
            )
        except WarehouseError as exc:
            failure = exc
        except Exception:
            failure = WarehouseError(_C.INTERNAL, warehouse=WAREHOUSE)
        finally:
            if own is not None:
                own.close()
        if failure is not None:
            log_warehouse_error(sanitised(failure), event="bigquery cancel failed")

    def _job_statistics(
        self, client: OutboundClient, job_id: str
    ) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        """(bytes processed, bytes billed, elapsed ms) from ``jobs.get``."""
        job = self._call(
            client,
            "GET",
            self._job_path(job_id),
            params={"location": self.connection.location},
        )
        self._raise_job_error(job)
        statistics = _mapping(job.get("statistics"))
        query_stats = _mapping(statistics.get("query"))
        start = _int64(statistics.get("startTime"))
        end = _int64(statistics.get("endTime"))
        elapsed = (
            end - start
            if start is not None and end is not None and end >= start
            else None
        )
        return (
            _int64(query_stats.get("totalBytesProcessed")),
            _int64(query_stats.get("totalBytesBilled")),
            elapsed,
        )

    # -- operations ------------------------------------------------------

    def run_query(self, query: BuiltQuery, deadline: Deadline) -> QueryResult:
        """Dry-run, run and read one generated statement, within ``deadline``."""
        if not isinstance(query, BuiltQuery) or query.dialect != WAREHOUSE:
            raise WarehouseError(_C.INTERNAL, warehouse=WAREHOUSE)
        with self._client_factory(deadline) as client:
            dry = self.dry_run(client, query.sql)
            self._check_dry_run(dry)
            # The id is ours before the job exists, so a job whose insert
            # answer was lost can still be cancelled.
            job_id = self._new_job_id()
            failure: Optional[WarehouseError] = None
            rows: List[Dict[str, Optional[str]]] = []
            try:
                self._insert(client, query.sql, job_id, deadline)
                rows = self._wait(client, job_id, deadline)
            except WarehouseError as exc:
                failure = exc
            if failure is not None:
                # The job may still be running: stop it unless BigQuery itself
                # reported how it ended.
                if failure.code in (
                    _C.TIME_LIMIT,
                    _C.UNREACHABLE,
                    _C.RESULT_INVALID,
                    _C.INTERNAL,
                ):
                    self._cancel(client, job_id, deadline)
                raise sanitised(failure)
            processed, billed, elapsed = self._job_statistics(client, job_id)
        return QueryResult(
            rows=tuple(rows),
            job_id=job_id,
            location=self.connection.location,
            total_bytes_processed=(
                processed if processed is not None else dry.total_bytes_processed
            ),
            total_bytes_billed=billed,
            elapsed_ms=elapsed,
        )

    def check_connection(self, deadline: Deadline) -> DryRun:
        """Sign in and dry-run a trivial SELECT in the billing project.

        Proves the key signs in, the service account may create jobs in the
        billing project, and the location exists.  Nothing runs or bills.
        """
        with self._client_factory(deadline) as client:
            dry = self.dry_run(client, CONNECTION_TEST_SQL)
            self._check_dry_run(dry)
            return dry

    def table_columns(
        self, table: Tuple[str, ...], deadline: Deadline
    ) -> Tuple[Tuple[str, str], ...]:
        """``tables.get``: the top-level column names and types of a table or view.

        The reference is checked against the BigQuery identifier rules before
        anything is sent (``WarehouseQueryRefused``, ``invalid_identifier``).
        Reads metadata only; no query runs.
        """
        project, dataset, name = validate_table_parts(BIGQUERY, table)
        path = (
            "/projects/"
            + quote(project, safe="")
            + "/datasets/"
            + quote(dataset, safe="")
            + "/tables/"
            + quote(name, safe="")
        )
        with self._client_factory(deadline) as client:
            resource = self._call(client, "GET", path)
        fields = _mapping(resource.get("schema")).get("fields")
        if not isinstance(fields, list):
            raise _invalid()
        columns: List[Tuple[str, str]] = []
        for field in fields:
            field = _mapping(field)
            column = field.get("name")
            kind = field.get("type")
            if not _fullmatch(_FIELD_NAME, column) or not _fullmatch(_TYPE_NAME, kind):
                raise _invalid()
            columns.append((column, kind))
        return tuple(columns)


__all__ = [
    "API_ROOT",
    "JOB_LABELS",
    "REASON_CODES",
    "TOKEN_URL",
    "AccessTokenCache",
    "BigQueryAdapter",
    "BigQueryConfigRefused",
    "BigQueryConnection",
    "DryRun",
    "QueryResult",
    "ServiceAccountKey",
    "check_token_endpoint",
    "decode_rows",
    "parse_service_account_json",
]
