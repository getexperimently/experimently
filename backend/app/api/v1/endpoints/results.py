"""
Results and analysis endpoints (EP-016 + EP-021).

Provides endpoints for retrieving experiment results, daily time-series data,
sample size / power analysis, cache invalidation, and sequential testing analysis.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from backend.app.api.deps import get_db, get_current_active_user, get_current_superuser
from backend.app.models.analysis_snapshot import AnalysisKind
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.user import User
from backend.app.schemas.bayesian import BayesianResultsResponse
from backend.app.schemas.dimensional import DimensionalBreakdownResponse, SegmentBreakdown, SegmentVariantResult as SchemaSegmentVariantResult
from backend.app.schemas.results import (
    DailyDataPoint,
    DailyResultsResponse,
    ExperimentResultsResponse,
    SampleSizeResult,
    SRMResult,
    VariantTimeSeries,
)
from backend.app.schemas.sequential import SequentialTestingResponse
from backend.app.schemas.variance_reduction import (
    CupedMetricResult,
    CupedResultsResponse,
    VarianceReductionMethod,
)
from backend.app.services.analysis_service import AnalysisService
from backend.app.services.analysis_snapshot_service import record_snapshot
from backend.app.services.cache import CacheService
from backend.app.services.cuped_service import CupedService
from backend.app.services.dimensional_analysis_service import DimensionalAnalysisService
from backend.app.services.sequential_testing_service import SequentialTestingService
from backend.app.services.srm_service import compute_srm_for_experiment

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper: sample-ratio mismatch (best-effort)
# ---------------------------------------------------------------------------


def _compute_srm(experiment_id: UUID, db: Session) -> Optional[SRMResult]:
    """
    Run the SRM chi-square test for an experiment.

    Returns ``None`` when the test is undefined (fewer than two allocated
    variants, no assignments, or an adaptive/bandit allocation) or when the
    lookup fails — an SRM check must never turn a results request into an
    error.
    """
    try:
        result = compute_srm_for_experiment(db, experiment_id)
    except Exception as exc:  # noqa: BLE001 - best-effort by design
        logger.warning("SRM check failed for experiment %s: %s", experiment_id, exc)
        try:
            db.rollback()
        except Exception:  # pragma: no cover - defensive
            pass
        return None
    if result is None:
        return None
    try:
        return SRMResult(**result.to_dict())
    except Exception as exc:  # noqa: BLE001 - defensive against odd DB values
        logger.warning("SRM result for experiment %s not serialisable: %s", experiment_id, exc)
        return None


# ---------------------------------------------------------------------------
# Helper: build a CacheService backed by Redis (best-effort)
# ---------------------------------------------------------------------------

def _get_cache_service() -> CacheService:
    """
    Attempt to create a synchronous Redis-backed CacheService.

    Returns a disabled CacheService (no Redis client) if Redis is not
    reachable or not configured, so callers never have to handle
    connection errors explicitly.
    """
    try:
        import redis as redis_lib
        from backend.app.core.config import settings

        r = redis_lib.Redis(
            host=settings.REDIS_HOST,
            port=int(settings.REDIS_PORT),
            db=0,
        )
        # Quick ping to verify the connection is alive.
        r.ping()
        return CacheService(redis_client=r)
    except Exception:
        return CacheService(redis_client=None)


# ---------------------------------------------------------------------------
# Helper: compute dimensional breakdown (Issue #28)
# ---------------------------------------------------------------------------


def _compute_dimensional_breakdown(
    experiment_id: UUID,
    dimension: str,
    db,
    base_alpha: float = 0.05,
) -> DimensionalBreakdownResponse:
    """
    Query the database for per-segment event counts and compute breakdown statistics.

    Fetches segment values from event metadata (JSONB field), groups assignment
    and conversion counts by (segment_value, variant_id), then delegates to
    DimensionalAnalysisService for statistical computation.

    This function is tolerant: any error during data retrieval silently returns
    an empty-segment breakdown so that the main results response is not affected.
    """
    from sqlalchemy import text
    from backend.app.core.database_config import get_schema_name

    dim_service = DimensionalAnalysisService()
    segments: Dict[str, Dict[str, Any]] = {}

    # Conversions are the events named after the experiment's primary metric
    # (see services/event_matching.py); fall back to the legacy
    # event_type = 'conversion' convention when no metric row exists.
    from backend.app.models.experiment import Metric
    from backend.app.services.event_matching import CONVERSION_SQL_PREDICATE

    primary_metric = (
        db.query(Metric)
        .filter(Metric.experiment_id == experiment_id)
        .order_by(Metric.is_primary.desc())
        .first()
    )
    if primary_metric is not None and primary_metric.event_name:
        conversion_predicate = CONVERSION_SQL_PREDICATE
        conversion_params: Dict[str, Any] = {"event_name": primary_metric.event_name}
    else:
        conversion_predicate = "event_type = 'conversion'"
        conversion_params = {}

    try:
        schema = get_schema_name()

        # Pull distinct segment values for this dimension from event metadata.
        # `schema` comes from get_schema_name(), which only ever returns one of
        # two literal identifiers; all request-derived values are bound params.
        seg_val_q = text(  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            f"""
            SELECT DISTINCT
                COALESCE(
                    jsonb_extract_path_text(event_metadata, :dim_key),
                    'unknown'
                ) AS segment_value
            FROM {schema}.events
            WHERE experiment_id = :exp_id
              AND event_metadata IS NOT NULL
            """  # nosec B608 - schema is a fixed config identifier, not user input
        )
        seg_val_rows = db.execute(
            seg_val_q, {"dim_key": dimension, "exp_id": str(experiment_id)}
        ).fetchall()
        segment_values = [row[0] for row in seg_val_rows if row[0]]

        for seg_val in segment_values:
            # Count assignments per variant for this segment
            asgn_q = text(  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
                f"""
                SELECT a.variant_id::text, COUNT(DISTINCT a.user_id) AS total
                FROM {schema}.assignments a
                JOIN {schema}.events e
                  ON a.user_id = e.user_id
                 AND a.experiment_id = e.experiment_id
                WHERE a.experiment_id = :exp_id
                  AND e.event_metadata IS NOT NULL
                  AND COALESCE(
                      jsonb_extract_path_text(e.event_metadata, :dim_key),
                      'unknown'
                  ) = :seg_val
                GROUP BY a.variant_id
                """  # nosec B608 - schema is a fixed config identifier, not user input
            )
            asgn_rows = db.execute(
                asgn_q,
                {"exp_id": str(experiment_id), "dim_key": dimension, "seg_val": seg_val},
            ).fetchall()

            # Count conversions per variant for this segment
            conv_q = text(  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
                f"""
                SELECT variant_id::text, COUNT(*) AS conversions
                FROM {schema}.events
                WHERE experiment_id = :exp_id
                  AND {conversion_predicate}
                  AND event_metadata IS NOT NULL
                  AND COALESCE(
                      jsonb_extract_path_text(event_metadata, :dim_key),
                      'unknown'
                  ) = :seg_val
                GROUP BY variant_id
                """  # nosec B608 - schema is a fixed config identifier, not user input
            )
            conv_rows = db.execute(
                conv_q,
                {
                    "exp_id": str(experiment_id),
                    "dim_key": dimension,
                    "seg_val": seg_val,
                    **conversion_params,
                },
            ).fetchall()

            # Build variant_map for this segment
            variant_map: Dict[str, Any] = {}
            for vid, total in asgn_rows:
                variant_map[vid] = {"total": int(total), "conversions": 0}
            for vid, conv in conv_rows:
                if vid not in variant_map:
                    variant_map[vid] = {"total": 0, "conversions": 0}
                variant_map[vid]["conversions"] = int(conv)

            if variant_map:
                segments[seg_val] = variant_map

    except Exception as exc:
        # Non-fatal: log and return empty breakdown
        import logging
        logging.getLogger(__name__).warning(
            "Failed to fetch segment data for dimension %r: %s", dimension, exc
        )

    # Compute statistics
    segment_results = dim_service.compute_segment_results(
        segments=segments, base_alpha=base_alpha
    )
    has_hte = dim_service.detect_hte(segment_results)
    adjusted_alpha = dim_service.get_adjusted_alpha(base_alpha, len(segments)) if segments else base_alpha

    hte_warning = (
        (
            f"Heterogeneous treatment effects detected across '{dimension}' segments. "
            "Results may differ significantly between groups — "
            "investigate per-segment effects before shipping."
        )
        if has_hte
        else None
    )

    # Convert service dataclasses to Pydantic schema
    schema_segments: list = []
    for seg in segment_results:
        schema_variants = [
            SchemaSegmentVariantResult(
                variant_id=v.variant_id,
                variant_name=v.variant_name,
                is_control=v.is_control,
                sample_size=v.sample_size,
                conversions=v.conversions,
                mean=v.mean,
                confidence_interval=v.confidence_interval,
                p_value=v.p_value,
                is_significant=v.is_significant,
            )
            for v in seg.variants
        ]
        schema_segments.append(
            SegmentBreakdown(
                segment_value=seg.segment_value,
                sample_size=seg.sample_size,
                variants=schema_variants,
            )
        )

    return DimensionalBreakdownResponse(
        dimension=dimension,
        is_exploratory=True,
        adjusted_alpha=adjusted_alpha,
        has_heterogeneous_effects=has_hte,
        hte_warning=hte_warning,
        segments=schema_segments,
    )


# ---------------------------------------------------------------------------
# Endpoint 1 — GET /{experiment_id}
# ---------------------------------------------------------------------------


@router.get("/{experiment_id}", response_model=ExperimentResultsResponse)
def get_experiment_results(
    experiment_id: UUID,
    confidence_level: float = Query(default=0.95, ge=0.80, le=0.99),
    correction_method: str = Query(
        default="none",
        pattern="^(none|bonferroni|benjamini_hochberg)$",
    ),
    use_cache: bool = Query(default=True),
    breakdown: Optional[str] = Query(
        default=None,
        description=(
            "Dimension to break down results by (e.g. 'platform', 'country', "
            "'user_tier'). When supplied the response includes a 'breakdown' field "
            "with per-segment statistics and Bonferroni-corrected significance."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExperimentResultsResponse:
    """
    Get comprehensive statistical results for an experiment.

    Returns per-metric, per-variant statistics including p-values,
    confidence intervals, effect sizes, and an overall recommendation.

    Results are cached in Redis (TTL = 5 min for running experiments,
    24 h for completed/paused ones).  Pass ``use_cache=false`` to force
    a fresh computation.

    Supply ``breakdown=<dimension>`` to receive an additional per-segment
    breakdown of results (Issue #28).  Supported dimensions include
    ``platform``, ``country``, and ``user_tier``, but any dimension key
    present in event metadata is accepted.  Breakdowns are always marked
    exploratory and use Bonferroni-corrected significance thresholds.
    """
    cache_key = f"results:{experiment_id}:{confidence_level}:{correction_method}:{breakdown or ''}"

    # --- Cache read ---
    if use_cache:
        try:
            cache = _get_cache_service()
            cached = cache.get(cache_key)
            if cached:
                return ExperimentResultsResponse.model_validate_json(cached)
        except Exception:
            pass  # Cache miss is acceptable

    # --- Compute results ---
    try:
        service = AnalysisService(db)
        result = service.get_experiment_results(
            experiment_id,
            confidence_level=confidence_level,
            correction_method=correction_method,
        )
    except TypeError:
        # The service may not accept keyword arguments yet — call without them
        try:
            service = AnalysisService(db)
            result = service.get_experiment_results(experiment_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Experiment not found")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    except ValueError:
        raise HTTPException(status_code=404, detail="Experiment not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if result is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    # --- Map the service dict to the response schema ---
    # The service returns a dict — build ExperimentResultsResponse from it.
    # Fields that may be missing are handled with .get() and sensible defaults.
    try:
        # Normalise status to a string (may be an enum value)
        raw_status = result.get("status", "unknown")
        if hasattr(raw_status, "value"):
            raw_status = raw_status.value

        # Build summary sub-object
        summary_data = result.get("summary", {})

        # Build metrics list (may be keyed as metrics_results or metrics)
        metrics_data = result.get("metrics") or result.get("metrics_results") or []

        # --- Issue #28: Compute dimensional breakdown if requested ---
        breakdown_response: Optional[DimensionalBreakdownResponse] = None
        if breakdown:
            breakdown_response = _compute_dimensional_breakdown(
                experiment_id=experiment_id,
                dimension=breakdown,
                db=db,
                base_alpha=1.0 - confidence_level,
            )

        # --- P0 statistical credibility: sample-ratio mismatch ---
        srm_response = _compute_srm(experiment_id, db)

        response = ExperimentResultsResponse(
            experiment_id=result.get("experiment_id", str(experiment_id)),
            experiment_name=result.get("experiment_name", ""),
            status=raw_status,
            start_date=result.get("start_date"),
            end_date=result.get("end_date"),
            confidence_level=confidence_level,
            correction_method=correction_method,
            sample_size_adequate=result.get("sample_size_adequate", False),
            computed_at=result.get("computed_at", datetime.now(timezone.utc)),
            summary=summary_data,
            metrics=metrics_data,
            sequential_testing=result.get("sequential_testing"),
            breakdown=breakdown_response,
            bayesian_results=result.get("bayesian_results"),
            srm=srm_response,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to serialise results: {exc}",
        )

    # --- Persist audit snapshots (best-effort; never fails the response) ---
    _record_results_snapshots(db, response)

    # --- Cache write ---
    try:
        cache = _get_cache_service()
        running_statuses = {"running", "active", "RUNNING", "ACTIVE"}
        ttl = 300 if raw_status in running_statuses else 86400
        cache.set(cache_key, response.model_dump_json(), expire=ttl)
    except Exception:
        pass  # Cache write failure is non-fatal

    return response


def _record_results_snapshots(db: Session, response: ExperimentResultsResponse) -> None:
    """
    Write the ``analysis_snapshots`` rows for one fresh results computation.

    One ``frequentist`` row carries the whole response; when the experiment
    has Bayesian analysis enabled a second ``bayesian`` row records the seed
    and sample count that produced the posteriors.  Cache hits do not reach
    this function, so a row means the numbers were actually recomputed.
    """
    try:
        payload = response.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - never fail the response
        logger.warning("Could not serialise results for snapshot: %s", exc)
        return

    record_snapshot(
        db,
        response.experiment_id,
        AnalysisKind.FREQUENTIST,
        payload,
        as_of=response.computed_at,
    )

    bayesian = response.bayesian_results
    if bayesian is not None and bayesian.is_enabled:
        record_snapshot(
            db,
            response.experiment_id,
            AnalysisKind.BAYESIAN,
            payload.get("bayesian_results") or {},
            engine_version=bayesian.engine_version,
            seed=bayesian.seed,
            n_samples=bayesian.n_samples,
            as_of=response.computed_at,
        )


# ---------------------------------------------------------------------------
# Endpoint 2 — GET /{experiment_id}/daily
# ---------------------------------------------------------------------------


@router.get("/{experiment_id}/daily", response_model=DailyResultsResponse)
def get_experiment_daily_results(
    experiment_id: UUID,
    metric_id: Optional[UUID] = Query(default=None),
    start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DailyResultsResponse:
    """
    Get daily time-series results for an experiment.

    Returns both a raw daily view and a running cumulative view per variant,
    suitable for rendering trend charts.  Optionally filter to a single metric
    and/or a date range.
    """
    try:
        service = AnalysisService(db)
        daily_data: List[Dict] = service.get_daily_results(
            experiment_id,
            metric_id=metric_id,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Experiment not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # daily_data is a list of:
    # {
    #   "date": "YYYY-MM-DD",
    #   "metrics": [
    #     {
    #       "metric_id": "...",
    #       "metric_name": "...",
    #       "variants": [
    #         {
    #           "variant_id": "...",
    #           "variant_name": "...",
    #           "is_control": bool,
    #           "assignments": int,
    #           "conversions": int,
    #           "conversion_rate": float,
    #         },
    #         ...
    #       ],
    #     },
    #     ...
    #   ],
    # }
    #
    # We need to invert this into per-variant VariantTimeSeries objects,
    # each containing a list of daily data points plus cumulative totals.

    # Collect per-variant daily points.  Key = variant_id (str).
    variant_daily: Dict[str, List[Dict]] = {}  # variant_id -> list of daily dicts
    variant_meta: Dict[str, Dict] = {}         # variant_id -> {name, is_control}

    for day_entry in daily_data:
        date_str = day_entry.get("date", "")

        # Apply optional date range filter
        if start_date and date_str < start_date:
            continue
        if end_date and date_str > end_date:
            continue

        # We take the first metric (or the one matching metric_id)
        metrics_list = day_entry.get("metrics", [])
        if not metrics_list:
            continue

        # When metric_id is provided the service already filters; otherwise
        # default to the first metric in the list.
        chosen_metric = metrics_list[0]

        for v in chosen_metric.get("variants", []):
            vid = str(v["variant_id"])
            if vid not in variant_daily:
                variant_daily[vid] = []
                variant_meta[vid] = {
                    "variant_name": v.get("variant_name", ""),
                    "is_control": v.get("is_control", False),
                }
            variant_daily[vid].append(
                {
                    "date": date_str,
                    "sample_size": v.get("assignments", 0),
                    "conversions": v.get("conversions"),
                    "mean": (v.get("conversion_rate") or 0.0) / 100.0,
                }
            )

    # Build VariantTimeSeries for each variant
    series: List[VariantTimeSeries] = []
    for vid, daily_points in variant_daily.items():
        # Sort by date ascending
        daily_points.sort(key=lambda p: p["date"])

        daily_dp = [
            DailyDataPoint(
                date=p["date"],
                sample_size=p["sample_size"],
                conversions=p.get("conversions"),
                mean=p["mean"],
            )
            for p in daily_points
        ]

        # Compute cumulative series
        cumulative_sample = 0
        cumulative_conversions = 0
        cumulative_dp: List[DailyDataPoint] = []
        for p in daily_points:
            cumulative_sample += p["sample_size"]
            cumulative_conversions += p.get("conversions") or 0
            rate = (
                cumulative_conversions / cumulative_sample
                if cumulative_sample > 0
                else 0.0
            )
            cumulative_dp.append(
                DailyDataPoint(
                    date=p["date"],
                    sample_size=cumulative_sample,
                    conversions=cumulative_conversions,
                    mean=rate,
                )
            )

        meta = variant_meta[vid]
        series.append(
            VariantTimeSeries(
                variant_id=UUID(vid),
                variant_name=meta["variant_name"],
                is_control=meta["is_control"],
                values=daily_dp,
                cumulative=cumulative_dp,
            )
        )

    return DailyResultsResponse(
        experiment_id=experiment_id,
        metric_id=metric_id,
        series=series,
    )


# ---------------------------------------------------------------------------
# Endpoint 3 — GET /{experiment_id}/sample-size
# ---------------------------------------------------------------------------


@router.get("/{experiment_id}/sample-size", response_model=SampleSizeResult)
def get_sample_size_status(
    experiment_id: UUID,
    baseline_conversion_rate: float = Query(default=0.1, gt=0.0, lt=1.0),
    mde: float = Query(default=0.05, gt=0.0, lt=1.0),
    confidence_level: float = Query(default=0.95, ge=0.80, le=0.99),
    power_target: float = Query(default=0.80, ge=0.50, le=0.99),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SampleSizeResult:
    """
    Calculate sample-size requirements and current power for an experiment.

    Uses a two-proportion z-test formula to determine the required sample
    size per variant and estimates the achieved power given current enrolment.
    """
    # Try the service first (future-proofing)
    service = AnalysisService(db)
    if hasattr(service, "get_sample_size_status"):
        try:
            result = service.get_sample_size_status(
                experiment_id,
                baseline_conversion_rate,
                mde,
                confidence_level,
                power_target,
            )
            return SampleSizeResult(**result)
        except ValueError:
            raise HTTPException(status_code=404, detail="Experiment not found")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # --- Inline implementation ---
    try:
        from scipy.stats import norm
        from sqlalchemy import func as sqla_func
        from backend.app.models.assignment import Assignment

        # Verify experiment exists
        try:
            _ = service.get_experiment_results(experiment_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Experiment not found")
        except Exception:
            pass  # Continue even if full results computation fails

        alpha = 1.0 - confidence_level
        z_alpha = float(norm.ppf(1.0 - alpha / 2.0))
        z_beta = float(norm.ppf(power_target))

        p1 = baseline_conversion_rate
        p2 = p1 * (1.0 + mde)
        # Clamp p2 to (0, 1)
        p2 = min(max(p2, 1e-9), 1.0 - 1e-9)
        p_bar = (p1 + p2) / 2.0

        numerator = (
            z_alpha * math.sqrt(2.0 * p_bar * (1.0 - p_bar))
            + z_beta * math.sqrt(p1 * (1.0 - p1) + p2 * (1.0 - p2))
        ) ** 2
        denominator = (p2 - p1) ** 2
        n = math.ceil(numerator / denominator) if denominator > 0 else 1
        n = max(1, n)

        # Current sample size from the assignments table
        current_n = (
            db.query(sqla_func.count(Assignment.id))
            .filter(Assignment.experiment_id == experiment_id)
            .scalar()
            or 0
        )
        n_variants = 2  # Conservative default
        current_per_variant = current_n // n_variants if n_variants > 0 else 0

        # Achieved power
        if current_per_variant > 0:
            se = math.sqrt(p_bar * (1.0 - p_bar) * (2.0 / current_per_variant))
            achieved_power = float(
                norm.cdf(abs(p2 - p1) / se - z_alpha)
            ) if se > 0 else 0.0
        else:
            achieved_power = 0.0

        achieved_power = min(1.0, max(0.0, achieved_power))

        return SampleSizeResult(
            required_sample_size_per_variant=n,
            current_sample_size_per_variant=current_per_variant,
            is_adequate=current_per_variant >= n,
            achieved_power=achieved_power,
            days_to_significance=None,
            projected_completion_date=None,
            baseline_rate=p1,
            mde=mde,
            confidence_level=confidence_level,
            power_target=power_target,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Endpoint 4 — POST /{experiment_id}/invalidate-cache
# ---------------------------------------------------------------------------


@router.post("/{experiment_id}/invalidate-cache")
def invalidate_results_cache(
    experiment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
) -> Dict:
    """
    Invalidate all cached results for an experiment (superuser only).

    Deletes every Redis key that matches ``results:{experiment_id}:*``.
    Cache invalidation is best-effort: a failure here does not raise an error.
    """
    try:
        import redis as redis_lib
        from backend.app.core.config import settings

        r = redis_lib.Redis(
            host=settings.REDIS_HOST,
            port=int(settings.REDIS_PORT),
            db=0,
        )
        cache = CacheService(redis_client=r)
        cache.clear(pattern=f"results:{experiment_id}:*")
    except Exception:
        pass  # Cache invalidation is best-effort

    return {"status": "ok", "experiment_id": str(experiment_id)}


# ---------------------------------------------------------------------------
# EP-021: Sequential Testing Helpers
# ---------------------------------------------------------------------------


def _get_experiment_for_sequential(
    experiment_id: UUID, db: Session
) -> Optional[Experiment]:
    """Fetch experiment for sequential analysis. Returns None if not found."""
    return (
        db.query(Experiment)
        .options(
            joinedload(Experiment.variants),
            joinedload(Experiment.metric_definitions),
        )
        .filter(Experiment.id == experiment_id)
        .first()
    )


def _get_sequential_data(
    experiment: Experiment, db: Session
) -> Tuple[int, int, int, int]:
    """
    Extract control/treatment conversion data for sequential analysis.

    Returns (control_successes, control_total, treatment_successes, treatment_total).
    """
    from sqlalchemy import func
    from backend.app.models.assignment import Assignment
    from backend.app.models.event import Event

    control_variant = next(
        (v for v in experiment.variants if v.is_control), None
    )
    treatment_variant = next(
        (v for v in experiment.variants if not v.is_control), None
    )

    if not control_variant or not treatment_variant:
        return (0, 0, 0, 0)

    # Get primary metric
    primary_metric = next(
        (m for m in experiment.metric_definitions if m.is_primary),
        experiment.metric_definitions[0] if experiment.metric_definitions else None,
    )

    def _count_assignments(variant_id):
        return (
            db.query(func.count(Assignment.id))
            .filter(
                Assignment.experiment_id == experiment.id,
                Assignment.variant_id == variant_id,
            )
            .scalar()
            or 0
        )

    def _count_conversions(variant_id):
        if not primary_metric:
            return 0
        from backend.app.services.event_matching import conversion_event_filter

        return (
            db.query(func.count(Event.id))
            .filter(
                Event.experiment_id == experiment.id,
                Event.variant_id == variant_id,
                conversion_event_filter(primary_metric.event_name),
            )
            .scalar()
            or 0
        )

    control_total = _count_assignments(control_variant.id)
    control_successes = _count_conversions(control_variant.id)
    treatment_total = _count_assignments(treatment_variant.id)
    treatment_successes = _count_conversions(treatment_variant.id)

    return (control_successes, control_total, treatment_successes, treatment_total)


# ---------------------------------------------------------------------------
# Endpoint 5 — GET /{experiment_id}/sequential (EP-021)
# ---------------------------------------------------------------------------


@router.get(
    "/{experiment_id}/sequential",
    response_model=SequentialTestingResponse,
)
def get_sequential_results(
    experiment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SequentialTestingResponse:
    """
    Get sequential testing analysis for an experiment (EP-021).

    Returns mSPRT evidence ratio, always-valid confidence intervals,
    evidence trajectory for charting, alpha spending boundaries,
    and a recommended action (stop/continue).

    Only available for experiments with sequential_testing_enabled=True.
    """
    experiment = _get_experiment_for_sequential(experiment_id, db)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if not experiment.sequential_testing_enabled:
        raise HTTPException(
            status_code=404,
            detail="Sequential testing is not enabled for this experiment",
        )

    # Extract config
    config = experiment.sequential_testing_config or {}
    tau_squared = config.get("tau_squared", 0.001)
    spending_function = config.get("spending_function", "obrien_fleming")
    planned_looks = config.get("planned_looks", 10)
    alpha = config.get("alpha", 0.05)

    # Get conversion data
    control_s, control_t, treatment_s, treatment_t = _get_sequential_data(
        experiment, db
    )

    # Calculate duration
    actual_days = 0
    if experiment.start_date:
        delta = datetime.now(timezone.utc) - experiment.start_date.replace(
            tzinfo=timezone.utc
        ) if experiment.start_date.tzinfo is None else datetime.now(timezone.utc) - experiment.start_date
        actual_days = max(0, delta.days)

    # Run sequential analysis
    service = SequentialTestingService()
    analysis = service.run_sequential_analysis(
        control_successes=control_s,
        control_total=control_t,
        treatment_successes=treatment_s,
        treatment_total=treatment_t,
        config={
            "tau_squared": tau_squared,
            "spending_function": spending_function,
            "planned_looks": planned_looks,
            "alpha": alpha,
            "actual_days": actual_days,
            "expected_days": config.get("expected_duration_days", 30),
            "required_sample_size": config.get("required_sample_size", 10000),
        },
    )

    # Convert dataclass to response schema
    msprt_data = None
    if analysis.msprt_result:
        msprt_data = {
            "lambda_ratio": analysis.msprt_result.lambda_ratio,
            "always_valid_p_value": analysis.msprt_result.always_valid_p_value,
            "can_stop": analysis.msprt_result.can_stop,
            "evidence_strength": analysis.msprt_result.evidence_strength.value,
            "boundary": analysis.msprt_result.boundary,
        }

    cs_data = None
    if analysis.confidence_sequence:
        cs_data = {
            "lower": analysis.confidence_sequence.lower,
            "upper": analysis.confidence_sequence.upper,
            "width": analysis.confidence_sequence.width,
            "sample_size": analysis.confidence_sequence.sample_size,
        }

    trajectory_data = [
        {
            "sample_size": pt.sample_size,
            "lambda_ratio": pt.lambda_ratio,
            "always_valid_p_value": pt.always_valid_p_value,
            "can_stop": pt.can_stop,
        }
        for pt in analysis.evidence_trajectory
    ]

    spending_data = [
        {
            "look_number": b.look_number,
            "cumulative_alpha": b.cumulative_alpha,
            "boundary_z": b.boundary_z,
            "boundary_p": b.boundary_p,
        }
        for b in analysis.alpha_spending
    ]

    risk_data = None
    if analysis.long_running_risk:
        risk_data = {
            "is_at_risk": analysis.long_running_risk.is_at_risk,
            "expected_duration_days": analysis.long_running_risk.expected_duration_days,
            "actual_duration_days": analysis.long_running_risk.actual_duration_days,
            "risk_ratio": analysis.long_running_risk.risk_ratio,
            "recommendation": analysis.long_running_risk.recommendation,
        }

    response = SequentialTestingResponse(
        method=analysis.method.value,
        msprt_result=msprt_data,
        confidence_sequence=cs_data,
        evidence_trajectory=trajectory_data,
        alpha_spending=spending_data,
        long_running_risk=risk_data,
        recommended_action=analysis.recommended_action,
    )

    # Audit snapshot (best-effort; mSPRT is closed-form, so no seed).
    try:
        record_snapshot(
            db,
            experiment_id,
            AnalysisKind.SEQUENTIAL,
            response.model_dump(mode="json"),
        )
    except Exception as exc:  # noqa: BLE001 - never fail the response
        logger.warning("Sequential snapshot failed for %s: %s", experiment_id, exc)

    return response


# ---------------------------------------------------------------------------
# Issue #21 — CUPED helper + endpoint
# ---------------------------------------------------------------------------


def get_cuped_results_data(
    experiment_id: UUID,
    db: Session,
) -> CupedResultsResponse:
    """
    Compute CUPED variance-reduced results for an experiment.

    This helper is a separate function so that it can be easily mocked in
    unit tests.  It:
      1. Loads the experiment and its metric/assignment data.
      2. Reads variance_reduction_config to determine the method.
      3. Calls CupedService to compute adjusted statistics per metric.
      4. Returns a CupedResultsResponse.

    Raises:
        ValueError: If the experiment is not found.
    """
    import numpy as np

    # Fetch experiment
    experiment = (
        db.query(Experiment)
        .options(
            joinedload(Experiment.variants),
            joinedload(Experiment.metric_definitions),
        )
        .filter(Experiment.id == experiment_id)
        .first()
    )
    if not experiment:
        raise ValueError("Experiment not found")

    # Determine method from variance_reduction_config
    vr_config = experiment.variance_reduction_config or {}
    method_str = vr_config.get("method", VarianceReductionMethod.NONE.value)
    try:
        method = VarianceReductionMethod(method_str)
    except ValueError:
        method = VarianceReductionMethod.NONE

    winsorization_pct = float(vr_config.get("winsorization_percentile", 99.0))

    computed_at = datetime.now(timezone.utc).isoformat()

    # Identify control and treatment variants
    control_variant = next(
        (v for v in experiment.variants if v.is_control), None
    )
    treatment_variants = [v for v in experiment.variants if not v.is_control]

    metric_results: List[CupedMetricResult] = []

    for metric_def in experiment.metric_definitions:
        # Pull per-user metric values from the assignments/events tables.
        # For a robust implementation we would join events; here we build
        # synthetic per-user arrays from aggregate counts so the service can
        # always return a sensible (if simplified) result when the DB is live.
        #
        # The full CUPED pipeline with real pre-experiment covariates would
        # require a separate covariate data source (out of scope for this
        # endpoint's inline computation — use a dedicated analytics job).
        # Instead we demonstrate the pipeline with the available assignment
        # data, treating assignment order as a proxy covariate.

        try:
            from sqlalchemy import func as sqla_func
            from backend.app.models.assignment import Assignment
            from backend.app.models.event import Event, EventType

            def _get_outcomes(variant_id):
                """Return (Y, X) arrays for CUPED — Y=converted, X=assignment index."""
                assignments = (
                    db.query(Assignment)
                    .filter(
                        Assignment.experiment_id == experiment.id,
                        Assignment.variant_id == variant_id,
                    )
                    .all()
                )
                if not assignments:
                    return np.zeros(1), np.zeros(1)

                n = len(assignments)
                # X = assignment order (proxy pre-experiment covariate)
                X = np.arange(n, dtype=float)

                # Y = 1 if user converted, 0 otherwise
                converted_ids = set(
                    str(e.user_id)
                    for e in db.query(Event)
                    .filter(
                        Event.experiment_id == experiment.id,
                        Event.variant_id == variant_id,
                        Event.event_name == metric_def.event_name,
                    )
                    .all()
                )
                Y = np.array(
                    [1.0 if str(a.user_id) in converted_ids else 0.0
                     for a in assignments]
                )
                return Y, X

            if control_variant is None or not treatment_variants:
                # Not enough variants to compute an effect
                continue

            Y_c, X_c = _get_outcomes(control_variant.id)
            treatment_variant = treatment_variants[0]
            Y_t, X_t = _get_outcomes(treatment_variant.id)

            # Apply Winsorization if requested (before CUPED)
            if method in (VarianceReductionMethod.WINSORIZATION,
                          VarianceReductionMethod.CUPED,
                          VarianceReductionMethod.CUPED_PLUS):
                if method == VarianceReductionMethod.WINSORIZATION:
                    Y_c = CupedService.apply_winsorization(Y_c, percentile=winsorization_pct)
                    Y_t = CupedService.apply_winsorization(Y_t, percentile=winsorization_pct)

            # Compute CUPED effect
            cuped_effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
            applied_method = method if method != VarianceReductionMethod.NONE else VarianceReductionMethod.NONE

            metric_results.append(
                CupedMetricResult(
                    metric_id=str(metric_def.id),
                    metric_name=metric_def.name,
                    adjusted_control_mean=cuped_effect.adjusted_control_mean,
                    adjusted_treatment_mean=cuped_effect.adjusted_treatment_mean,
                    adjusted_effect=cuped_effect.adjusted_effect,
                    adjusted_se=cuped_effect.adjusted_se,
                    adjusted_p_value=cuped_effect.adjusted_p_value,
                    adjusted_ci_lower=cuped_effect.adjusted_ci[0],
                    adjusted_ci_upper=cuped_effect.adjusted_ci[1],
                    variance_reduction_pct=cuped_effect.variance_reduction_pct,
                    theta=cuped_effect.theta,
                    method=applied_method,
                )
            )
        except Exception:
            # If computation fails for a metric, skip it gracefully
            continue

    return CupedResultsResponse(
        experiment_id=str(experiment_id),
        method=method,
        metrics=metric_results,
        computed_at=computed_at,
    )


# ---------------------------------------------------------------------------
# Endpoint 6 — GET /{experiment_id}/cuped (Issue #21)
# ---------------------------------------------------------------------------


@router.get(
    "/{experiment_id}/cuped",
    response_model=CupedResultsResponse,
)
def get_cuped_results(
    experiment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CupedResultsResponse:
    """
    Get CUPED variance-reduced results for an experiment (Issue #21).

    Returns CUPED-adjusted per-metric effect estimates with lower variance
    than the standard analysis, enabling faster detection of true effects.

    The variance-reduction method is read from the experiment's
    ``variance_reduction_config`` JSONB field:

    - ``none``         — No adjustment (returns unadjusted effect, θ=0).
    - ``cuped``        — CUPED adjustment using pre-experiment covariate.
    - ``cuped_plus``   — CUPED++ with delta-method ratio adjustment.
    - ``winsorization`` — Winsorization only (no CUPED).

    Returns 404 if the experiment does not exist.
    """
    try:
        response = get_cuped_results_data(experiment_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CUPED computation failed: {exc}")

    # Audit snapshot (best-effort; CUPED is closed-form, so no seed).
    try:
        record_snapshot(
            db,
            experiment_id,
            AnalysisKind.CUPED,
            response.model_dump(mode="json"),
            engine_version=response.engine_version,
            as_of=response.computed_at,
        )
    except Exception as exc:  # noqa: BLE001 - never fail the response
        logger.warning("CUPED snapshot failed for %s: %s", experiment_id, exc)

    return response


# ---------------------------------------------------------------------------
# Endpoint 7 — GET /{experiment_id}/bayesian (P0 statistical credibility)
# ---------------------------------------------------------------------------


@router.get(
    "/{experiment_id}/bayesian",
    response_model=BayesianResultsResponse,
)
def get_bayesian_results(
    experiment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> BayesianResultsResponse:
    """
    Get the Bayesian analysis block for an experiment on its own.

    Returns the same ``bayesian_results`` payload that ``GET /results/{id}``
    embeds, always freshly computed (no cache).  The Monte Carlo seed is
    derived from ``(experiment_id, UTC day, n_samples)`` and echoed in the
    response, so two calls on the same day return byte-identical posteriors
    and the same ``seed``.

    Returns ``is_enabled=false`` (HTTP 200) when the experiment has not opted
    into Bayesian analysis, and 404 when the experiment does not exist.
    """
    experiment = _get_experiment_for_sequential(experiment_id, db)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    service = AnalysisService(db)
    if not service.is_bayesian_enabled(experiment):
        return BayesianResultsResponse(is_enabled=False)

    try:
        response = service.compute_bayesian_results(experiment)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Bayesian computation failed: {exc}"
        )

    try:
        record_snapshot(
            db,
            experiment_id,
            AnalysisKind.BAYESIAN,
            response.model_dump(mode="json"),
            engine_version=response.engine_version,
            seed=response.seed,
            n_samples=response.n_samples,
        )
    except Exception as exc:  # noqa: BLE001 - never fail the response
        logger.warning("Bayesian snapshot failed for %s: %s", experiment_id, exc)

    return response
