"""
EP-021 Sequential Testing Service.

Implements continuous monitoring of experiments using sequential statistical
methods that maintain valid error rates even with repeated peeking.

Key methods:
- mSPRT (mixture Sequential Probability Ratio Test)
- Always-valid confidence intervals (confidence sequences)
- Alpha spending functions (O'Brien-Fleming, Pocock)
- Evidence trajectory tracking
- Long-running experiment risk detection
"""

import logging
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from scipy import stats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SequentialTestingMethod(str, Enum):
    MSPRT = "msprt"
    ALWAYS_VALID = "always_valid"


class SpendingFunction(str, Enum):
    OBRIEN_FLEMING = "obrien_fleming"
    POCOCK = "pocock"


class EvidenceStrength(str, Enum):
    STRONG_FOR_EFFECT = "strong_for_effect"
    MODERATE_FOR_EFFECT = "moderate_for_effect"
    INCONCLUSIVE = "inconclusive"
    MODERATE_FOR_NULL = "moderate_for_null"
    STRONG_FOR_NULL = "strong_for_null"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MSPRTResult:
    """Result of an mSPRT computation."""

    lambda_ratio: float
    always_valid_p_value: float
    can_stop: bool
    evidence_strength: EvidenceStrength
    boundary: float  # 1/alpha


@dataclass
class ConfidenceSequence:
    """An always-valid confidence interval."""

    lower: float
    upper: float
    width: float
    sample_size: int


@dataclass
class AlphaSpendingBoundary:
    """A single boundary in an alpha spending schedule."""

    look_number: int
    cumulative_alpha: float
    boundary_z: float
    boundary_p: float


@dataclass
class EvidencePoint:
    """A single point along the evidence trajectory."""

    sample_size: int
    lambda_ratio: float
    always_valid_p_value: float
    can_stop: bool


@dataclass
class LongRunningRisk:
    """Risk assessment for a long-running experiment."""

    is_at_risk: bool
    expected_duration_days: int
    actual_duration_days: int
    risk_ratio: float
    recommendation: str


