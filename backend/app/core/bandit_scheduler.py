"""
BanditScheduler — periodically recomputes MAB variant weights.

Reads per-variant pull/conversion counts and updates BanditState in
PostgreSQL so the dashboard and the ``/tracking/assign`` endpoint can read
fresh weights.

Stats sources, in order of preference
-------------------------------------
1. DynamoDB real-time counters (``DynamoDBCounterService.get_experiment_counters``).
2. PostgreSQL: ``count(Assignment)`` per variant for pulls and the number of
   distinct converting users (events whose ``event_type`` equals the
   experiment's primary metric ``event_name``) for successes.  Used when
   DynamoDB is unavailable or holds no data for the experiment.
3. The previously persisted ``BanditState`` row.
4. Zero-count priors (equal weights).

Typical run cycle
-----------------
1. Query PostgreSQL for all ACTIVE experiments whose optimization_type is not "fixed".
2. For each experiment, fetch per-variant conversion counts (see above).
3. Compute new weights via BanditService.
4. Upsert BanditState row (create if missing, update if present).
5. Return a summary dict ``{updated: N, skipped: N, errors: N}``.

``BanditSchedulerRunner`` wraps the synchronous scheduler in an asyncio
loop so the FastAPI app can keep the weights fresh in the background.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.assignment import Assignment
from backend.app.models.bandit_state import BanditState
from backend.app.models.event import Event
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.services.bandit_service import BanditService, VariantStats
from backend.app.services.event_matching import (
    EXPOSURE_EVENT_TYPES,
    conversion_event_filter,
)

logger = logging.getLogger(__name__)


def _has_pulls(stats: Optional[Dict[str, VariantStats]]) -> bool:
    """Return True when at least one variant in ``stats`` recorded a pull."""
    return bool(stats) and any(vs.pulls > 0 for vs in stats.values())


class BanditScheduler:
    """
    Scheduler that keeps MAB allocation weights fresh in PostgreSQL.

    Can be called from a background task (``BanditSchedulerRunner``) or
    invoked directly in tests via ``run_once()``.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_once(self) -> Dict[str, int]:
        """
        Execute one scheduling pass.

        Returns
        -------
        dict
            ``{"updated": int, "skipped": int, "errors": int}``
        """
        summary: Dict[str, int] = {"updated": 0, "skipped": 0, "errors": 0}

        # Fetch all ACTIVE experiments that use a bandit algorithm
        active_mab_experiments = (
            self.db.query(Experiment)
            .filter(
                Experiment.status == ExperimentStatus.ACTIVE,
                Experiment.optimization_type != "fixed",
            )
            .all()
        )

        if not active_mab_experiments:
            logger.info("BanditScheduler: no active MAB experiments found")
            return summary

        for experiment in active_mab_experiments:
            try:
                updated = self.update_experiment(experiment)
                if updated:
                    summary["updated"] += 1
                else:
                    summary["skipped"] += 1
            except Exception as exc:
                logger.error(
                    "BanditScheduler: failed to update experiment %s: %s",
                    experiment.id,
                    exc,
                    exc_info=True,
                )
                summary["errors"] += 1
                try:
                    self.db.rollback()
                except Exception:  # pragma: no cover - defensive
                    pass

        logger.info(
            "BanditScheduler run complete: %s",
            summary,
        )
        return summary

    def update_experiment(self, experiment: Experiment) -> bool:
        """
        Recompute and persist bandit weights for a single experiment.

        Parameters
        ----------
        experiment:
            An active MAB experiment SQLAlchemy object.

        Returns
        -------
        bool
            ``True`` on success, ``False`` if skipped (e.g. fixed algorithm).
        """
        if experiment.optimization_type == "fixed":
            logger.debug(
                "Skipping experiment %s (optimization_type=fixed)", experiment.id
            )
            return False

        # Collect variant IDs
        variant_ids: List[str] = [str(v.id) for v in experiment.variants]

        if not variant_ids:
            logger.warning("Experiment %s has no variants — skipping", experiment.id)
            return False

        # Fetch stats (DynamoDB → PostgreSQL → BanditState → priors)
        variant_stats = self.get_variant_stats_from_counters(
            experiment.id, variant_ids, experiment=experiment
        )

        # Build the raw dict expected by BanditService
        variant_data: Dict[str, Dict] = {
            vid: {
                "successes": vs.successes,
                "failures": vs.failures,
                "pulls": vs.pulls,
                "total_reward": vs.total_reward,
            }
            for vid, vs in variant_stats.items()
        }

        # Compute new weights
        new_weights: Dict[str, float] = BanditService.compute_weights(
            algorithm=experiment.optimization_type,
            variant_data=variant_data,
        )

        total_pulls = sum(vs.pulls for vs in variant_stats.values())
        regret_pct = self.estimate_regret_reduction(new_weights, variant_stats)
        now_iso = datetime.now(timezone.utc).isoformat()

        # Build full variant_weights payload (weights + stats per variant)
        weights_payload: Dict[str, Dict] = {}
        for vid, weight in new_weights.items():
            stats = variant_stats.get(vid)
            weights_payload[vid] = {
                "weight": weight,
                "successes": stats.successes if stats else 0,
                "failures": stats.failures if stats else 0,
                "pulls": stats.pulls if stats else 0,
            }

        # Upsert BanditState
        bandit_state: Optional[BanditState] = (
            self.db.query(BanditState)
            .filter(BanditState.experiment_id == experiment.id)
            .first()
        )

        if bandit_state is None:
            bandit_state = BanditState(
                experiment_id=experiment.id,
                algorithm=experiment.optimization_type,
                variant_weights=weights_payload,
                total_pulls=total_pulls,
                regret_reduction_pct=regret_pct if regret_pct > 0 else None,
                last_computed_at=now_iso,
            )
            self.db.add(bandit_state)
        else:
            bandit_state.algorithm = experiment.optimization_type
            bandit_state.variant_weights = weights_payload
            bandit_state.total_pulls = total_pulls
            bandit_state.regret_reduction_pct = regret_pct if regret_pct > 0 else None
            bandit_state.last_computed_at = now_iso

        self.db.commit()

        logger.info(
            "BanditScheduler: updated weights for experiment %s (%s)",
            experiment.id,
            experiment.optimization_type,
        )
        return True

    # ------------------------------------------------------------------
    # Stats sources
    # ------------------------------------------------------------------

    def get_variant_stats_from_counters(
        self,
        experiment_id: UUID,
        variant_ids: List[str],
        experiment: Optional[Experiment] = None,
    ) -> Dict[str, VariantStats]:
        """
        Fetch per-variant pull/conversion counts for an experiment.

        Sources are tried in order: DynamoDB counters, PostgreSQL
        (assignments + conversion events), the persisted BanditState, and
        finally zero-count priors.  A source is skipped when it raises or
        when no variant has recorded a pull.

        Parameters
        ----------
        experiment_id:
            UUID of the experiment.
        variant_ids:
            List of variant ID strings to fetch.
        experiment:
            Optional experiment object; used to read the primary metric
            without an extra query.  Loaded from the DB when omitted.

        Returns
        -------
        dict
            ``{variant_id: VariantStats}``
        """
        stats = self._stats_from_dynamodb(experiment_id, variant_ids)
        if _has_pulls(stats):
            return stats  # type: ignore[return-value]

        stats = self._stats_from_postgres(experiment_id, variant_ids, experiment)
        if _has_pulls(stats):
            return stats  # type: ignore[return-value]

        stats = self._stats_from_bandit_state(experiment_id, variant_ids)
        if stats is not None:
            return stats

        # No data at all — use zero-count priors
        return {vid: VariantStats(variant_id=vid) for vid in variant_ids}

    def _stats_from_dynamodb(
        self, experiment_id: UUID, variant_ids: List[str]
    ) -> Optional[Dict[str, VariantStats]]:
        """Read counters from DynamoDB; ``None`` when the service is unavailable."""
        try:
            from backend.app.services.dynamodb_counter_service import (
                DynamoDBCounterService,
            )

            counter_service = DynamoDBCounterService()
            counters = counter_service.get_experiment_counters(str(experiment_id))
        except Exception as exc:
            logger.warning(
                "BanditScheduler: DynamoDB unavailable for experiment %s (%s); "
                "falling back to PostgreSQL",
                experiment_id,
                exc,
            )
            return None

        by_variant: Dict[str, Any] = {}
        for vc in getattr(counters, "variants", None) or []:
            by_variant[str(vc.variant_id)] = vc

        stats: Dict[str, VariantStats] = {}
        for vid in variant_ids:
            vc = by_variant.get(vid)
            assignments = int(getattr(vc, "assignments", 0) or 0) if vc else 0
            conversions = int(getattr(vc, "conversions", 0) or 0) if vc else 0
            stats[vid] = VariantStats(
                variant_id=vid,
                successes=conversions,
                failures=max(assignments - conversions, 0),
                pulls=assignments,
                total_reward=float(conversions),
            )
        return stats

    def _stats_from_postgres(
        self,
        experiment_id: UUID,
        variant_ids: List[str],
        experiment: Optional[Experiment] = None,
    ) -> Optional[Dict[str, VariantStats]]:
        """
        Derive pulls/successes from assignments and conversion events.

        pulls     = number of Assignment rows per variant
        successes = distinct converting users per variant, where a converting
                    user has an Event for the experiment whose ``event_type``
                    is the primary metric's ``event_name``.
        """
        try:
            if experiment is None:
                experiment = (
                    self.db.query(Experiment)
                    .filter(Experiment.id == experiment_id)
                    .first()
                )
            event_name = self._primary_event_name(experiment)
            pulls = self._count_assignments_by_variant(experiment_id)
            successes = self._count_conversions_by_variant(experiment_id, event_name)
        except Exception as exc:
            logger.warning(
                "BanditScheduler: PostgreSQL stats unavailable for experiment %s (%s); "
                "falling back to BanditState",
                experiment_id,
                exc,
            )
            try:
                self.db.rollback()
            except Exception:  # pragma: no cover - defensive
                pass
            return None

        stats: Dict[str, VariantStats] = {}
        for vid in variant_ids:
            n_pulls = int(pulls.get(vid, 0))
            n_successes = min(int(successes.get(vid, 0)), n_pulls)
            stats[vid] = VariantStats(
                variant_id=vid,
                successes=n_successes,
                failures=max(n_pulls - n_successes, 0),
                pulls=n_pulls,
                total_reward=float(n_successes),
            )
        return stats

    def _stats_from_bandit_state(
        self, experiment_id: UUID, variant_ids: List[str]
    ) -> Optional[Dict[str, VariantStats]]:
        """Read the previously persisted stats; ``None`` when there are none."""
        bandit_state: Optional[BanditState] = (
            self.db.query(BanditState)
            .filter(BanditState.experiment_id == experiment_id)
            .first()
        )

        if not bandit_state or not bandit_state.variant_weights:
            return None

        stats: Dict[str, VariantStats] = {}
        for vid in variant_ids:
            vdata = bandit_state.variant_weights.get(vid, {})
            if not isinstance(vdata, dict):
                vdata = {}
            stats[vid] = VariantStats(
                variant_id=vid,
                successes=int(vdata.get("successes", 0)),
                failures=int(vdata.get("failures", 0)),
                pulls=int(vdata.get("pulls", 0)),
                total_reward=float(vdata.get("successes", 0)),
            )
        return stats

    @staticmethod
    def _primary_event_name(experiment: Optional[Experiment]) -> Optional[str]:
        """
        Resolve the conversion event for an experiment.

        Uses the ``is_primary`` Metric row, then the first Metric row, then
        the legacy ``experiments.metrics['primary_metric']`` JSON value.
        Returns ``None`` when nothing is configured.
        """
        if experiment is None:
            return None

        metrics = list(getattr(experiment, "metric_definitions", None) or [])
        primary = next((m for m in metrics if getattr(m, "is_primary", False)), None)
        if primary is None and metrics:
            primary = metrics[0]
        if primary is not None and getattr(primary, "event_name", None):
            return str(primary.event_name)

        legacy = getattr(experiment, "metrics", None)
        if isinstance(legacy, dict):
            name = legacy.get("primary_metric")
            if isinstance(name, str) and name:
                return name
        return None

    def _count_assignments_by_variant(self, experiment_id: UUID) -> Dict[str, int]:
        """``{variant_id: assignment_count}`` for the experiment."""
        rows = (
            self.db.query(Assignment.variant_id, func.count(Assignment.id))
            .filter(Assignment.experiment_id == experiment_id)
            .group_by(Assignment.variant_id)
            .all()
        )
        return {str(variant_id): int(count) for variant_id, count in rows}

    def _count_conversions_by_variant(
        self, experiment_id: UUID, event_name: Optional[str]
    ) -> Dict[str, int]:
        """
        ``{variant_id: distinct_converting_users}`` for the experiment.

        Conversions are attributed to the variant the user is assigned to.
        When ``event_name`` is ``None`` every non-exposure event counts.
        """
        query = (
            self.db.query(
                Assignment.variant_id, func.count(func.distinct(Event.user_id))
            )
            .join(
                Event,
                and_(
                    Event.user_id == Assignment.user_id,
                    Event.experiment_id == Assignment.experiment_id,
                ),
            )
            .filter(Assignment.experiment_id == experiment_id)
        )
        if event_name:
            # Same rule as the results engine: match the metric's event_name,
            # whatever event_type the producer used (see services/event_matching).
            query = query.filter(conversion_event_filter(event_name))
        else:
            query = query.filter(Event.event_type.notin_(EXPOSURE_EVENT_TYPES))
        rows = query.group_by(Assignment.variant_id).all()
        return {str(variant_id): int(count) for variant_id, count in rows}

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------

    def estimate_regret_reduction(
        self,
        weights: Dict[str, float],
        variant_stats: Dict[str, VariantStats],
    ) -> float:
        """
        Estimate percentage regret reduction vs. uniform allocation.

        Regret is defined as the opportunity cost of not always showing
        the best variant.  We compare:
        - Expected reward under current weights
        - Expected reward under uniform allocation

        Parameters
        ----------
        weights:
            Current bandit weights ``{variant_id: float}``.
        variant_stats:
            Per-variant stats ``{variant_id: VariantStats}``.

        Returns
        -------
        float
            Percentage improvement (0.0 for uniform weights or no data).
        """
        if not weights or not variant_stats:
            return 0.0

        # Compute conversion rates
        rates: Dict[str, float] = {
            vid: vs.conversion_rate for vid, vs in variant_stats.items()
        }

        # Expected reward under current bandit weights
        bandit_reward = sum(
            weights.get(vid, 0.0) * rates.get(vid, 0.0) for vid in weights
        )

        # Expected reward under uniform allocation
        n = len(weights)
        if n == 0:
            return 0.0
        uniform_weight = 1.0 / n
        uniform_reward = sum(uniform_weight * rates.get(vid, 0.0) for vid in weights)

        if uniform_reward == 0.0:
            return 0.0

        reduction = (bandit_reward - uniform_reward) / uniform_reward * 100.0
        return max(0.0, reduction)

    def get_recommendation(
        self,
        weights: Dict[str, float],
        variant_names: Dict[str, str],
    ) -> str:
        """
        Return a human-readable recommendation string.

        Rules
        -----
        - ``max_weight >= 0.8``  → ``"DEPLOYING_<VariantName>"``
        - ``max_weight >= 0.5``  → ``"CONVERGING"``
        - otherwise             → ``"EXPLORING"``

        Parameters
        ----------
        weights:
            Current bandit weights ``{variant_id: float}``.
        variant_names:
            Mapping ``{variant_id: variant_name}`` for display.

        Returns
        -------
        str
            Recommendation string.
        """
        if not weights:
            return "EXPLORING"

        max_weight = max(weights.values())

        if max_weight >= 0.8:
            winning_id = max(weights, key=weights.get)
            name = variant_names.get(winning_id, winning_id)
            return f"DEPLOYING_{name}"

        if max_weight >= 0.5:
            return "CONVERGING"

        return "EXPLORING"


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------


