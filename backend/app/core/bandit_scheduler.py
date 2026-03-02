"""
BanditScheduler — runs every 15 minutes to update MAB variant weights.

Reads conversion counts from DynamoDB (via real-time counter integration)
and updates BanditState in PostgreSQL so the dashboard and assignment Lambda
can read fresh weights.

Typical run cycle
-----------------
1. Query PostgreSQL for all ACTIVE experiments whose optimization_type is not "fixed".
2. For each experiment, fetch per-variant conversion counts from DynamoDB counters.
3. Compute new weights via BanditService.
4. Upsert BanditState row (create if missing, update if present).
5. Return a summary dict ``{updated: N, skipped: N, errors: N}``.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.bandit_state import BanditState
from backend.app.services.bandit_service import BanditService, VariantStats

logger = logging.getLogger(__name__)


class BanditScheduler:
    """
    Scheduler that keeps MAB allocation weights fresh in PostgreSQL.

    Can be called from a background thread (APScheduler) or invoked directly
    in tests via ``run_once()``.
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
            logger.warning(
                "Experiment %s has no variants — skipping", experiment.id
            )
            return False

        # Fetch stats (DynamoDB → fallback to BanditState)
        variant_stats = self.get_variant_stats_from_counters(
            experiment.id, variant_ids
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

    def get_variant_stats_from_counters(
        self,
        experiment_id: UUID,
        variant_ids: List[str],
    ) -> Dict[str, VariantStats]:
        """
        Fetch variant conversion counts from DynamoDB counters.

        Falls back to the persisted BanditState if DynamoDB is unavailable or
        returns no data, and uses zero-count priors when neither source has data.

        Parameters
        ----------
        experiment_id:
            UUID of the experiment.
        variant_ids:
            List of variant ID strings to fetch.

        Returns
        -------
        dict
            ``{variant_id: VariantStats}``
        """
        stats: Dict[str, VariantStats] = {}

        try:
            from backend.app.services.dynamodb_counter_service import (
                DynamoDBCounterService,
            )

            counter_service = DynamoDBCounterService()
            counters = counter_service.get_counters(str(experiment_id))

            for vid in variant_ids:
                variant_data = counters.get(vid, {}) if counters else {}
                stats[vid] = VariantStats(
                    variant_id=vid,
                    successes=int(variant_data.get("conversions", 0)),
                    failures=int(
                        variant_data.get("assignments", 0)
                        - variant_data.get("conversions", 0)
                    ),
                    pulls=int(variant_data.get("assignments", 0)),
                    total_reward=float(variant_data.get("conversions", 0)),
                )
        except Exception as exc:
            logger.warning(
                "BanditScheduler: DynamoDB unavailable for experiment %s (%s); "
                "falling back to BanditState",
                experiment_id,
                exc,
            )
            # Fallback: read from BanditState if it exists
            bandit_state: Optional[BanditState] = (
                self.db.query(BanditState)
                .filter(BanditState.experiment_id == experiment_id)
                .first()
            )

            if bandit_state and bandit_state.variant_weights:
                for vid in variant_ids:
                    vdata = bandit_state.variant_weights.get(vid, {})
                    stats[vid] = VariantStats(
                        variant_id=vid,
                        successes=int(vdata.get("successes", 0)),
                        failures=int(vdata.get("failures", 0)),
                        pulls=int(vdata.get("pulls", 0)),
                        total_reward=float(vdata.get("successes", 0)),
                    )
            else:
                # No data at all — use zero-count priors
                for vid in variant_ids:
                    stats[vid] = VariantStats(variant_id=vid)

        return stats

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
