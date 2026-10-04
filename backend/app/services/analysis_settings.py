"""Which correction method and confidence level judge an experiment's results (#580).

Each experiment stores a ``correction_method`` and a ``confidence_level``
(Benjamini-Hochberg at 0.95 unless its creator chose otherwise). A request that
names its own value -- ``?correction_method=`` or ``?confidence_level=`` on
``/results/{id}`` or ``/results/{id}/sample-size`` -- uses that value for that
request; otherwise the stored one is used. ``/results/{id}`` resolves before it
builds its cache key, so an answer computed under one setting is never served
for another.
"""

from __future__ import annotations

from typing import Any, NamedTuple, Optional

from backend.app.services.sufficient_stats_analysis import (
    CORRECTION_METHODS,
    UnknownCorrectionMethodError,
)


class AnalysisSettings(NamedTuple):
    """The level and method one results computation uses."""

    confidence_level: float
    correction_method: str


def resolve_analysis_settings(
    experiment: Any,
    confidence_level: Optional[float] = None,
    correction_method: Optional[str] = None,
) -> AnalysisSettings:
    """The request's value where it names one, otherwise the experiment's own.

    Args:
        experiment: an ``Experiment`` (or any object with the two attributes).
        confidence_level: the request's level, or None for the stored one.
        correction_method: the request's method, or None for the stored one.

    Raises:
        UnknownCorrectionMethodError: the method that would be used is not one
            the analysis knows. The database's check constraint refuses such a
            stored value, so this means a defect, and it surfaces as a 500.
    """
    level = (
        confidence_level
        if confidence_level is not None
        else float(experiment.confidence_level)
    )
    method = (
        correction_method
        if correction_method is not None
        else experiment.correction_method
    )
    # A ``CorrectionMethod`` enum member is compared by its value.
    method = getattr(method, "value", method)
    if method not in CORRECTION_METHODS:
        raise UnknownCorrectionMethodError(method)
    return AnalysisSettings(confidence_level=level, correction_method=method)
