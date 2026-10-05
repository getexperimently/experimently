"""
EP-021 Sequential Testing Service.

Implements continuous monitoring of experiments using sequential statistical
methods that maintain valid error rates even with repeated peeking.

Key methods:
- mSPRT (mixture Sequential Probability Ratio Test)
- Always-valid confidence intervals (confidence sequences)
- Evidence trajectory tracking
- Long-running experiment risk detection (advisory: ``at_risk``)

There is no group-sequential (alpha-spending) mode: ``alpha_spending`` is always
an empty list.  The O'Brien-Fleming and Pocock boundaries this service used to
report did not hold their stated significance level (#232), and nothing counted
the looks they were indexed by.  The stop/continue decision is mSPRT alone,
which stays valid however often the results are read.
"""

import logging
import math
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# log of the largest finite double: the mSPRT evidence ratio is capped here so
# it always serialises as a finite JSON number.
_LOG_FLOAT_MAX = math.log(sys.float_info.max)


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
    """A single boundary in an alpha spending schedule.

    Kept as the element type of ``SequentialAnalysis.alpha_spending``, which is
    always empty until a group-sequential mode exists.
    """

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
    alpha_spending: List[AlphaSpendingBoundary]  # always [] (see module docstring)
    long_running_risk: Optional[LongRunningRisk]
    # One of "stop_for_effect", "stop_for_futility", "continue".  This service
    # emits only "stop_for_effect" and "continue": running long is not evidence
    # of no effect, so it is reported as ``at_risk`` instead.
    recommended_action: str

    @property
    def at_risk(self) -> Optional[bool]:
        """Advisory: the experiment is running long or collecting slowly."""
        if self.long_running_risk is None:
            return None
        return self.long_running_risk.is_at_risk


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SequentialTestingService:
    """
    Service for sequential testing of A/B experiments.

    Provides early stopping decisions using the mSPRT framework, with
    always-valid confidence intervals alongside.
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

        # Agresti-Caffo variance of the difference (#854): positive for any
        # counts with n > 0, and the same V the confidence sequence uses.
        V_n = self.difference_variance(
            control_successes, control_total, treatment_successes, treatment_total
        )

        Z_n = delta / math.sqrt(V_n)

        # mSPRT lambda: mixture likelihood ratio with Gaussian(0, tau^2) prior
        # Lambda_n = sqrt(V_n / (V_n + tau^2)) * exp(tau^2 * Z_n^2 / (2*(V_n + tau^2)))
        #
        # Computed in log space and capped at the largest finite double before
        # exp: an overwhelming difference (|Z| above about 38 once V is much
        # smaller than tau^2) would otherwise not fit in a float. The cap cuts
        # nothing that was finite before, and the capped value is still above
        # 1/alpha for any usable alpha, so it can stop.
        ratio = V_n / (V_n + tau_squared)
        log_lambda = 0.5 * math.log(ratio) + tau_squared * Z_n**2 / (
            2.0 * (V_n + tau_squared)
        )
        lambda_ratio = math.exp(min(log_lambda, _LOG_FLOAT_MAX))

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

        The interval is the inversion of the same normal-mixture mSPRT that
        ``compute_msprt`` runs (Johari et al. 2017; Howard et al. 2021): it is
        every effect delta for which the mixture likelihood ratio of the data
        against delta stays below 1/alpha.  With the Agresti-Caffo variance V
        of the difference in proportions (``difference_variance``) and the
        mixing variance tau^2 that gives

            delta_hat +/- sqrt( V (V + tau^2) / tau^2
                                * (2 ln(1/alpha) + ln((V + tau^2) / V)) )

        Because V and tau^2 are the ones ``compute_msprt`` uses, 0 lies
        outside this interval exactly when Lambda >= 1/alpha, i.e. exactly when
        ``can_stop`` is true.  The half-width falls like sqrt(V log(1/V)), so
        the interval keeps narrowing as data arrives.  The result is
        intersected with [-1, 1], the range of a difference in proportions.

        The centre is the observed difference delta_hat; only the variance is
        Agresti-Caffo.  The plug-in variance p(1-p)/n used before #854 is too
        small when one arm is small and its rate low (it is 0 for an arm with
        no conversions), so the interval was too narrow and A/A experiments
        were stopped far more often than alpha at unequal splits.  The
        Agresti-Caffo variance is positive for any counts, so an arm with all
        0s or all 1s still gets a finite interval.

        When there is no data in an arm (n = 0), nothing bounds the effect: the
        interval is the whole range a difference in proportions can take,
        [-1, 1].  ``compute_msprt`` reports Lambda = 1 (cannot stop) in the
        same case, so the two still agree.

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
        unbounded = ConfidenceSequence(
            lower=-1.0,
            upper=1.0,
            width=2.0,
            sample_size=sample_size,
        )

        if control_total == 0 or treatment_total == 0:
            return unbounded

        p_c = control_successes / control_total
        p_t = treatment_successes / treatment_total
        delta_hat = p_t - p_c

        V_n = self.difference_variance(
            control_successes, control_total, treatment_successes, treatment_total
        )

        margin = self.confidence_sequence_half_width(V_n, tau_squared, alpha)

        # A difference of proportions lies in [-1, 1], so the interval is
        # intersected with it.  0 and the true delta are always inside
        # [-1, 1], so this changes neither coverage nor the agreement with
        # ``can_stop``; it only stops a small-sample interval being reported
        # as, say, [-7.5, 7.5].
        lower = max(delta_hat - margin, -1.0)
        upper = min(delta_hat + margin, 1.0)
        width = upper - lower

        return ConfidenceSequence(
            lower=lower,
            upper=upper,
            width=width,
            sample_size=sample_size,
        )

    @staticmethod
    def difference_variance(
        control_successes: int,
        control_total: int,
        treatment_successes: int,
        treatment_total: int,
    ) -> float:
        """Agresti-Caffo variance of ``p_t - p_c``, for n > 0 in both arms.

        One success and one failure are added to each arm,
        ``p~ = (x + 1) / (n + 2)``, and the variance is
        ``p~_c (1 - p~_c) / (n_c + 2) + p~_t (1 - p~_t) / (n_t + 2)``,
        which is positive for any counts.  ``compute_msprt`` and
        ``compute_always_valid_ci`` both use it, so 0 lies outside the
        interval exactly when ``can_stop`` is true.
        """
        p_c = (control_successes + 1) / (control_total + 2)
        p_t = (treatment_successes + 1) / (treatment_total + 2)
        return p_c * (1 - p_c) / (control_total + 2) + p_t * (1 - p_t) / (
            treatment_total + 2
        )

    @staticmethod
    def confidence_sequence_half_width(
        variance: float, tau_squared: float, alpha: float
    ) -> float:
        """Half-width of the normal-mixture confidence sequence, for V > 0.

        sqrt( V (V + tau^2) / tau^2 * (2 ln(1/alpha) + ln((V + tau^2) / V)) ).
        """
        v_plus_tau = variance + tau_squared
        return math.sqrt(
            variance
            * v_plus_tau
            / tau_squared
            * (2.0 * math.log(1.0 / alpha) + math.log(v_plus_tau / variance))
        )

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
                "Experiment has exceeded 1.5x its expected duration. Running long "
                "is not evidence of no effect; consider increasing traffic "
                "allocation or revisiting the expected duration."
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
                - alpha (float): Significance level; the mSPRT boundary is 1/alpha
                - actual_days (int): Days the experiment has been running
                - expected_days (int): Expected experiment duration in days
                - required_sample_size (int): Total required sample size
                Any other key (``spending_function``, ``planned_looks``,
                ``current_look``) is ignored: no alpha-spending table is computed.

        Returns:
            SequentialAnalysis with all component results and recommendation.
        """
        tau_squared = config.get("tau_squared", 0.001)
        alpha = config.get("alpha", 0.05)
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

        # 3. Long-running risk (advisory; never a stopping rule)
        total_sample = control_total + treatment_total
        long_running_risk = self.estimate_long_running_risk(
            actual_days=actual_days,
            expected_days=expected_days,
            current_sample_size=total_sample,
            required_sample_size=required_sample_size,
        )

        # 4. Evidence trajectory (single point for current data)
        evidence_trajectory = [
            EvidencePoint(
                sample_size=total_sample,
                lambda_ratio=msprt_result.lambda_ratio,
                always_valid_p_value=msprt_result.always_valid_p_value,
                can_stop=msprt_result.can_stop,
            )
        ]

        # 5. Determine recommended action (mSPRT alone)
        recommended_action = self._determine_action(msprt_result=msprt_result)

        return SequentialAnalysis(
            method=SequentialTestingMethod.MSPRT,
            msprt_result=msprt_result,
            confidence_sequence=confidence_sequence,
            evidence_trajectory=evidence_trajectory,
            alpha_spending=[],
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
    def _determine_action(msprt_result: MSPRTResult) -> str:
        """
        Determine the recommended action from the mSPRT result.

        - mSPRT crosses its boundary (Lambda >= 1/alpha) -> ``stop_for_effect``
        - otherwise -> ``continue``

        ``stop_for_futility`` stays in the response's value set but is not
        emitted: the mSPRT has no futility boundary, and an experiment that
        runs long is reported through the advisory ``at_risk`` flag instead.
        """
        if msprt_result.can_stop:
            return "stop_for_effect"
        return "continue"
