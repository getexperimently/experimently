"""Synchronous client for the Experimentation Platform public API.

* Dependency-free: HTTP goes through :mod:`urllib` from the standard library
  (or any injected :class:`~experimentation.transport.Transport`).
* **The server decides.** Experiment assignment and flag evaluation come from
  ``POST /api/v1/tracking/assign`` and
  ``GET /api/v1/feature-flags/evaluate/{key}``; nothing is bucketed locally.
* Successful assignments/evaluations are cached per user + key for
  ``cache_ttl_seconds``; failures are never cached.
* ``get_assignment``/``get_feature_flag``/``get_all_flags``/``get_assignments``
  raise :class:`~experimentation.ExperimentationError`; the convenience
  wrappers ``get_variant``/``is_feature_enabled`` swallow it and return a
  default; ``track``/``track_batch`` never raise.
* Safe to share between threads.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union
from urllib.parse import quote, urlencode

from .cache import UserKeyCache
from .transport import Response, Transport, UrllibTransport
from .types import Assignment, BatchResult, ExperimentationError, FlagEvaluation
from .version import __version__

__all__ = ["BATCH_LIMIT", "ExperimentationClient"]

logger = logging.getLogger(__name__)

#: Maximum events per ``POST /api/v1/tracking/batch`` request.
BATCH_LIMIT = 100
#: Upper bound honoured for a ``Retry-After`` header on 429.
MAX_RETRY_AFTER_SECONDS = 5.0
#: Wait used when a 429 carries no (parseable) ``Retry-After`` header.
DEFAULT_RETRY_AFTER_SECONDS = 1.0

_USER_AGENT = f"experimentation-sdk-python/{__version__}"


def _iso_timestamp(value: Union[datetime, str, None]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return _iso_timestamp(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _retry_after_seconds(response: Response) -> float:
    header = response.header("Retry-After")
    seconds = DEFAULT_RETRY_AFTER_SECONDS
    if header is not None:
        try:
            seconds = float(header.strip())
        except ValueError:
            seconds = DEFAULT_RETRY_AFTER_SECONDS
    return max(0.0, min(seconds, MAX_RETRY_AFTER_SECONDS))


class ExperimentationClient:
    """Client for experiments, feature flags and event tracking.

    Args:
        api_url: Backend origin, e.g. ``"http://localhost:8000"``. The client
            appends ``/api/v1/...``; a trailing slash is ignored.
        api_key: Sent as ``X-API-Key`` on every request.
        timeout_seconds: Per-request timeout (default 5 s).
        cache_ttl_seconds: How long a successful assignment/evaluation is
            reused for the same user + key (default 300 s).
        default_variant: What ``get_variant`` returns when assignment fails
            (default ``"control"``).
        transport: Optional :class:`~experimentation.transport.Transport`
            (tests use :class:`experimentation.testing.FakeTransport`).
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        timeout_seconds: float = 5.0,
        cache_ttl_seconds: float = 300,
        default_variant: str = "control",
        transport: Optional[Transport] = None,
    ) -> None:
        if not api_url:
            raise ValueError("api_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.default_variant = default_variant
        self._api_key = api_key
        self._transport: Transport = transport if transport is not None else UrllibTransport()
        self._assignments: UserKeyCache[Assignment] = UserKeyCache(cache_ttl_seconds)
        self._flags: UserKeyCache[FlagEvaluation] = UserKeyCache(cache_ttl_seconds)
        self._sleep = time.sleep
        self._headers: Dict[str, str] = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }

    # ------------------------------------------------------------------ HTTP

    def _send(self, method: str, url: str, data: Optional[bytes]) -> Response:
        try:
            return self._transport.send(method, url, self._headers, data, self.timeout_seconds)
        except ExperimentationError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise any transport failure
            raise ExperimentationError(f"{method} {url} failed: {exc}") from exc

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Mapping[str, Any]] = None,
        query: Optional[Mapping[str, str]] = None,
    ) -> Any:
        """Perform one API call and return the decoded JSON body (``None`` if empty).

        Retries exactly once on 429, sleeping for ``Retry-After`` (capped at
        :data:`MAX_RETRY_AFTER_SECONDS`). Raises :class:`ExperimentationError`
        for any non-2xx response, network failure or undecodable body.
        """
        url = self.api_url + path
        if query:
            url += "?" + urlencode(query, quote_via=quote)
        data = None if body is None else json.dumps(body, default=_json_default).encode("utf-8")

        response = self._send(method, url, data)
        if response.status == 429:
            wait = _retry_after_seconds(response)
            logger.debug("429 from %s %s; retrying once after %.1fs", method, path, wait)
            self._sleep(wait)
            response = self._send(method, url, data)

        if response.status < 200 or response.status >= 300:
            raise ExperimentationError(
                f"{method} {path} failed with HTTP {response.status}",
                status=response.status,
                body=response.text(),
            )
        if not response.body:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ExperimentationError(
                f"{method} {path} returned a non-JSON body",
                status=response.status,
                body=response.text(),
            ) from exc

    # ----------------------------------------------------------- experiments

    def get_assignment(
        self,
        experiment_key: str,
        user_id: str,
        user_attributes: Optional[Mapping[str, Any]] = None,
    ) -> Assignment:
        """Assign ``user_id`` to ``experiment_key`` via ``POST /api/v1/tracking/assign``.

        Sticky on the server and cached here per user + key. ``user_attributes``
        is sent as ``context`` (used by targeting rules). Raises
        :class:`ExperimentationError` (``status == 404`` when the experiment is
        not ACTIVE or unknown).
        """
        cached = self._assignments.get(user_id, experiment_key)
        if cached is not None:
            return cached

        body: Dict[str, Any] = {"experiment_key": experiment_key, "user_id": user_id}
        if user_attributes is not None:
            body["context"] = dict(user_attributes)
        data = self._request("POST", "/api/v1/tracking/assign", body=body)

        if not isinstance(data, dict) or not isinstance(data.get("variant_name"), str):
            raise ExperimentationError(
                "POST /api/v1/tracking/assign returned an unexpected body",
                status=200,
                body=json.dumps(data),
            )
        assignment = Assignment(
            experiment_key=str(data.get("experiment_key") or experiment_key),
            user_id=str(data.get("user_id") or user_id),
            variant_id=None if data.get("variant_id") is None else str(data["variant_id"]),
            variant_name=data["variant_name"],
            is_control=bool(data.get("is_control", False)),
            configuration=data.get("configuration"),
        )
        self._assignments.set(user_id, experiment_key, assignment)
        return assignment

    def get_variant(
        self,
        experiment_key: str,
        user_id: str,
        user_attributes: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """``get_assignment(...).variant_name``, or ``default_variant`` on any failure."""
        try:
            return self.get_assignment(experiment_key, user_id, user_attributes).variant_name
        except ExperimentationError as exc:
            logger.warning("get_variant(%s, %s) failed: %s", experiment_key, user_id, exc)
            return self.default_variant

    def get_assignments(self, user_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        """The user's assignments from ``GET /api/v1/tracking/assignments/{user_id}`` (server-side, not cached)."""
        data = self._request(
            "GET",
            f"/api/v1/tracking/assignments/{quote(user_id, safe='')}",
            query={"active_only": "true" if active_only else "false"},
        )
        return list(data) if isinstance(data, list) else []

    # ---------------------------------------------------------- feature flags

    def get_feature_flag(self, flag_key: str, user_id: str) -> FlagEvaluation:
        """Evaluate one flag via ``GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…``.

        Cached per user + key. Raises :class:`ExperimentationError`
        (``status == 404`` when the flag is not ACTIVE or unknown).
        """
        cached = self._flags.get(user_id, flag_key)
        if cached is not None:
            return cached

        data = self._request(
            "GET",
            f"/api/v1/feature-flags/evaluate/{quote(flag_key, safe='')}",
            query={"user_id": user_id},
        )
        if not isinstance(data, dict):
            raise ExperimentationError(
                "GET /api/v1/feature-flags/evaluate returned an unexpected body",
                status=200,
                body=json.dumps(data),
            )
        evaluation = FlagEvaluation(
            key=str(data.get("key") or flag_key),
            enabled=bool(data.get("enabled", False)),
            config=data.get("config"),
        )
        self._flags.set(user_id, flag_key, evaluation)
        return evaluation

    def is_feature_enabled(self, flag_key: str, user_id: str) -> bool:
        """``get_feature_flag(...).enabled``, or ``False`` on any failure."""
        try:
            return self.get_feature_flag(flag_key, user_id).enabled
        except ExperimentationError as exc:
            logger.warning("is_feature_enabled(%s, %s) failed: %s", flag_key, user_id, exc)
            return False

    def get_all_flags(self, user_id: str) -> Dict[str, bool]:
        """All active flags for the user from ``GET /api/v1/feature-flags/user/{user_id}`` (not cached)."""
        data = self._request("GET", f"/api/v1/feature-flags/user/{quote(user_id, safe='')}")
        if not isinstance(data, dict):
            return {}
        return {str(key): bool(value) for key, value in data.items()}

    # --------------------------------------------------------------- tracking

    @staticmethod
    def _event_body(
        user_id: str,
        event_name: str,
        event_value: Optional[float],
        properties: Optional[Mapping[str, Any]],
        event_type: Optional[str],
        timestamp: Union[datetime, str, None],
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "event_type": event_type or event_name,
            "event_name": event_name,
            "user_id": user_id,
        }
        if event_value is not None:
            body["value"] = float(event_value)
        if properties is not None:
            body["metadata"] = dict(properties)
        stamp = _iso_timestamp(timestamp)
        if stamp is not None:
            body["timestamp"] = stamp
        return body

    def track(
        self,
        user_id: str,
        event_name: str,
        event_value: Optional[float] = None,
        properties: Optional[Mapping[str, Any]] = None,
        experiment_key: Optional[str] = None,
        feature_flag_key: Optional[str] = None,
        event_type: Optional[str] = None,
        timestamp: Union[datetime, str, None] = None,
    ) -> bool:
        """Record an event. Never raises.

        * With ``experiment_key`` and/or ``feature_flag_key``: one
          ``POST /api/v1/tracking/track``.
        * Without a key: one ``POST /api/v1/tracking/batch`` (chunked at 100)
          containing one entry per cached assignment (``experiment_key``) plus
          one per cached evaluated flag (``feature_flag_key``) for this user.
          If nothing is cached for the user, nothing is sent and ``False`` is
          returned.

        ``event_type`` defaults to ``event_name``. Returns ``True`` only when
        the server accepted the event(s).
        """
        try:
            base = self._event_body(user_id, event_name, event_value, properties, event_type, timestamp)
            if experiment_key or feature_flag_key:
                body = dict(base)
                if experiment_key:
                    body["experiment_key"] = experiment_key
                if feature_flag_key:
                    body["feature_flag_key"] = feature_flag_key
                self._request("POST", "/api/v1/tracking/track", body=body)
                return True

            events: List[Dict[str, Any]] = [
                dict(base, experiment_key=assignment.experiment_key)
                for assignment in self.cached_assignments(user_id)
            ]
            events.extend(dict(base, feature_flag_key=flag.key) for flag in self.cached_flags(user_id))
            if not events:
                logger.debug("track(%s, %s): nothing cached for user; nothing sent", user_id, event_name)
                return False
            return self.track_batch(events).ok
        except Exception as exc:  # noqa: BLE001 - fire-and-forget
            logger.warning("track(%s, %s) failed: %s", user_id, event_name, exc)
            return False

    def track_batch(self, events: Iterable[Mapping[str, Any]]) -> BatchResult:
        """Send raw track bodies via ``POST /api/v1/tracking/batch`` in chunks of 100. Never raises.

        Each event is a dict with the ``/tracking/track`` fields
        (``event_type``/``event_name``, ``user_id``, ``experiment_key`` or
        ``feature_flag_key``, optional ``value``, ``metadata``, ``timestamp``).
        ``event_type`` defaults to ``event_name`` when missing. A chunk that
        fails outright counts every one of its events as a failure; error
        ``index`` values are absolute positions in ``events``.
        """
        result = BatchResult()
        normalised = [self._normalise_event(event) for event in events]
        for start in range(0, len(normalised), BATCH_LIMIT):
            chunk = normalised[start : start + BATCH_LIMIT]
            try:
                data = self._request("POST", "/api/v1/tracking/batch", body={"events": chunk})
            except Exception as exc:  # noqa: BLE001 - never raise
                logger.warning("track_batch chunk starting at %d failed: %s", start, exc)
                result.failure_count += len(chunk)
                result.errors.append(
                    {
                        "index": start,
                        "count": len(chunk),
                        "status": getattr(exc, "status", None),
                        "error": str(exc),
                    }
                )
                continue
            if isinstance(data, dict):
                result.success_count += int(data.get("success_count") or 0)
                result.failure_count += int(data.get("failure_count") or 0)
                for error in data.get("errors") or []:
                    entry = dict(error) if isinstance(error, Mapping) else {"error": error}
                    if isinstance(entry.get("index"), int):
                        entry["index"] += start
                    result.errors.append(entry)
            else:
                result.success_count += len(chunk)
        return result

    @staticmethod
    def _normalise_event(event: Mapping[str, Any]) -> Dict[str, Any]:
        body = dict(event)
        if not body.get("event_type") and body.get("event_name"):
            body["event_type"] = body["event_name"]
        if isinstance(body.get("timestamp"), datetime):
            body["timestamp"] = _iso_timestamp(body["timestamp"])
        return body

    # ------------------------------------------------------------------ cache

    def cached_assignments(self, user_id: str) -> List[Assignment]:
        """Successful, unexpired assignments cached for the user (what ``track`` fans out to)."""
        return [assignment for _, assignment in self._assignments.entries(user_id)]

    def cached_flags(self, user_id: str) -> List[FlagEvaluation]:
        """Successful, unexpired flag evaluations cached for the user."""
        return [evaluation for _, evaluation in self._flags.entries(user_id)]

    def clear_cache(self) -> None:
        """Drop every cached assignment and evaluation."""
        self._assignments.clear()
        self._flags.clear()