def _is_test_environment() -> bool:
    """True when running under pytest / the test settings profile."""
    if bool(getattr(settings, "TESTING", False)):
        return True
    if os.environ.get("APP_ENV", "").lower() == "test":
        return True
    return os.environ.get("TESTING", "").lower() in ("1", "true", "yes")


class BanditSchedulerRunner:
    """
    Asyncio wrapper that runs ``BanditScheduler.run_once()`` periodically.

    Each pass opens a fresh ``SessionLocal()`` session and executes the
    synchronous scheduler in a worker thread so the event loop is never
    blocked.  Errors are logged and the loop keeps going.

    The runner does not start under the test profile (``settings.TESTING``
    or ``APP_ENV=test``) unless ``run_in_tests=True`` is passed.
    """

    def __init__(
        self,
        interval_minutes: Optional[int] = None,
        run_in_tests: bool = False,
    ) -> None:
        if interval_minutes is None:
            interval_minutes = int(
                getattr(settings, "BANDIT_UPDATE_INTERVAL_MINUTES", 5)
            )
        self.interval_minutes = interval_minutes
        # Seconds slept between passes; tests shorten this directly.
        self.interval_seconds: float = float(interval_minutes) * 60.0
        self.run_in_tests = run_in_tests
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self.run_count = 0
        self.error_count = 0
        self.last_result: Optional[Dict[str, int]] = None
        self.last_error: Optional[str] = None

    async def start(self) -> None:
        """Start the background loop (no-op in the test environment)."""
        if self.is_running:
            logger.warning("Bandit scheduler is already running")
            return

        if not self.run_in_tests and _is_test_environment():
            logger.info("Bandit scheduler not started (test environment)")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._run_scheduler())
        logger.info(
            "Bandit scheduler started with %s minute interval", self.interval_minutes
        )

    async def stop(self) -> None:
        """Cancel the background loop and wait for it to finish."""
        if not self.is_running:
            return

        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Bandit scheduler task ended with error: %s", exc)
            self.task = None
        logger.info("Bandit scheduler stopped")

    async def _run_scheduler(self) -> None:
        """Loop: run one pass, sleep, repeat until stopped."""
        while self.is_running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.error_count += 1
                self.last_error = str(exc)
                logger.error("Error in bandit scheduler: %s", exc, exc_info=True)

            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break

    async def run_once(self) -> Dict[str, int]:
        """Execute a single scheduler pass in a worker thread."""
        result = await asyncio.to_thread(self._run_sync)
        self.run_count += 1
        self.last_result = result
        return result

    @staticmethod
    def _run_sync() -> Dict[str, int]:
        """Open a session, run the scheduler once, close the session."""
        from backend.app.db.session import SessionLocal

        db = SessionLocal()
        try:
            return BanditScheduler(db).run_once()
        finally:
            db.close()


# Global instance started/stopped by the FastAPI lifespan
bandit_scheduler_runner = BanditSchedulerRunner()
