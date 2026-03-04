"""
ExperimentationProvider — OpenFeature AbstractProvider implementation.

Performs local, consistent-hash-based flag evaluation using the same MD5
algorithm as the Go, Java, and TypeScript SDKs.

Lifecycle:
  1. Construct with API key (and optional base_url / cache_ttl / timeout).
  2. The OpenFeature SDK calls initialize(evaluation_context) on set_provider().
  3. resolve_*_details() methods evaluate flags from the in-memory cache.
  4. The OpenFeature SDK calls shutdown() when the provider is replaced.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, List, Optional, Union

import requests
from requests.exceptions import RequestException, Timeout

from openfeature.evaluation_context import EvaluationContext
from openfeature.exception import (
    ErrorCode,
    FlagNotFoundError,
    GeneralError,
    TypeMismatchError,
)
from openfeature.flag_evaluation import FlagResolutionDetails, Reason
from openfeature.hook import Hook
from openfeature.provider.metadata import Metadata
from openfeature.provider.provider import AbstractProvider

from .cache import FlagCache
from .evaluator import LocalEvaluator
from .types import FeatureFlagDefinition

logger = logging.getLogger(__name__)


class ExperimentationProvider(AbstractProvider):
    """
    OpenFeature provider for the Experimentation Platform.

    Evaluates feature flags locally using the same MD5-based consistent hash
    algorithm as the Go, Java, and TypeScript SDKs, ensuring identical user
    assignments across all clients.

    Example::

        from openfeature import api
        from experimentation_openfeature import ExperimentationProvider

        api.set_provider(ExperimentationProvider(api_key="your-api-key"))
        client = api.get_client()
        enabled = client.get_boolean_value("dark-mode", False)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        cache_ttl: int = 300,
        timeout: int = 10,
        *,
        _session: Optional[requests.Session] = None,
    ) -> None:
        """
        Create a new ExperimentationProvider.

        Args:
            api_key:    API key sent in the X-API-Key header.
            base_url:   Base URL of the platform API (no trailing slash).
            cache_ttl:  Seconds the flag cache is valid. Defaults to 300 (5 min).
            timeout:    HTTP request timeout in seconds. Defaults to 10.
            _session:   Optional requests.Session for testing (dependency injection).
        """
        if not api_key:
            raise ValueError("ExperimentationProvider: api_key is required")

        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._cache = FlagCache(ttl=cache_ttl)
        self._evaluator = LocalEvaluator()
        self._refresh_lock = threading.Lock()

        # Use injected session (tests) or create a new persistent session.
        if _session is not None:
            self._session = _session
        else:
            self._session = requests.Session()
            self._session.headers.update({
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            })

    # ------------------------------------------------------------------
    # AbstractProvider interface
    # ------------------------------------------------------------------

    def get_metadata(self) -> Metadata:
        return Metadata("experimentation-platform-provider")

    def get_provider_hooks(self) -> List[Hook]:
        return []

    def initialize(self, evaluation_context: Optional[EvaluationContext] = None) -> None:
        """Fetch all flags and warm the cache. Called by the OpenFeature SDK."""
        self._refresh_flags()

    def shutdown(self) -> None:
        """Release resources. Called by the OpenFeature SDK on provider change."""
        self._cache.clear()
        self._session.close()

    # ------------------------------------------------------------------
    # Flag resolution
    # ------------------------------------------------------------------

    def resolve_boolean_details(
        self,
        flag_key: str,
        default_value: bool,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[bool]:
        result = self._resolve(flag_key, evaluation_context)
        value = result.value
        if not isinstance(value, bool):
            # Treat "enabled" (True/False from a no-variant flag) as bool-compatible.
            value = bool(value) if value is not None else default_value
        return FlagResolutionDetails(
            value=value,
            reason=result.reason,
            variant=result.variant,
            error_code=result.error_code,
            error_message=result.error_message,
        )

    def resolve_string_details(
        self,
        flag_key: str,
        default_value: str,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[str]:
        result = self._resolve(flag_key, evaluation_context)
        if result.error_code is not None:
            return FlagResolutionDetails(
                value=default_value,
                reason=result.reason,
                error_code=result.error_code,
                error_message=result.error_message,
            )
        if not isinstance(result.value, str):
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.TYPE_MISMATCH,
                error_message=f'Flag "{flag_key}" value is not a string',
            )
        return FlagResolutionDetails(
            value=result.value,
            reason=result.reason,
            variant=result.variant,
        )

    def resolve_integer_details(
        self,
        flag_key: str,
        default_value: int,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[int]:
        result = self._resolve(flag_key, evaluation_context)
        if result.error_code is not None:
            return FlagResolutionDetails(
                value=default_value,
                reason=result.reason,
                error_code=result.error_code,
                error_message=result.error_message,
            )
        if not isinstance(result.value, int) or isinstance(result.value, bool):
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.TYPE_MISMATCH,
                error_message=f'Flag "{flag_key}" value is not an integer',
            )
        return FlagResolutionDetails(
            value=result.value,
            reason=result.reason,
            variant=result.variant,
        )

    def resolve_float_details(
        self,
        flag_key: str,
        default_value: float,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[float]:
        result = self._resolve(flag_key, evaluation_context)
        if result.error_code is not None:
            return FlagResolutionDetails(
                value=default_value,
                reason=result.reason,
                error_code=result.error_code,
                error_message=result.error_message,
            )
        if not isinstance(result.value, (int, float)) or isinstance(result.value, bool):
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.TYPE_MISMATCH,
                error_message=f'Flag "{flag_key}" value is not a float',
            )
        return FlagResolutionDetails(
            value=float(result.value),
            reason=result.reason,
            variant=result.variant,
        )

    def resolve_object_details(
        self,
        flag_key: str,
        default_value: Union[dict, list],
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[Union[dict, list]]:
        result = self._resolve(flag_key, evaluation_context)
        if result.error_code is not None:
            return FlagResolutionDetails(
                value=default_value,
                reason=result.reason,
                error_code=result.error_code,
                error_message=result.error_message,
            )
        if not isinstance(result.value, (dict, list)):
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.TYPE_MISMATCH,
                error_message=f'Flag "{flag_key}" value is not a dict or list',
            )
        return FlagResolutionDetails(
            value=result.value,
            reason=result.reason,
            variant=result.variant,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve(
        self, flag_key: str, evaluation_context: Optional[EvaluationContext]
    ) -> "_InternalResult":
        """Common resolution logic shared by all resolve_*_details methods."""
        self._ensure_fresh_cache()

        flag = self._cache.get(flag_key)
        if flag is None:
            return _InternalResult(
                value=None,
                variant=None,
                reason=Reason.DEFAULT,
                error_code=ErrorCode.FLAG_NOT_FOUND,
                error_message=f'Flag "{flag_key}" not found',
            )

        user_id = ""
        if evaluation_context is not None and evaluation_context.targeting_key:
            user_id = evaluation_context.targeting_key

        cached_warm = self._cache.is_valid()
        eval_result = self._evaluator.evaluate(flag, user_id)

        return _InternalResult(
            value=eval_result.value,
            variant=eval_result.variant,
            reason=Reason.CACHED if cached_warm else Reason.STATIC,
        )

    def _ensure_fresh_cache(self) -> None:
        """Refresh the flag cache if it has expired (with double-checked locking)."""
        if self._cache.is_valid():
            return
        with self._refresh_lock:
            # Re-check after acquiring the lock (another thread may have refreshed).
            if not self._cache.is_valid():
                try:
                    self._refresh_flags()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Flag cache refresh failed: %s", exc)

    def _refresh_flags(self) -> None:
        """Fetch all flags from the platform API and update the cache."""
        url = f"{self._base_url}/api/v1/openfeature/flags"
        try:
            response = self._session.get(
                url,
                headers={"X-API-Key": self._api_key},
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            flags = [
                FeatureFlagDefinition.from_dict(f) for f in data.get("flags", [])
            ]
            self._cache.update(flags)
            logger.debug("Loaded %d flags from %s", len(flags), url)
        except Timeout as exc:
            raise GeneralError(
                error_message=f"Timeout fetching flags from {url}"
            ) from exc
        except RequestException as exc:
            raise GeneralError(
                error_message=f"HTTP error fetching flags: {exc}"
            ) from exc


class _InternalResult:
    """Lightweight internal resolution result (not the public FlagResolutionDetails)."""

    __slots__ = ("value", "variant", "reason", "error_code", "error_message")

    def __init__(
        self,
        value: Any,
        variant: Optional[str],
        reason: Union[str, Reason],
        error_code: Optional[ErrorCode] = None,
        error_message: Optional[str] = None,
    ) -> None:
        self.value = value
        self.variant = variant
        self.reason = reason
        self.error_code = error_code
        self.error_message = error_message
