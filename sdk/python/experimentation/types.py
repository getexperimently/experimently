"""Public data types returned by :class:`experimentation.ExperimentationClient`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = ["Assignment", "BatchResult", "ExperimentationError", "FlagEvaluation"]


class ExperimentationError(Exception):
    """Raised by ``get_assignment``, ``get_feature_flag``, ``get_all_flags`` and
    ``get_assignments`` when the API call fails.

    Attributes:
        status: HTTP status code of the failed response, or ``None`` for
            network errors and timeouts.
        body: Raw response body (text) when a response was received.
    """

    def __init__(
        self,
        message: str,
        status: Optional[int] = None,
        body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


@dataclass(frozen=True)
class Assignment:
    """A user's (sticky) variant assignment, from ``POST /api/v1/tracking/assign``."""

    experiment_key: str
    user_id: str
    variant_id: Optional[str]
    variant_name: str
    is_control: bool
    configuration: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class FlagEvaluation:
    """A server-side flag decision, from ``GET /api/v1/feature-flags/evaluate/{key}``."""

    key: str
    enabled: bool
    config: Any = None


@dataclass
class BatchResult:
    """Aggregated outcome of ``track_batch`` (summed over all 100-event chunks)."""

    success_count: int = 0
    failure_count: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """``True`` when no event failed."""
        return self.failure_count == 0
