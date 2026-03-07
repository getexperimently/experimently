"""
Pre-Experiment Statistical Power Calculator Service (EP-056).

Provides:
- Sample size computation for proportions and means
- Minimum detectable effect (MDE) estimation given a fixed sample
- Runtime estimation given daily traffic
- Power curve generation for frontend visualisation
- Bonferroni correction for multi-variant experiments

All calculations use scipy.stats for numerical accuracy.
"""

import math
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from scipy.stats import norm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SampleSizeResult:
    """Result of a sample size computation."""
    per_variant: int
    total: int
    alpha: float
    power: float
    baseline_rate: float
    mde_absolute: float
    mde_relative: float
    confidence_level: float
    runtime_days: Optional[float]
    n_variants: int
    two_tailed: bool
    metric_type: str


@dataclass
class MDEResult:
    """Result of an MDE computation."""
    mde_absolute: float
    mde_relative: float
    per_variant_sample: int
    total_sample: int
    alpha: float
    power: float
    n_variants: int
    two_tailed: bool


@dataclass
class RuntimeEstimate:
    """Estimated runtime to reach significance."""
    days_to_significance: float
    weeks_to_significance: float
    daily_traffic_per_variant: int
    confidence_interval_days: Tuple[float, float]


@dataclass
class PowerCurvePoint:
    """A single point on the sample-size vs. effect-size power curve."""
    effect_size_relative: float
    sample_size_per_variant: int
    is_current_target: bool


# ---------------------------------------------------------------------------
# Default effect size grid for power curves (relative lifts)
# ---------------------------------------------------------------------------

_DEFAULT_EFFECT_SIZES = [
    0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.12, 0.15,
    0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50,
]


# ---------------------------------------------------------------------------
# PowerCalculatorService
# ---------------------------------------------------------------------------

