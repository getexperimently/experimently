"""The estimator a warehouse run computes proportion results with.

Warehouse analysis does not have a statistics engine of its own.  A
proportion metric's result comes from the function ``/results`` uses,
:func:`backend.app.services.sufficient_stats_analysis.binomial_metric_result`,
called with the counts the warehouse returned: units and converting units per
variant.  On identical counts the two paths give identical numbers.  Nothing
here computes a p-value, an interval or an effect size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, Sequence
from uuid import UUID

from backend.app.services.sufficient_stats_analysis import binomial_metric_result

#: ``binomial_metric_result(variants, alpha, correction_method, *, metric)``.
BinomialEstimator = Callable[..., Dict[str, Any]]


@dataclass(frozen=True)
class VariantRef:
    """An experiment variant as the estimator needs it."""

    id: UUID
    name: str
    is_control: bool


@dataclass(frozen=True)
class MetricRef:
    """The metric's identity, which the result carries.

    ``metric_type`` is ``conversion``: a warehouse proportion metric is the
    share of units with at least one event, what ``/results`` calls a
    conversion metric.
    """

    id: UUID
    name: str
    is_primary: bool
    metric_type: str = "conversion"


@dataclass(frozen=True)
class VariantCounts:
    variant: VariantRef
    n: int
    n_converted: int


def _json_safe(value: Any) -> Any:
    """The result as JSON values: tuples as lists, UUIDs as text, and a
    non-finite float (which JSON cannot hold) as null."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def proportion_result(
    counts: Sequence[VariantCounts],
    *,
    alpha: float,
    correction_method: str,
    metric: MetricRef,
    estimator: BinomialEstimator = binomial_metric_result,
) -> Dict[str, Any]:
    """The ``MetricResult``-shaped result for the warehouse's counts, as JSON.

    ``counts`` holds every experiment variant, the control first.
    """
    variants = [(c.variant, c.n, c.n_converted) for c in counts]
    return _json_safe(estimator(variants, alpha, correction_method, metric=metric))


__all__ = [
    "BinomialEstimator",
    "MetricRef",
    "VariantCounts",
    "VariantRef",
    "binomial_metric_result",
    "proportion_result",
]
