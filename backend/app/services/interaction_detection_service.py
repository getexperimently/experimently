"""
Experiment Interaction Detection Service.

Detects statistical interactions, novelty effects, and SUTVA violations
when multiple experiments run simultaneously on the same user population.
Provides cross-experiment analysis for the dashboard API.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Set

import numpy as np
from scipy import stats


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class InteractionResult:
    """Result of a 2×2 interaction test between two experiments."""

    has_interaction: bool
    p_value: float
    interaction_effect_size: float
    warning_message: Optional[str] = None


@dataclass
class NoveltyResult:
    """Result of a novelty effect analysis on daily treatment effects."""

    has_novelty: bool
    decline_rate: float  # slope of linear regression on daily_effects
    recommendation: str


@dataclass
class SUTVAResult:
    """Result of a SUTVA (Stable Unit Treatment Value Assumption) check."""

    has_violation: bool
    contamination_rate: float
    warning_message: Optional[str] = None


@dataclass
class InteractionAnalysis:
    """Full interaction analysis for a pair of experiments."""

    experiment_a_id: str
    experiment_b_id: str
    overlap_coefficient: float
    has_significant_overlap: bool
    interaction_result: Optional[InteractionResult]
    novelty_result: Optional[NoveltyResult]
    sutva_result: Optional[SUTVAResult]
    overall_risk: str  # "low" | "medium" | "high"
    recommendations: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Service implementation
# ---------------------------------------------------------------------------

class InteractionDetectionService:
    """Service for detecting interactions between simultaneously running experiments."""

    OVERLAP_THRESHOLD = 0.30  # Flag pairs with > 30 % shared users
    NOVELTY_SLOPE_THRESHOLD = -0.05  # Negative slope threshold to flag novelty

    # ------------------------------------------------------------------
    # Overlap detection
    # ------------------------------------------------------------------

    @staticmethod
    def compute_user_overlap(users_a: Set[str], users_b: Set[str]) -> float:
        """Compute Jaccard similarity: |A ∩ B| / |A ∪ B|.

        Returns 0.0 when either set is empty.
        """
        if not users_a or not users_b:
            return 0.0
        intersection = len(users_a & users_b)
        union = len(users_a | users_b)
        if union == 0:
            return 0.0
        return intersection / union

    @staticmethod
    def has_significant_overlap(
        users_a: Set[str],
        users_b: Set[str],
        threshold: float = 0.30,
    ) -> bool:
        """Return True when the Jaccard similarity exceeds the threshold."""
        jaccard = InteractionDetectionService.compute_user_overlap(users_a, users_b)
        return jaccard > threshold

    # ------------------------------------------------------------------
    # Interaction effect detection
    # ------------------------------------------------------------------

    @staticmethod
    def detect_interaction(
        control_only: int,
        treatment_a_only: int,
        treatment_b_only: int,
        both_treatments: int,
    ) -> InteractionResult:
        """Chi-squared test for interaction between experiments A and B.

        Constructs a 2×2 contingency table and tests for independence:

            +----------------+----------+-----------+
            |                | Exp-B ON | Exp-B OFF |
            +----------------+----------+-----------+
            | Exp-A ON       | both     | a_only    |
            | Exp-A OFF      | b_only   | control   |
            +----------------+----------+-----------+
        """
        table = np.array(
            [[both_treatments, treatment_a_only], [treatment_b_only, control_only]],
            dtype=float,
        )

        # scipy chi2_contingency requires all cells >= 0 and total > 0
        if table.sum() == 0:
            return InteractionResult(
                has_interaction=False,
                p_value=1.0,
                interaction_effect_size=0.0,
                warning_message="Empty contingency table — cannot compute interaction.",
            )

        chi2, p_value, dof, expected = stats.chi2_contingency(table, correction=False)

        # Effect size: simple excess above additivity for the "both" cell
        total = table.sum()
        row_marginal_both = both_treatments + treatment_a_only
        col_marginal_both = both_treatments + treatment_b_only
        expected_both = (row_marginal_both * col_marginal_both) / total if total > 0 else 0
        interaction_effect_size = (both_treatments - expected_both) / total if total > 0 else 0.0

        has_interaction = bool(p_value < 0.05)
        warning_message = (
            "Significant interaction detected between experiments. "
            "Results may be confounded."
            if has_interaction
            else None
        )

        return InteractionResult(
            has_interaction=has_interaction,
            p_value=float(p_value),
            interaction_effect_size=float(interaction_effect_size),
            warning_message=warning_message,
        )

    @staticmethod
    def compute_interaction_effect_size(
        a_effect: float,
        b_effect: float,
        ab_effect: float,
    ) -> float:
        """Excess effect beyond additivity: AB − A − B."""
        return ab_effect - a_effect - b_effect

    # ------------------------------------------------------------------
    # Novelty effect detection
    # ------------------------------------------------------------------

    @staticmethod
    def detect_novelty_effect(daily_effects: List[float]) -> NoveltyResult:
        """Detect novelty effects by fitting a linear regression to daily effect sizes.

        A significantly negative slope indicates that the treatment effect is
        declining over time, which is the signature of a novelty effect.
        """
        if len(daily_effects) < 2:
            return NoveltyResult(
                has_novelty=False,
                decline_rate=0.0,
                recommendation="Not enough data points to detect novelty effect.",
            )

        x = np.arange(len(daily_effects), dtype=float)
        y = np.array(daily_effects, dtype=float)

        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

        # A clearly negative slope signals novelty
        has_novelty = bool(slope < InteractionDetectionService.NOVELTY_SLOPE_THRESHOLD)

        if has_novelty:
            recommendation = (
                "Novelty effect detected: treatment effect is declining over time. "
                "Extend the minimum runtime of the experiment to allow the novelty "
                "effect to dissipate before making a decision."
            )
        else:
            recommendation = (
                "No significant novelty effect detected. "
                "The treatment effect appears stable over the observed period."
            )

        return NoveltyResult(
            has_novelty=has_novelty,
            decline_rate=float(slope),
            recommendation=recommendation,
        )

    # ------------------------------------------------------------------
    # SUTVA violation detection
    # ------------------------------------------------------------------

    @staticmethod
    def check_sutva(
        treatment_size: int,
        control_size: int,
        network_feature: bool = False,
        contamination_rate: float = 0.0,
    ) -> SUTVAResult:
        """Check for SUTVA (Stable Unit Treatment Value Assumption) violations.

        Network features inherently violate SUTVA because a user's outcome
        depends on the treatment status of other users.
        """
        has_violation = network_feature or contamination_rate > 0.05

        if network_feature:
            warning_message = (
                "This experiment involves a network or social feature. "
                "SUTVA is likely violated: treatment of one user may affect outcomes "
                "for control users through network effects."
            )
        elif contamination_rate > 0.05:
            warning_message = (
                f"Contamination rate of {contamination_rate:.1%} exceeds acceptable threshold. "
                "Some control users have been exposed to the treatment, "
                "which may bias the experiment results."
            )
        else:
            warning_message = None

        return SUTVAResult(
            has_violation=has_violation,
            contamination_rate=contamination_rate,
            warning_message=warning_message,
        )

    @staticmethod
    def compute_contamination_rate(
        treatment_users: Set[str],
        control_users_exposed_to_treatment: Set[str],
    ) -> float:
        """Compute the fraction of contaminated control users.

        contamination_rate = |exposed control users| / |treatment users|

        Returns 0.0 when treatment_users is empty.
        """
        if not treatment_users:
            return 0.0
        return len(control_users_exposed_to_treatment) / len(treatment_users)

    # ------------------------------------------------------------------
    # High-level service methods (database-aware)
    # ------------------------------------------------------------------

    def analyze_experiment_pair(
        self,
        experiment_a_id: str,
        experiment_b_id: str,
        db,
    ) -> Optional[InteractionAnalysis]:
        """Full interaction analysis for two experiments.

        Returns None if the experiments do not have significant user overlap
        (Jaccard < OVERLAP_THRESHOLD).
        """
        users_a = self._get_experiment_users(experiment_a_id, db)
        users_b = self._get_experiment_users(experiment_b_id, db)

        overlap = self.compute_user_overlap(users_a, users_b)
        significant = overlap > self.OVERLAP_THRESHOLD

        if not significant:
            return None

        # Basic interaction result using rough user counts as proxy for 2×2 table
        n_a = len(users_a)
        n_b = len(users_b)
        n_both = len(users_a & users_b)
        n_control = max(1, n_a + n_b - 2 * n_both)

        interaction_result = self.detect_interaction(
            control_only=n_control,
            treatment_a_only=n_a - n_both,
            treatment_b_only=n_b - n_both,
            both_treatments=n_both,
        )

        # No daily data available from the DB stub — return a neutral result
        novelty_result = NoveltyResult(
            has_novelty=False,
            decline_rate=0.0,
            recommendation="Novelty analysis requires time-series data.",
        )

        # SUTVA: flag contamination equal to the overlap count / treatment size
        contamination = n_both / n_a if n_a > 0 else 0.0
        sutva_result = self.check_sutva(
            treatment_size=n_a,
            control_size=n_b,
            network_feature=False,
            contamination_rate=contamination,
        )

        analysis = InteractionAnalysis(
            experiment_a_id=experiment_a_id,
            experiment_b_id=experiment_b_id,
            overlap_coefficient=overlap,
            has_significant_overlap=significant,
            interaction_result=interaction_result,
            novelty_result=novelty_result,
            sutva_result=sutva_result,
            overall_risk="",  # computed below
            recommendations=[],
        )
        analysis.overall_risk = self._compute_overall_risk(analysis)
        analysis.recommendations = self._build_recommendations(analysis)
        return analysis

    def scan_active_experiments(self, db) -> List[InteractionAnalysis]:
        """Scan all active experiment pairs for interactions.

        Pairs with overlap < OVERLAP_THRESHOLD are excluded.
        """
        exp_ids = self._get_active_experiment_ids(db)
        results: List[InteractionAnalysis] = []

        for i in range(len(exp_ids)):
            for j in range(i + 1, len(exp_ids)):
                analysis = self.analyze_experiment_pair(exp_ids[i], exp_ids[j], db)
                if analysis is not None:
                    results.append(analysis)

        return results

    # ------------------------------------------------------------------
    # Risk aggregation
    # ------------------------------------------------------------------

    def _compute_overall_risk(self, analysis: InteractionAnalysis) -> str:
        """Aggregate risk level from interaction, novelty, and SUTVA signals."""
        risk_score = 0

        if analysis.interaction_result and analysis.interaction_result.has_interaction:
            risk_score += 2
        if analysis.novelty_result and analysis.novelty_result.has_novelty:
            risk_score += 1
        if analysis.sutva_result and analysis.sutva_result.has_violation:
            risk_score += 2

        if risk_score >= 3:
            return "high"
        if risk_score >= 1:
            return "medium"
        return "low"

    def _build_recommendations(self, analysis: InteractionAnalysis) -> List[str]:
        """Build a list of actionable recommendations from sub-results."""
        recs: List[str] = []

        if analysis.interaction_result and analysis.interaction_result.warning_message:
            recs.append(analysis.interaction_result.warning_message)
        if analysis.novelty_result and analysis.novelty_result.has_novelty:
            recs.append(analysis.novelty_result.recommendation)
        if analysis.sutva_result and analysis.sutva_result.warning_message:
            recs.append(analysis.sutva_result.warning_message)
        if not recs:
            recs.append(
                "No significant interaction concerns detected for this experiment pair."
            )
        return recs

    # ------------------------------------------------------------------
    # Database helpers (stubbed — override or patch in tests)
    # ------------------------------------------------------------------

    def _get_experiment_users(self, experiment_id: str, db) -> Set[str]:
        """Return the set of user IDs assigned to an experiment.

        Queries the assignments table for the given experiment_id.
        Falls back to an empty set if the query fails or returns nothing.
        """
        try:
            from backend.app.models.assignment import Assignment  # noqa: WPS433 — local import
            rows = (
                db.query(Assignment.user_id)
                .filter(Assignment.experiment_id == experiment_id)
                .all()
            )
            return {str(row.user_id) for row in rows}
        except Exception:
            return set()

    def _get_active_experiment_ids(self, db) -> List[str]:
        """Return a list of IDs for all currently active experiments."""
        try:
            from backend.app.models.experiment import Experiment, ExperimentStatus  # noqa: WPS433
            rows = (
                db.query(Experiment.id)
                .filter(Experiment.status == ExperimentStatus.ACTIVE)
                .all()
            )
            return [str(row.id) for row in rows]
        except Exception:
            return []
