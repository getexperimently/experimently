"""
Whether each statistical analysis's numbers are established or still beta.

This is not ``x-stability`` (docs/api/stability.md), which is about the *shape*
of a response.  ``analysis_status`` is about whether the *numbers* are right:

* ``"ga"``   -- the analysis is established; ``analysis_notice`` is ``None``.
* ``"beta"`` -- the numbers are still being corrected or part of the analysis
  is not computed; ``analysis_notice`` says what, in a sentence a reader can act
  on.

``analysis_notice`` is non-null exactly when the status is ``"beta"``.  A
response takes its posture from this one table, and the tests read the table
rather than retyping it.

The module is in ``core`` so that schemas and routes can import it without an
import cycle through ``backend.app.services``.
"""

from typing import Dict, Literal, Optional, Tuple

AnalysisStatus = Literal["ga", "beta"]

#: The sequential analysis is beta until its confidence sequence is corrected
#: (#231).  It never computes a planned-looks table, so ``alpha_spending`` is
#: always empty (#232).
SEQUENTIAL_NOTICE = (
    "Beta: the stop/continue decision is mSPRT alone, at the significance "
    "level shown by the boundary (1/alpha). alpha_spending is always empty: "
    "the planned-looks (alpha-spending) table is not computed yet. The "
    "confidence sequence is being corrected (#231)."
)

#: analysis -> (status, notice).  The notice is None exactly when status is ga.
ANALYSIS_STATUS: Dict[str, Tuple[AnalysisStatus, Optional[str]]] = {
    "sequential": ("beta", SEQUENTIAL_NOTICE),
}


def analysis_posture(analysis: str) -> Tuple[AnalysisStatus, Optional[str]]:
    """Return ``(analysis_status, analysis_notice)`` for *analysis*.

    Raises ``KeyError`` for an analysis the table does not list, so a new
    analysis cannot silently default to ``ga``.
    """
    return ANALYSIS_STATUS[analysis]
