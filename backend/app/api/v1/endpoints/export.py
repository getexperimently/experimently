"""
Data export and reporting endpoints (EP-020).

GET  /api/v1/export/experiments           — Download all experiments as CSV/JSON
GET  /api/v1/export/variants              — Download variant results as CSV/JSON
GET  /api/v1/export/feature-flags         — Download feature flag data as CSV/JSON
GET  /api/v1/export/reports/overview      — Platform overview report (JSON)
GET  /api/v1/export/reports/experiments/{id} — Full single-experiment report (JSON)
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.api.deps import get_db
from backend.app.models.user import User
from backend.app.schemas.export import ExportFormat, ExportRequest, ExportScope
from backend.app.services.export_service import ExportService

router = APIRouter()


# ---------------------------------------------------------------------------
# Export: Experiments
# ---------------------------------------------------------------------------


@router.get(
    "/experiments",
    summary="Export experiments to CSV or JSON",
    description=(
        "Download all (or filtered) experiments as a CSV or JSON file. "
        "Requires authentication. Available to all roles."
    ),
    tags=["Export"],
)
def export_experiments(
    format: ExportFormat = Query(
        ExportFormat.CSV, description="Output format: csv or json"
    ),
    scope: ExportScope = Query(ExportScope.SUMMARY, description="Data scope"),
    start_date: Optional[datetime] = Query(
        None, description="Filter by created_at >= start_date (inclusive)"
    ),
    end_date: Optional[datetime] = Query(
        None, description="Filter by created_at <= end_date (inclusive)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> StreamingResponse:
    """
    Download all experiments as CSV (default) or JSON.

    Supports optional date filtering using `start_date` and `end_date`.
    The file is streamed as an attachment.
    """
    request = ExportRequest(
        format=format,
        scope=scope,
        start_date=start_date,
        end_date=end_date,
    )
    service = ExportService(db)
    content, content_type = service.export_experiments(request)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"experiments_{timestamp}.{format.value}"

    return StreamingResponse(
        iter([content]),
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Export: Variants
# ---------------------------------------------------------------------------


@router.get(
    "/variants",
    summary="Export variant results to CSV or JSON",
    description=(
        "Download per-variant results for all (or filtered) experiments. "
        "Requires authentication."
    ),
    tags=["Export"],
)
def export_variants(
    format: ExportFormat = Query(
        ExportFormat.CSV, description="Output format: csv or json"
    ),
    scope: ExportScope = Query(ExportScope.SUMMARY, description="Data scope"),
    start_date: Optional[datetime] = Query(
        None, description="Filter experiments created at or after this date"
    ),
    end_date: Optional[datetime] = Query(
        None, description="Filter experiments created at or before this date"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> StreamingResponse:
    """
    Download variant-level results as CSV (default) or JSON.

    Each row represents one variant within one experiment, with aggregated
    metrics such as assignments, conversions, p-value and statistical significance.
    """
    request = ExportRequest(
        format=format,
        scope=scope,
        start_date=start_date,
        end_date=end_date,
    )
    service = ExportService(db)
    content, content_type = service.export_variants(request)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"variants_{timestamp}.{format.value}"

    return StreamingResponse(
        iter([content]),
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Export: Feature Flags
# ---------------------------------------------------------------------------


@router.get(
    "/feature-flags",
    summary="Export feature flag data to CSV or JSON",
    description=(
        "Download feature flag usage data as a CSV or JSON file. "
        "Requires authentication."
    ),
    tags=["Export"],
)
def export_feature_flags(
    format: ExportFormat = Query(
        ExportFormat.CSV, description="Output format: csv or json"
    ),
    start_date: Optional[datetime] = Query(
        None, description="Filter flags created at or after this date"
    ),
    end_date: Optional[datetime] = Query(
        None, description="Filter flags created at or before this date"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> StreamingResponse:
    """
    Download feature flag data as CSV (default) or JSON.

    Includes rollout percentages, evaluation counts, and enabled rates for
    each feature flag.
    """
    request = ExportRequest(
        format=format,
        scope=ExportScope.SUMMARY,
        start_date=start_date,
        end_date=end_date,
    )
    service = ExportService(db)
    content, content_type = service.export_feature_flags(request)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"feature_flags_{timestamp}.{format.value}"

    return StreamingResponse(
        iter([content]),
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Reports: Platform Overview
# ---------------------------------------------------------------------------


@router.get(
    "/reports/overview",
    summary="Platform overview report",
    description=(
        "Returns a JSON summary of platform-wide experiment and feature flag "
        "activity. Optionally filtered by a date range."
    ),
    tags=["Reports"],
)
def get_overview_report(
    start_date: Optional[datetime] = Query(
        None, description="Report period start (inclusive)"
    ),
    end_date: Optional[datetime] = Query(
        None, description="Report period end (inclusive)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> JSONResponse:
    """
    Generate a platform-wide overview report.

    Returns aggregate counts for experiments, feature flags, assignments, events,
    and experiment winners. Supports optional date-range filtering.
    """
    service = ExportService(db)
    report = service.generate_platform_overview(
        start_date=start_date,
        end_date=end_date,
    )
    return JSONResponse(content=report.model_dump())


# ---------------------------------------------------------------------------
# Reports: Single Experiment
# ---------------------------------------------------------------------------


@router.get(
    "/reports/experiments/{experiment_id}",
    summary="Full experiment report",
    description=(
        "Returns a JSON report for a single experiment, including all variant "
        "data and summary statistics."
    ),
    tags=["Reports"],
)
def get_experiment_report(
    experiment_id: str,
    format: ExportFormat = Query(
        ExportFormat.JSON, description="Output format: csv or json"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> JSONResponse:
    """
    Generate a detailed report for a single experiment.

    Exports both experiment-level and variant-level data for the requested
    experiment.
    """
    # Always use JSON format internally so the report can be composed into one response
    json_request = ExportRequest(format=ExportFormat.JSON, scope=ExportScope.SUMMARY)
    service = ExportService(db)

    import json as _json

    # Fetch experiment rows filtered to this specific ID
    exp_result = service.export_experiments(
        json_request, experiment_ids=[experiment_id]
    )
    exp_content: str = (
        exp_result[0] if isinstance(exp_result, tuple) else str(exp_result)
    )
    experiments = _json.loads(exp_content) if exp_content else []

    # Fetch variant rows for this experiment
    var_result = service.export_variants(json_request, experiment_ids=[experiment_id])
    var_content: str = (
        var_result[0] if isinstance(var_result, tuple) else str(var_result)
    )
    variants = _json.loads(var_content) if var_content else []

    report: dict = {
        "experiment_id": experiment_id,
        "experiments": experiments,
        "variants": variants,
    }

    if experiments and isinstance(experiments, list) and experiments:
        report["experiment_id"] = experiments[0].get("experiment_id", experiment_id)

    return JSONResponse(content=report)
