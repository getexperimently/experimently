"""
Whether each analysis's numbers can be relied on: ``ga`` or ``beta``.

This is the one table behind the ``analysis_status`` and ``analysis_notice``
fields of the analysis responses.  It is about the *numbers*, and is separate
from a route's ``x-stability`` (``docs/api/stability.md``), which is about the
*shape* of the request and response.

* ``ga``: the analysis computes what its fields say; ``analysis_notice`` is null.
* ``beta``: part of the analysis is not computed yet, or not computed from what
  its name says; ``analysis_notice`` says which part, and links the issue.

A notice is present exactly when the status is ``beta``: the table refuses any
other combination when this module is imported.  Responses read the table when
they are built, never a copy of it, so changing an entry here changes every
response that carries it.
"""

from dataclasses import dataclass
from typing import Dict, Literal, Optional

AnalysisStatusValue = Literal["ga", "beta"]

GA: AnalysisStatusValue = "ga"
BETA: AnalysisStatusValue = "beta"

_ISSUES = "https://github.com/getexperimently/experimently/issues"


@dataclass(frozen=True)
class AnalysisLabel:
    """The status of one analysis and, when it is beta, why."""

    status: AnalysisStatusValue
    notice: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in (GA, BETA):
            raise ValueError(
                f"analysis status must be 'ga' or 'beta', not {self.status!r}"
            )
        if (self.status == BETA) != bool(self.notice):
            raise ValueError(
                "an analysis notice is required when the status is 'beta' "
                "and must be absent when it is 'ga'"
            )


#: Keyed by the analysis, not the route: ``interactions`` labels
#: ``GET /interactions/{a}/{b}``, ``novelty`` labels ``.../novelty`` and
#: ``cuped`` labels ``GET /results/{id}/cuped``.
ANALYSIS_STATUS: Dict[str, AnalysisLabel] = {
    "cuped": AnalysisLabel(
        BETA,
        "Beta: the covariate is not yet a pre-experiment metric, so "
        "variance_reduction_pct is close to 0 and the adjusted estimate is "
        "close to the unadjusted one. "
        f"{_ISSUES}/217",
    ),
    "interactions": AnalysisLabel(
        BETA,
        "Beta: only the overlap between the two experiments' users is measured. "
        "The interaction, novelty and SUTVA analyses are not computed yet, so "
        "interaction_result, novelty_result and sutva_result are null and "
        "overall_risk reflects the overlap alone. "
        f"{_ISSUES}/219",
    ),
    "novelty": AnalysisLabel(
        BETA,
        "Beta: novelty is not computed yet, so has_novelty and decline_rate are "
        "null. A null has_novelty means not computed, not no novelty. "
        f"{_ISSUES}/219",
    ),
}


def analysis_label(analysis: str) -> AnalysisLabel:
    """The current label of ``analysis``; a ``KeyError`` for an unknown one."""
    return ANALYSIS_STATUS[analysis]


def analysis_status(analysis: str) -> AnalysisStatusValue:
    """``"ga"`` or ``"beta"`` for ``analysis``, read from the table now."""
    return analysis_label(analysis).status


def analysis_notice(analysis: str) -> Optional[str]:
    """The notice for ``analysis``: text when it is beta, ``None`` when ga."""
    return analysis_label(analysis).notice
