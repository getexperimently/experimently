"""
Post-Stratification Variance Reduction Service — EP-043.

Implements the Horvitz-Thompson post-stratification estimator for reducing
variance in experiment effect estimates. Post-stratification is more powerful
than CUPED when treatment and control group sizes differ within strata, because
it reweights estimates to match the population stratum proportions.

Reference:
    Cochran, W. G. (1977). Sampling Techniques (3rd ed.). Wiley.
    Deng, A., Xu, Y., Kohavi, R., & Walker, T. (2013). Improving the sensitivity
    of online controlled experiments by utilizing pre-experiment data. WSDM 2013.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class PostStratResult:
    """Result of a post-stratification analysis.

    Attributes:
        metric_name: Name of the metric column analysed.
        control_mean: Post-stratification-weighted mean for the control group.
        treatment_mean: Post-stratification-weighted mean for the treatment group.
        effect_size: treatment_mean - control_mean (absolute effect).
        effect_size_relative: effect_size / |control_mean| (relative lift).
        variance_reduction: Percentage variance reduction vs. the naive (unstratified)
            estimator. Positive means reduction; negative means inflation.
        adjusted_se: Standard error of the post-stratified effect estimate.
        p_value: Two-tailed p-value from a z-test on the adjusted effect.
        confidence_interval: (lower, upper) two-sided CI at the requested alpha level.
        n_strata: Number of unique strata used.
        strata_sizes: Mapping of stratum label → total count across both groups.
    """

    metric_name: str
    control_mean: float
    treatment_mean: float
    effect_size: float
    effect_size_relative: float
    variance_reduction: float
    adjusted_se: float
    p_value: float
    confidence_interval: Tuple[float, float]
    n_strata: int
    strata_sizes: Dict[str, int]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PostStratificationService:
    """
    Service for computing post-stratification variance-reduced effect estimates.

    The Horvitz-Thompson estimator reweights stratum-specific means by the
    *population* stratum proportions (estimated from the combined control +
    treatment sample), removing bias introduced when stratum proportions differ
    between the two groups.

    Usage::

        svc = PostStratificationService()
        result = svc.compute(
            control_data=control_df,   # DataFrame with metric_value + stratum cols
            treatment_data=treatment_df,
            stratum_cols=["country", "device_type"],
        )
    """

    # Minimum number of observations required per stratum per group
    MIN_STRATUM_SIZE = 2

    def compute(
        self,
        control_data: pd.DataFrame,
        treatment_data: pd.DataFrame,
        stratum_cols: List[str],
        metric_col: str = "metric_value",
        alpha: float = 0.05,
    ) -> PostStratResult:
        """
        Compute the post-stratified treatment effect estimate.

        Args:
            control_data: DataFrame for the control group. Must contain
                ``metric_col`` and all columns in ``stratum_cols``.
            treatment_data: DataFrame for the treatment group. Same schema.
            stratum_cols: Column name(s) used to define strata. Multiple columns
                create interaction strata (e.g. ["country", "device"]).
            metric_col: Name of the numeric outcome column. Default "metric_value".
            alpha: Significance level for confidence intervals. Default 0.05.

        Returns:
            PostStratResult with weighted estimates and variance statistics.

        Raises:
            ValueError: If data is empty, columns are missing, or any stratum
                has fewer than MIN_STRATUM_SIZE observations in either group.
        """
        # --- Input validation ---
        if len(control_data) == 0:
            raise ValueError("Empty control data: no observations provided")
        if len(treatment_data) == 0:
            raise ValueError("Empty treatment data: no observations provided")

        # Validate stratum columns exist in both DataFrames
        for col in stratum_cols:
            if col not in control_data.columns:
                raise KeyError(
                    f"Stratum column '{col}' not found in control_data columns: "
                    f"{list(control_data.columns)}"
                )
            if col not in treatment_data.columns:
                raise KeyError(
                    f"Stratum column '{col}' not found in treatment_data columns: "
                    f"{list(treatment_data.columns)}"
                )

        # Validate metric column
        if metric_col not in control_data.columns:
            raise KeyError(
                f"Metric column '{metric_col}' not found in control_data"
            )
        if metric_col not in treatment_data.columns:
            raise KeyError(
                f"Metric column '{metric_col}' not found in treatment_data"
            )

        # Create stratum labels (combine stratum cols into a single label string)
        control_df = control_data.copy()
        treatment_df = treatment_data.copy()

        if len(stratum_cols) == 1:
            control_df["_stratum"] = control_df[stratum_cols[0]].astype(str)
            treatment_df["_stratum"] = treatment_df[stratum_cols[0]].astype(str)
        else:
            control_df["_stratum"] = (
                control_df[stratum_cols].astype(str).agg("_".join, axis=1)
            )
            treatment_df["_stratum"] = (
                treatment_df[stratum_cols].astype(str).agg("_".join, axis=1)
            )

        # Combined dataset for population proportion estimation
        combined = pd.concat([control_df, treatment_df], ignore_index=True)
        all_strata = sorted(combined["_stratum"].unique())
        N_total = len(combined)

        # Validate minimum stratum sizes
        for stratum in all_strata:
            n_ctrl = (control_df["_stratum"] == stratum).sum()
            n_trt = (treatment_df["_stratum"] == stratum).sum()
            if n_ctrl < self.MIN_STRATUM_SIZE:
                raise ValueError(
                    f"Stratum '{stratum}' has only {n_ctrl} control observations "
                    f"(minimum required: {self.MIN_STRATUM_SIZE}). "
                    "Merge or remove sparse strata before running post-stratification."
                )
            if n_trt < self.MIN_STRATUM_SIZE:
                raise ValueError(
                    f"Stratum '{stratum}' has only {n_trt} treatment observations "
                    f"(minimum required: {self.MIN_STRATUM_SIZE}). "
                    "Merge or remove sparse strata before running post-stratification."
                )

        # --- Horvitz-Thompson weighted estimator ---
        # Population stratum weights: W_h = N_h / N
        # Weighted mean for group g: Ȳ_g = Σ_h W_h * ȳ_{g,h}
        # Weighted variance for group g: Var(Ȳ_g) = Σ_h W_h² * (s²_{g,h} / n_{g,h})

        ctrl_vals = control_df[metric_col].values.astype(float)
        trt_vals = treatment_df[metric_col].values.astype(float)

        # Raw (unstratified) variances for variance-reduction computation
        raw_ctrl_var = float(np.var(ctrl_vals, ddof=1)) if len(ctrl_vals) > 1 else 0.0

        # Per-stratum statistics
        strata_sizes: Dict[str, int] = {}
        weighted_ctrl_mean = 0.0
        weighted_trt_mean = 0.0
        weighted_ctrl_var = 0.0   # Cochran's formula: Σ W_h² * s²_{ctrl,h} / n_{ctrl,h}
        weighted_trt_var = 0.0    # Cochran's formula: Σ W_h² * s²_{trt,h}  / n_{trt,h}

        for stratum in all_strata:
            ctrl_mask = control_df["_stratum"] == stratum
            trt_mask = treatment_df["_stratum"] == stratum

            ctrl_h = control_df.loc[ctrl_mask, metric_col].values.astype(float)
            trt_h = treatment_df.loc[trt_mask, metric_col].values.astype(float)

            n_ctrl_h = len(ctrl_h)
            n_trt_h = len(trt_h)
            N_h = (combined["_stratum"] == stratum).sum()

            # Population stratum weight
            W_h = N_h / N_total

            # Stratum-specific sample means
            mean_ctrl_h = float(ctrl_h.mean())
            mean_trt_h = float(trt_h.mean())

            # Stratum-specific sample variances (ddof=1)
            var_ctrl_h = float(np.var(ctrl_h, ddof=1)) if n_ctrl_h > 1 else 0.0
            var_trt_h = float(np.var(trt_h, ddof=1)) if n_trt_h > 1 else 0.0

            weighted_ctrl_mean += W_h * mean_ctrl_h
            weighted_trt_mean += W_h * mean_trt_h

            # Cochran's variance formula for stratified estimator
            weighted_ctrl_var += (W_h ** 2) * (var_ctrl_h / n_ctrl_h)
            weighted_trt_var += (W_h ** 2) * (var_trt_h / n_trt_h)

            strata_sizes[stratum] = int(N_h)

        # Effect size (Horvitz-Thompson)
        effect_size = weighted_trt_mean - weighted_ctrl_mean

        # Relative effect size
        if abs(weighted_ctrl_mean) > 1e-12:
            effect_size_relative = effect_size / abs(weighted_ctrl_mean)
        else:
            effect_size_relative = 0.0

        # Standard error of the HT effect estimate
        se = math.sqrt(max(weighted_ctrl_var + weighted_trt_var, 1e-24))

        # Two-tailed z-test
        z_stat = effect_size / se
        p_value = float(2.0 * (1.0 - stats.norm.cdf(abs(z_stat))))
        p_value = min(1.0, max(0.0, p_value))

        # Confidence interval
        z_crit = float(stats.norm.ppf(1.0 - alpha / 2.0))
        ci_lower = effect_size - z_crit * se
        ci_upper = effect_size + z_crit * se

        # Variance reduction vs. naive (unstratified) estimator
        # Naive SE² = Var(ctrl) / n_ctrl + Var(trt) / n_trt
        n_ctrl = len(ctrl_vals)
        n_trt = len(trt_vals)
        raw_trt_var = float(np.var(trt_vals, ddof=1)) if len(trt_vals) > 1 else 0.0
        raw_se_sq = (
            (raw_ctrl_var / n_ctrl if n_ctrl > 0 else 0.0)
            + (raw_trt_var / n_trt if n_trt > 0 else 0.0)
        )
        poststrat_se_sq = weighted_ctrl_var + weighted_trt_var

        variance_reduction = self._compute_variance_reduction(raw_se_sq, poststrat_se_sq)

        return PostStratResult(
            metric_name=metric_col,
            control_mean=float(weighted_ctrl_mean),
            treatment_mean=float(weighted_trt_mean),
            effect_size=float(effect_size),
            effect_size_relative=float(effect_size_relative),
            variance_reduction=float(variance_reduction),
            adjusted_se=float(se),
            p_value=float(p_value),
            confidence_interval=(float(ci_lower), float(ci_upper)),
            n_strata=len(all_strata),
            strata_sizes=strata_sizes,
        )

    @staticmethod
    def _compute_variance_reduction(raw_var: float, poststrat_var: float) -> float:
        """
        Compute percentage variance reduction of post-stratification vs. raw estimator.

        Args:
            raw_var: Variance (or squared SE) of the naive (unstratified) estimator.
            poststrat_var: Variance (or squared SE) of the post-stratified estimator.

        Returns:
            Percentage reduction: (raw - poststrat) / raw * 100.
            Returns 0.0 when raw_var is zero (no reference to compare against).
        """
        if raw_var <= 0.0:
            return 0.0
        return (raw_var - poststrat_var) / raw_var * 100.0
