"""
Cross-experiment interaction detection endpoints (Issue #25).

GET /api/v1/interactions/scan                     — scan all active experiments
GET /api/v1/interactions/{exp_a_id}/{exp_b_id}    — analyze a specific pair
GET /api/v1/interactions/{exp_a_id}/{exp_b_id}/novelty — novelty sub-analysis

Access: DEVELOPER and above (VIEWER gets 403 on write-like analysis endpoints).
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_active_user, get_db
from backend.app.models.user import User, UserRole
from backend.app.schemas.interaction import (
    ActiveInteractionScanResponse,
    InteractionAnalysisResponse,
    NoveltyResultSchema,
    RiskLevel,
)
from backend.app.services.interaction_detection_service import (
    InteractionDetectionService,
    InteractionAnalysis,
    InteractionResult,
    NoveltyResult,
    SUTVAResult,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Permission helper
# ---------------------------------------------------------------------------

def _require_developer(current_user: User) -> None:
    """Raise 403 when the user is VIEWER (read-only role).

    DEVELOPER, ANALYST, and ADMIN may access interaction analysis endpoints.
    """
    role = getattr(current_user, "role", None)
    if current_user.is_superuser:
        return
    if role in (UserRole.VIEWER,):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="DEVELOPER role or higher is required to access interaction analysis.",
        )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _to_response(analysis: InteractionAnalysis) -> InteractionAnalysisResponse:
    """Convert an InteractionAnalysis dataclass to the Pydantic response schema."""
    from backend.app.schemas.interaction import (
        InteractionResultSchema,
        NoveltyResultSchema,
        SUTVAResultSchema,
    )

    interaction_result = None
    if analysis.interaction_result is not None:
        interaction_result = InteractionResultSchema(
            has_interaction=analysis.interaction_result.has_interaction,
            p_value=analysis.interaction_result.p_value,
            interaction_effect_size=analysis.interaction_result.interaction_effect_size,
            warning_message=analysis.interaction_result.warning_message,
        )

    novelty_result = None
    if analysis.novelty_result is not None:
        novelty_result = NoveltyResultSchema(
            has_novelty=analysis.novelty_result.has_novelty,
            decline_rate=analysis.novelty_result.decline_rate,
            recommendation=analysis.novelty_result.recommendation,
        )

    sutva_result = None
    if analysis.sutva_result is not None:
        sutva_result = SUTVAResultSchema(
            has_violation=analysis.sutva_result.has_violation,
            contamination_rate=analysis.sutva_result.contamination_rate,
            warning_message=analysis.sutva_result.warning_message,
        )

    return InteractionAnalysisResponse(
        experiment_a_id=analysis.experiment_a_id,
        experiment_b_id=analysis.experiment_b_id,
        overlap_coefficient=analysis.overlap_coefficient,
        has_significant_overlap=analysis.has_significant_overlap,
        interaction_result=interaction_result,
        novelty_result=novelty_result,
        sutva_result=sutva_result,
        overall_risk=RiskLevel(analysis.overall_risk),
        recommendations=analysis.recommendations,
    )


def _make_empty_response(exp_a_id: str, exp_b_id: str) -> InteractionAnalysisResponse:
    """Return a minimal response for non-overlapping experiment pairs."""
    return InteractionAnalysisResponse(
        experiment_a_id=exp_a_id,
        experiment_b_id=exp_b_id,
        overlap_coefficient=0.0,
        has_significant_overlap=False,
        interaction_result=None,
        novelty_result=None,
        sutva_result=None,
        overall_risk=RiskLevel.LOW,
        recommendations=[
            "No significant user overlap detected between these experiments. "
            "Interaction analysis is not required."
        ],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/scan", response_model=ActiveInteractionScanResponse)
def scan_interactions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """Scan all active experiments for pairwise interactions.

    Requires DEVELOPER role or higher.
    """
    _require_developer(current_user)

    service = InteractionDetectionService()
    analyses = service.scan_active_experiments(db)
    active_ids = service._get_active_experiment_ids(db)

    response_analyses = [_to_response(a) for a in analyses]
    high_risk_count = sum(
        1 for a in response_analyses if a.overall_risk == RiskLevel.HIGH
    )

    return ActiveInteractionScanResponse(
        total_active_experiments=len(active_ids),
        pairs_analyzed=len(response_analyses),
        high_risk_pairs=high_risk_count,
        analyses=response_analyses,
    )


@router.get("/{exp_a_id}/{exp_b_id}/novelty", response_model=NoveltyResultSchema)
def analyze_novelty(
    exp_a_id: UUID,
    exp_b_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """Return the novelty sub-analysis for a pair of experiments.

    This route MUST be defined before /{exp_a_id}/{exp_b_id} to avoid
    the path segment "novelty" being captured as exp_b_id.
    """
    _require_developer(current_user)

    service = InteractionDetectionService()
    try:
        analysis = service.analyze_experiment_pair(str(exp_a_id), str(exp_b_id), db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    if analysis is None or analysis.novelty_result is None:
        return NoveltyResultSchema(
            has_novelty=False,
            decline_rate=0.0,
            recommendation=(
                "No significant user overlap detected. "
                "Novelty analysis requires overlapping experiment populations."
            ),
        )

    return NoveltyResultSchema(
        has_novelty=analysis.novelty_result.has_novelty,
        decline_rate=analysis.novelty_result.decline_rate,
        recommendation=analysis.novelty_result.recommendation,
    )


@router.get("/{exp_a_id}/{exp_b_id}", response_model=InteractionAnalysisResponse)
def analyze_pair(
    exp_a_id: UUID,
    exp_b_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """Analyze interaction between two specific experiments.

    Returns a minimal response (overlap_coefficient=0, has_significant_overlap=False)
    when experiments do not share a significant portion of users.
    """
    _require_developer(current_user)

    service = InteractionDetectionService()
    try:
        analysis = service.analyze_experiment_pair(str(exp_a_id), str(exp_b_id), db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    if analysis is None:
        return _make_empty_response(str(exp_a_id), str(exp_b_id))

    return _to_response(analysis)