class PowerCalculatorService:
    """
    Pre-experiment statistical power analysis.

    Uses scipy.stats for exact z-score based calculations.
    Supports proportion metrics (binary outcomes), mean metrics
    (continuous outcomes), and multi-variant Bonferroni correction.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_sample_size(
        self,
        baseline_rate: float,
        minimum_detectable_effect: float,
        alpha: float = 0.05,
        power: float = 0.80,
        n_variants: int = 2,
        two_tailed: bool = True,
        metric_type: str = "proportion",
        baseline_std: Optional[float] = None,
        daily_traffic: Optional[int] = None,
        traffic_allocation: float = 1.0,
    ) -> SampleSizeResult:
        """
        Compute the required sample size per variant.

        Parameters
        ----------
        baseline_rate:
            Current metric rate (0 < baseline_rate < 1). For metric_type='mean'
            this is the baseline mean value normalised to [0,1].
        minimum_detectable_effect:
            Desired minimum detectable relative effect (e.g. 0.10 = 10% lift).
            Must be in (0, 1).
        alpha:
            Type I error rate (false positive rate). Must be in (0, 0.5).
        power:
            Desired statistical power (1 - beta). Must be in (0, 1).
        n_variants:
            Total number of variants including control (>= 2).
            When > 2, Bonferroni correction is applied (alpha / (n_variants - 1)).
        two_tailed:
            Use a two-tailed test (recommended; reduces required power by ~20%
            for one-tailed).
        metric_type:
            'proportion' | 'mean' | 'ratio'.
        baseline_std:
            Standard deviation of the baseline metric (required when
            metric_type='mean').
        daily_traffic:
            Optional total daily users entering the experiment.
        traffic_allocation:
            Fraction of traffic participating in the experiment (0, 1].

        Returns
        -------
        SampleSizeResult
        """
        self._validate_inputs(
            baseline_rate=baseline_rate,
            mde_relative=minimum_detectable_effect,
            alpha=alpha,
            power=power,
            metric_type=metric_type,
            baseline_std=baseline_std,
        )

        # Bonferroni correction: n_comparisons = number of treatment variants
        n_comparisons = max(1, n_variants - 1)
        corrected_alpha = alpha / n_comparisons

        mde_absolute = baseline_rate * minimum_detectable_effect
        p1 = baseline_rate
        p2 = baseline_rate + mde_absolute

        if metric_type == "proportion":
            n_per_variant = self._sample_size_proportions(
                p1=p1,
                p2=p2,
                alpha=corrected_alpha,
                power=power,
                two_tailed=two_tailed,
            )
        elif metric_type in ("mean", "ratio"):
            n_per_variant = self._sample_size_means(
                mean1=p1,
                mean2=p2,
                std=baseline_std,  # type: ignore[arg-type]
                alpha=corrected_alpha,
                power=power,
                two_tailed=two_tailed,
            )
        else:
            raise ValueError(f"Unknown metric_type: {metric_type}")

        total = n_per_variant * n_variants

        # Runtime estimate
        runtime_days: Optional[float] = None
        if daily_traffic is not None and daily_traffic > 0:
            runtime_est = self.compute_runtime_estimate(
                required_sample_size=n_per_variant,
                daily_traffic=daily_traffic,
                traffic_allocation=traffic_allocation,
                n_variants=n_variants,
            )
            runtime_days = runtime_est.days_to_significance

        return SampleSizeResult(
            per_variant=n_per_variant,
            total=total,
            alpha=alpha,
            power=power,
            baseline_rate=baseline_rate,
            mde_absolute=mde_absolute,
            mde_relative=minimum_detectable_effect,
            confidence_level=1.0 - alpha,
            runtime_days=runtime_days,
            n_variants=n_variants,
            two_tailed=two_tailed,
            metric_type=metric_type,
        )

    def compute_mde(
        self,
        sample_size_per_variant: int,
        baseline_rate: float,
        alpha: float = 0.05,
        power: float = 0.80,
        n_variants: int = 2,
        two_tailed: bool = True,
    ) -> MDEResult:
        """
        Given a fixed sample size, find the smallest detectable relative effect.

        Uses binary search between 0.001 and 0.999 relative effect sizes.

        Parameters
        ----------
        sample_size_per_variant:
            Number of samples available per variant.
        baseline_rate:
            Current baseline proportion/rate (0 < x < 1).
        alpha:
            Type I error rate.
        power:
            Desired statistical power.
        n_variants:
            Total variants including control.
        two_tailed:
            Whether to use a two-tailed test.

        Returns
        -------
        MDEResult
        """
        self._validate_basic(alpha=alpha, power=power, baseline_rate=baseline_rate)
        if sample_size_per_variant <= 0:
            raise ValueError("sample_size_per_variant must be > 0")

        # Binary search for the MDE
        low, high = 0.001, 0.999
        n_comparisons = max(1, n_variants - 1)
        corrected_alpha = alpha / n_comparisons

        for _ in range(60):
            mid = (low + high) / 2
            mde_abs = baseline_rate * mid
            p2 = baseline_rate + mde_abs
            if p2 >= 1.0:
                high = mid
                continue
            n_needed = self._sample_size_proportions(
                p1=baseline_rate,
                p2=p2,
                alpha=corrected_alpha,
                power=power,
                two_tailed=two_tailed,
            )
            if n_needed > sample_size_per_variant:
                low = mid
            else:
                high = mid

        mde_relative = (low + high) / 2
        mde_absolute = baseline_rate * mde_relative

        return MDEResult(
            mde_absolute=mde_absolute,
            mde_relative=mde_relative,
            per_variant_sample=sample_size_per_variant,
            total_sample=sample_size_per_variant * n_variants,
            alpha=alpha,
            power=power,
            n_variants=n_variants,
            two_tailed=two_tailed,
        )

    def compute_runtime_estimate(
        self,
        required_sample_size: int,
        daily_traffic: int,
        traffic_allocation: float,
        n_variants: int = 2,
    ) -> RuntimeEstimate:
        """
        Estimate how many days to collect the required sample size.

        Parameters
        ----------
        required_sample_size:
            Sample size required per variant.
        daily_traffic:
            Total daily users eligible for the experiment.
        traffic_allocation:
            Fraction of eligible traffic enrolled (0, 1].
        n_variants:
            Number of variants (traffic is split equally).

        Returns
        -------
        RuntimeEstimate
        """
        if required_sample_size <= 0:
            raise ValueError("required_sample_size must be > 0")
        if daily_traffic <= 0:
            raise ValueError("daily_traffic must be > 0")
        if not (0 < traffic_allocation <= 1.0):
            raise ValueError("traffic_allocation must be in (0, 1]")
        if n_variants < 2:
            raise ValueError("n_variants must be >= 2")

        daily_per_variant = max(1, int(daily_traffic * traffic_allocation / n_variants))
        days = required_sample_size / daily_per_variant
        weeks = days / 7.0

        # 90% CI using Poisson approximation: traffic varies ~±sqrt(n) per day
        # CI width ≈ 1.645 * sqrt(days) / daily_per_variant * required_sample_size / required_sample_size
        # Simplified: CI ≈ days ± 1.645 * sqrt(days)
        ci_half = 1.645 * math.sqrt(days)
        ci_lower = max(0.0, days - ci_half)
        ci_upper = days + ci_half

        return RuntimeEstimate(
            days_to_significance=days,
            weeks_to_significance=weeks,
            daily_traffic_per_variant=daily_per_variant,
            confidence_interval_days=(ci_lower, ci_upper),
        )

    def compute_power_curve(
        self,
        baseline_rate: float,
        alpha: float = 0.05,
        power_target: float = 0.80,
        effect_sizes: Optional[List[float]] = None,
        mde_target: Optional[float] = None,
    ) -> List[PowerCurvePoint]:
        """
        Compute the power curve: for each relative effect size, what sample
        size is required?

        Parameters
        ----------
        baseline_rate:
            Current baseline proportion.
        alpha:
            Type I error rate.
        power_target:
            Target statistical power.
        effect_sizes:
            List of relative effect sizes to evaluate.
            Defaults to _DEFAULT_EFFECT_SIZES.
        mde_target:
            The currently selected MDE. The closest point will be marked
            with is_current_target=True.

        Returns
        -------
        List[PowerCurvePoint] sorted by effect_size_relative ascending.
        """
        self._validate_basic(alpha=alpha, power=power_target, baseline_rate=baseline_rate)

        sizes = effect_sizes if effect_sizes is not None else _DEFAULT_EFFECT_SIZES
        points: List[PowerCurvePoint] = []

        # Find which effect size is closest to the target
        closest_idx: Optional[int] = None
        if mde_target is not None:
            closest_idx = min(
                range(len(sizes)),
                key=lambda i: abs(sizes[i] - mde_target),
            )

        for idx, es in enumerate(sorted(sizes)):
            mde_abs = baseline_rate * es
            p2 = baseline_rate + mde_abs
            if p2 >= 1.0 or mde_abs <= 0:
                continue  # skip invalid points
            try:
                n = self._sample_size_proportions(
                    p1=baseline_rate,
                    p2=p2,
                    alpha=alpha,
                    power=power_target,
                    two_tailed=True,
                )
            except Exception:
                continue

            is_target = (closest_idx is not None) and (idx == closest_idx)
            points.append(
                PowerCurvePoint(
                    effect_size_relative=es,
                    sample_size_per_variant=n,
                    is_current_target=is_target,
                )
            )

        return points

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sample_size_proportions(
        p1: float,
        p2: float,
        alpha: float,
        power: float,
        two_tailed: bool,
    ) -> int:
        """
        Compute the required sample size per group for a two-proportions
        z-test using the exact unpooled formula.

        Formula (Fleiss, 2003):
            n = [z_alpha * sqrt(2 * p_bar * (1 - p_bar))
                 + z_power * sqrt(p1*(1-p1) + p2*(1-p2))]^2
                / (p2 - p1)^2

        Parameters
        ----------
        p1 : baseline proportion
        p2 : treatment proportion
        alpha : type I error rate (already Bonferroni-corrected if needed)
        power : desired power
        two_tailed : whether to use two-tailed alpha

        Returns
        -------
        int : sample size per group (ceiling)
        """
        z_alpha = norm.ppf(1 - alpha / (2 if two_tailed else 1))
        z_power = norm.ppf(power)
        pooled = (p1 + p2) / 2
        delta = abs(p2 - p1)

        if delta == 0:
            raise ValueError("p1 and p2 must differ (delta cannot be zero)")

        n = (
            z_alpha * math.sqrt(2 * pooled * (1 - pooled))
            + z_power * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
        ) ** 2 / delta ** 2

        return math.ceil(n)

    @staticmethod
    def _sample_size_means(
        mean1: float,
        mean2: float,
        std: float,
        alpha: float,
        power: float,
        two_tailed: bool,
    ) -> int:
        """
        Compute the required sample size per group for a two-sample t-test
        (normal approximation with known variance).

        Formula:
            n = 2 * std^2 * (z_alpha + z_power)^2 / (mean2 - mean1)^2
        """
        z_alpha = norm.ppf(1 - alpha / (2 if two_tailed else 1))
        z_power = norm.ppf(power)
        delta = abs(mean2 - mean1)

        if delta == 0:
            raise ValueError("mean1 and mean2 must differ")
        if std <= 0:
            raise ValueError("std must be > 0")

        n = 2 * std ** 2 * (z_alpha + z_power) ** 2 / delta ** 2
        return math.ceil(n)

    @staticmethod
    def _validate_inputs(
        baseline_rate: float,
        mde_relative: float,
        alpha: float,
        power: float,
        metric_type: str,
        baseline_std: Optional[float],
    ) -> None:
        """Validate all inputs and raise ValueError on invalid values."""
        if not (0 < baseline_rate < 1):
            raise ValueError(
                f"baseline_rate must be in (0, 1), got {baseline_rate}"
            )
        if mde_relative <= 0:
            raise ValueError(
                f"minimum_detectable_effect must be > 0, got {mde_relative}"
            )
        if mde_relative >= 1.0:
            raise ValueError(
                f"minimum_detectable_effect must be < 1.0, got {mde_relative}"
            )
        if not (0 < alpha < 0.5):
            raise ValueError(f"alpha must be in (0, 0.5), got {alpha}")
        if not (0 < power < 1):
            raise ValueError(f"power must be in (0, 1), got {power}")
        if metric_type not in ("proportion", "mean", "ratio"):
            raise ValueError(
                f"metric_type must be 'proportion', 'mean', or 'ratio', got '{metric_type}'"
            )
        if metric_type == "mean" and baseline_std is None:
            raise ValueError(
                "baseline_std is required when metric_type='mean'"
            )
        # Validate that treatment rate is a valid probability
        mde_abs = baseline_rate * mde_relative
        p2 = baseline_rate + mde_abs
        if p2 >= 1.0:
            raise ValueError(
                f"baseline_rate + mde_absolute = {p2:.4f} >= 1.0. "
                "Reduce baseline_rate or minimum_detectable_effect."
            )

    @staticmethod
    def _validate_basic(
        alpha: float,
        power: float,
        baseline_rate: float,
    ) -> None:
        """Lightweight validation for MDE/curve endpoints."""
        if not (0 < baseline_rate < 1):
            raise ValueError(
                f"baseline_rate must be in (0, 1), got {baseline_rate}"
            )
        if not (0 < alpha < 0.5):
            raise ValueError(f"alpha must be in (0, 0.5), got {alpha}")
        if not (0 < power < 1):
            raise ValueError(f"power must be in (0, 1), got {power}")