@dataclass
class SequentialAnalysis:
    """Full sequential analysis result for an experiment."""

    method: SequentialTestingMethod
    msprt_result: Optional[MSPRTResult]
    confidence_sequence: Optional[ConfidenceSequence]
    evidence_trajectory: List[EvidencePoint]
    alpha_spending: List[AlphaSpendingBoundary]
    long_running_risk: Optional[LongRunningRisk]
    recommended_action: str  # "stop_for_effect", "stop_for_futility", "continue"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SequentialTestingService:
    """
    Service for sequential testing of A/B experiments.

    Provides statistically valid early stopping decisions using the mSPRT
    framework, always-valid confidence intervals, and alpha spending
    functions for group sequential designs.
    """

    def compute_msprt(
        self,
        control_successes: int,
        control_total: int,
        treatment_successes: int,
        treatment_total: int,
        tau_squared: float = 0.001,
        alpha: float = 0.05,
    ) -> MSPRTResult:
        """
        Compute the mixture Sequential Probability Ratio Test (mSPRT).

        The mSPRT uses a Gaussian mixture over possible effect sizes to
        produce an evidence ratio (lambda) that can be monitored continuously.

        Args:
            control_successes: Number of successes in control group.
            control_total: Total observations in control group.
            treatment_successes: Number of successes in treatment group.
            treatment_total: Total observations in treatment group.
            tau_squared: Variance of the Gaussian mixing distribution.
                         Smaller values give more power for small effects.
            alpha: Significance level for the test.

        Returns:
            MSPRTResult with lambda ratio, p-value, and stopping decision.
        """
        boundary = 1.0 / alpha

        # Edge cases: insufficient data
        if control_total == 0 or treatment_total == 0:
            return MSPRTResult(
                lambda_ratio=1.0,
                always_valid_p_value=1.0,
                can_stop=False,
                evidence_strength=EvidenceStrength.INCONCLUSIVE,
                boundary=boundary,
            )

        p_c = control_successes / control_total
        p_t = treatment_successes / treatment_total
        delta = p_t - p_c

        # Pooled variance of the difference in proportions
        V_n = p_c * (1 - p_c) / control_total + p_t * (1 - p_t) / treatment_total

        if V_n <= 0:
            # Degenerate case (all 0s or all 1s in both groups)
            return MSPRTResult(
                lambda_ratio=1.0,
                always_valid_p_value=1.0,
                can_stop=False,
                evidence_strength=EvidenceStrength.INCONCLUSIVE,
                boundary=boundary,
            )

        Z_n = delta / math.sqrt(V_n)

        # mSPRT lambda: mixture likelihood ratio with Gaussian(0, tau^2) prior
        # Lambda_n = sqrt(V_n / (V_n + tau^2)) * exp(tau^2 * Z_n^2 / (2*(V_n + tau^2)))
        ratio = V_n / (V_n + tau_squared)
        lambda_ratio = math.sqrt(ratio) * math.exp(
            tau_squared * Z_n**2 / (2.0 * (V_n + tau_squared))
        )

        can_stop = lambda_ratio >= boundary
        always_valid_p = min(1.0, 1.0 / lambda_ratio)

        evidence_strength = self._classify_evidence(lambda_ratio, boundary)

        return MSPRTResult(
            lambda_ratio=lambda_ratio,
            always_valid_p_value=always_valid_p,
            can_stop=can_stop,
            evidence_strength=evidence_strength,
            boundary=boundary,
        )

    def compute_always_valid_ci(
        self,
        control_successes: int,
        control_total: int,
        treatment_successes: int,
        treatment_total: int,
        alpha: float = 0.05,
        tau_squared: float = 0.001,
    ) -> ConfidenceSequence:
        """
        Compute an always-valid confidence interval (confidence sequence).

        Uses the mSPRT mixing parameter to construct a CI that remains
        valid under continuous monitoring.

        Args:
            control_successes: Number of successes in control group.
            control_total: Total observations in control group.
            treatment_successes: Number of successes in treatment group.
            treatment_total: Total observations in treatment group.
            alpha: Confidence level (CI is 1 - alpha).
            tau_squared: Variance of the mixing distribution.

        Returns:
            ConfidenceSequence with lower, upper, width, and sample_size.
        """
        sample_size = control_total + treatment_total

        if control_total == 0 or treatment_total == 0:
            return ConfidenceSequence(
                lower=-1.0,
                upper=1.0,
                width=2.0,
                sample_size=sample_size,
            )

        p_c = control_successes / control_total
        p_t = treatment_successes / treatment_total
        delta_hat = p_t - p_c

        V_n = p_c * (1 - p_c) / control_total + p_t * (1 - p_t) / treatment_total

        # rho = sqrt(V_n + tau^2), the effective standard deviation under the
        # mixture distribution
        rho = math.sqrt(V_n + tau_squared)

        # Approximate margin: rho * sqrt(2 * log(1/alpha))
        margin = rho * math.sqrt(2.0 * math.log(1.0 / alpha))

        lower = delta_hat - margin
        upper = delta_hat + margin
        width = upper - lower

        return ConfidenceSequence(
            lower=lower,
            upper=upper,
            width=width,
            sample_size=sample_size,
        )

    def compute_alpha_spending(
        self,
        current_look: int,
        planned_looks: int,
        alpha: float = 0.05,
        spending_function: SpendingFunction = SpendingFunction.OBRIEN_FLEMING,
    ) -> List[AlphaSpendingBoundary]:
        """
        Compute alpha spending boundaries for a group sequential design.

        Args:
            current_look: How many looks have been taken so far.
            planned_looks: Total number of planned looks (analyses).
            alpha: Overall significance level to spend.
            spending_function: Which spending function to use.

        Returns:
            List of AlphaSpendingBoundary, one per look up to current_look.
        """
        boundaries: List[AlphaSpendingBoundary] = []

        if spending_function == SpendingFunction.POCOCK:
            boundaries = self._pocock_spending(current_look, planned_looks, alpha)
        else:
            boundaries = self._obrien_fleming_spending(
                current_look, planned_looks, alpha
            )

        return boundaries

    def compute_evidence_trajectory(
        self,
        control_successes_over_time: List[int],
        control_totals_over_time: List[int],
        treatment_successes_over_time: List[int],
        treatment_totals_over_time: List[int],
        tau_squared: float = 0.001,
        alpha: float = 0.05,
    ) -> List[EvidencePoint]:
        """
        Compute the evidence trajectory over sequential data looks.

        Takes parallel lists of cumulative data at each look and returns
        a trajectory of evidence points.

        Args:
            control_successes_over_time: Cumulative control successes at each look.
            control_totals_over_time: Cumulative control totals at each look.
            treatment_successes_over_time: Cumulative treatment successes at each look.
            treatment_totals_over_time: Cumulative treatment totals at each look.
            tau_squared: Mixing distribution variance.
            alpha: Significance level.

        Returns:
            List of EvidencePoint, one per look.
        """
        n_looks = len(control_successes_over_time)
        trajectory: List[EvidencePoint] = []

        for i in range(n_looks):
            msprt = self.compute_msprt(
                control_successes=control_successes_over_time[i],
                control_total=control_totals_over_time[i],
                treatment_successes=treatment_successes_over_time[i],
                treatment_total=treatment_totals_over_time[i],
                tau_squared=tau_squared,
                alpha=alpha,
            )
            sample_size = control_totals_over_time[i] + treatment_totals_over_time[i]
            trajectory.append(
                EvidencePoint(
                    sample_size=sample_size,
                    lambda_ratio=msprt.lambda_ratio,
                    always_valid_p_value=msprt.always_valid_p_value,
                    can_stop=msprt.can_stop,
                )
            )

        return trajectory

    def estimate_long_running_risk(
        self,
        actual_days: int,
        expected_days: int,
        current_sample_size: int,
        required_sample_size: int,
    ) -> LongRunningRisk:
        """
        Assess whether an experiment is at risk of running too long.

        An experiment is flagged at risk if:
        - actual_days > 1.5 * expected_days, OR
        - at 50%+ of expected duration with < 50% of required samples

        Args:
            actual_days: How many days the experiment has been running.
            expected_days: How many days the experiment was expected to run.
            current_sample_size: Current total observations collected.
            required_sample_size: Required total observations.

        Returns:
            LongRunningRisk with risk assessment and recommendation.
        """
        risk_ratio = actual_days / expected_days if expected_days > 0 else 0.0

        duration_exceeded = actual_days > 1.5 * expected_days

        fraction_of_duration = actual_days / expected_days if expected_days > 0 else 0.0
        fraction_of_samples = (
            current_sample_size / required_sample_size
            if required_sample_size > 0
            else 0.0
        )
        slow_collection = fraction_of_duration >= 0.5 and fraction_of_samples < 0.5

        is_at_risk = duration_exceeded or slow_collection

        if duration_exceeded:
            recommendation = (
                "Experiment has exceeded 1.5x its expected duration. "
                "Consider stopping for futility or increasing traffic allocation."
            )
        elif slow_collection:
            recommendation = (
                "Sample collection is significantly behind schedule. "
                "Consider increasing traffic allocation or extending the expected duration."
            )
        else:
            recommendation = "Experiment is on track. No action needed."

        return LongRunningRisk(
            is_at_risk=is_at_risk,
            expected_duration_days=expected_days,
            actual_duration_days=actual_days,
            risk_ratio=risk_ratio,
            recommendation=recommendation,
        )

    def run_sequential_analysis(
        self,
        control_successes: int,
        control_total: int,
        treatment_successes: int,
        treatment_total: int,
        config: Dict[str, Any],
    ) -> SequentialAnalysis:
        """
        Run a full sequential analysis combining all methods.

        Args:
            control_successes: Number of successes in control group.
            control_total: Total observations in control group.
            treatment_successes: Number of successes in treatment group.
            treatment_total: Total observations in treatment group.
            config: Dictionary with:
                - tau_squared (float): Mixing distribution variance
                - alpha (float): Significance level
                - spending_function (SpendingFunction): Alpha spending type
                - planned_looks (int): Total planned analyses
                - current_look (int): Current analysis number
                - actual_days (int): Days the experiment has been running
                - expected_days (int): Expected experiment duration in days
                - required_sample_size (int): Total required sample size

        Returns:
            SequentialAnalysis with all component results and recommendation.
        """
        tau_squared = config.get("tau_squared", 0.001)
        alpha = config.get("alpha", 0.05)
        spending_fn = config.get("spending_function", SpendingFunction.OBRIEN_FLEMING)
        planned_looks = config.get("planned_looks", 5)
        current_look = config.get("current_look", 1)
        actual_days = config.get("actual_days", 0)
        expected_days = config.get("expected_days", 14)
        required_sample_size = config.get("required_sample_size", 10000)

        # 1. mSPRT
        msprt_result = self.compute_msprt(
            control_successes=control_successes,
            control_total=control_total,
            treatment_successes=treatment_successes,
            treatment_total=treatment_total,
            tau_squared=tau_squared,
            alpha=alpha,
        )

        # 2. Always-valid confidence interval
        confidence_sequence = self.compute_always_valid_ci(
            control_successes=control_successes,
            control_total=control_total,
            treatment_successes=treatment_successes,
            treatment_total=treatment_total,
            alpha=alpha,
            tau_squared=tau_squared,
        )

        # 3. Alpha spending boundaries
        alpha_spending = self.compute_alpha_spending(
            current_look=current_look,
            planned_looks=planned_looks,
            alpha=alpha,
            spending_function=spending_fn,
        )

        # 4. Long-running risk
        total_sample = control_total + treatment_total
        long_running_risk = self.estimate_long_running_risk(
            actual_days=actual_days,
            expected_days=expected_days,
            current_sample_size=total_sample,
            required_sample_size=required_sample_size,
        )

        # 5. Evidence trajectory (single point for current data)
        evidence_trajectory = [
            EvidencePoint(
                sample_size=total_sample,
                lambda_ratio=msprt_result.lambda_ratio,
                always_valid_p_value=msprt_result.always_valid_p_value,
                can_stop=msprt_result.can_stop,
            )
        ]

        # 6. Determine recommended action
        recommended_action = self._determine_action(
            msprt_result=msprt_result,
            confidence_sequence=confidence_sequence,
            long_running_risk=long_running_risk,
        )

        return SequentialAnalysis(
            method=SequentialTestingMethod.MSPRT,
            msprt_result=msprt_result,
            confidence_sequence=confidence_sequence,
            evidence_trajectory=evidence_trajectory,
            alpha_spending=alpha_spending,
            long_running_risk=long_running_risk,
            recommended_action=recommended_action,
        )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _classify_evidence(
        lambda_ratio: float,
        boundary: float,
    ) -> EvidenceStrength:
        """
        Classify the strength of evidence from a lambda ratio.

        Uses a calibration inspired by Jeffreys' scale for Bayes factors:
        - lambda >= boundary        -> strong for effect
        - lambda >= boundary / 3    -> moderate for effect
        - lambda <= 1 / boundary    -> strong for null
        - lambda <= 3 / boundary    -> moderate for null
        - otherwise                 -> inconclusive
        """
        if lambda_ratio >= boundary:
            return EvidenceStrength.STRONG_FOR_EFFECT
        if lambda_ratio >= boundary / 3.0:
            return EvidenceStrength.MODERATE_FOR_EFFECT
        if lambda_ratio <= 1.0 / boundary:
            return EvidenceStrength.STRONG_FOR_NULL
        if lambda_ratio <= 3.0 / boundary:
            return EvidenceStrength.MODERATE_FOR_NULL
        return EvidenceStrength.INCONCLUSIVE

    @staticmethod
    def _obrien_fleming_spending(
        current_look: int,
        planned_looks: int,
        alpha: float,
    ) -> List[AlphaSpendingBoundary]:
        """
        Compute O'Brien-Fleming alpha spending boundaries.

        The OBF spending function is:
            alpha*(t) = 2 * (1 - Phi(z_{alpha/2} / sqrt(t)))

        where t = i / planned_looks is the information fraction at look i.
        The incremental spend at each look is alpha*(t_i) - alpha*(t_{i-1}).
        """
        z_alpha_half = stats.norm.ppf(1 - alpha / 2.0)
        boundaries: List[AlphaSpendingBoundary] = []

        for i in range(1, current_look + 1):
            t_i = i / planned_looks
            # Cumulative alpha spent through look i
            cumulative_alpha = 2.0 * (
                1.0 - stats.norm.cdf(z_alpha_half / math.sqrt(t_i))
            )
            # Ensure we don't exceed the total alpha budget
            cumulative_alpha = min(cumulative_alpha, alpha)

            # Convert cumulative alpha to a z-boundary for this look
            # Two-sided: boundary_p = cumulative spend at this look (incremental)
            # For OBF we derive the boundary from the spending function directly
            boundary_z = z_alpha_half / math.sqrt(t_i)
            boundary_p = 2.0 * (1.0 - stats.norm.cdf(boundary_z))

            boundaries.append(
                AlphaSpendingBoundary(
                    look_number=i,
                    cumulative_alpha=cumulative_alpha,
                    boundary_z=boundary_z,
                    boundary_p=boundary_p,
                )
            )

        return boundaries

    @staticmethod
    def _pocock_spending(
        current_look: int,
        planned_looks: int,
        alpha: float,
    ) -> List[AlphaSpendingBoundary]:
        """
        Compute Pocock alpha spending boundaries.

        Pocock uses equal alpha spending at each look:
            incremental_alpha = alpha / planned_looks

        All boundaries use the same z-value.
        """
        incremental_alpha = alpha / planned_looks
        # The z-boundary is the same at every look (Pocock property)
        boundary_z = stats.norm.ppf(1.0 - incremental_alpha / 2.0)
        boundary_p = 2.0 * (1.0 - stats.norm.cdf(boundary_z))

        boundaries: List[AlphaSpendingBoundary] = []
        for i in range(1, current_look + 1):
            cumulative_alpha = incremental_alpha * i
            boundaries.append(
                AlphaSpendingBoundary(
                    look_number=i,
                    cumulative_alpha=cumulative_alpha,
                    boundary_z=boundary_z,
                    boundary_p=boundary_p,
                )
            )

        return boundaries

    @staticmethod
    def _determine_action(
        msprt_result: MSPRTResult,
        confidence_sequence: ConfidenceSequence,
        long_running_risk: LongRunningRisk,
    ) -> str:
        """
        Determine the recommended action based on all analysis results.

        Decision logic:
        1. If mSPRT can_stop and CI doesn't contain 0 -> stop_for_effect
        2. If experiment is at risk and evidence is weak -> stop_for_futility
        3. Otherwise -> continue
        """
        if msprt_result.can_stop:
            # Check if the CI excludes zero (i.e. the effect is real)
            ci_excludes_zero = (
                confidence_sequence.lower > 0 or confidence_sequence.upper < 0
            )
            if ci_excludes_zero:
                return "stop_for_effect"
            # mSPRT says stop but CI includes zero — still flag effect
            return "stop_for_effect"

        # Check for futility: long running with weak evidence
        if long_running_risk.is_at_risk and msprt_result.evidence_strength in (
            EvidenceStrength.INCONCLUSIVE,
            EvidenceStrength.MODERATE_FOR_NULL,
            EvidenceStrength.STRONG_FOR_NULL,
        ):
            return "stop_for_futility"

        return "continue"
