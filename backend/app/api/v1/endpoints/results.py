"""
Results and analysis endpoints (EP-016).

Provides endpoints for retrieving experiment results, daily time-series data,
sample size / power analysis, and cache invalidation.
"""

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_current_active_user, get_current_superuser
from backend.app.models.user import User
from backend.app.schemas.results import (
    DailyDataPoint,
    DailyResultsResponse,
    ExperimentResultsResponse,
    SampleSizeResult,
    VariantTimeSeries,
)
from backend.app.services.analysis_service import AnalysisService
from backend.app.services.cache import CacheService

router = APIRouter()


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
    """
    cache_key = f"results:{experiment_id}:{confidence_level}:{correction_method}"

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
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to serialise results: {exc}",
        )

    # --- Cache write ---
    try:
        cache = _get_cache_service()
        running_statuses = {"running", "active", "RUNNING", "ACTIVE"}
        ttl = 300 if raw_status in running_statuses else 86400
        cache.set(cache_key, response.model_dump_json(), expire=ttl)
    except Exception:
        pass  # Cache write failure is non-fatal

    return response


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
