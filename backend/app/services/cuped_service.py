"""
CUPED Variance Reduction Service — Issue #21.

Implements CUPED (Controlled-experiment Using Pre-Experiment Data) and
Winsorization to reduce variance and reach statistical significance faster.

Reference:
  Deng, A., Xu, Y., Kohavi, R., & Walker, T. (2013). Improving the sensitivity
  of online controlled experiments by utilizing pre-experiment data.
  WSDM 2013.
"""

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np
from scipy import stats


# ---------------------------------------------------------------------------
# CupedEffect — result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CupedEffect:
    """Result of a CUPED variance-reduction analysis.

    Attributes:
        adjusted_control_mean: Mean of the CUPED-adjusted control observations.
        adjusted_treatment_mean: Mean of the CUPED-adjusted treatment observations.
        adjusted_effect: adjusted_treatment_mean - adjusted_control_mean.
        adjusted_se: Pooled standard error of the adjusted effect.
        adjusted_p_value: Two-tailed p-value from a z-test on the adjusted effect.
        adjusted_ci: 95% confidence interval (lower, upper) for the adjusted effect.
        variance_reduction_pct: Percentage of variance removed by CUPED in the
            control group, relative to the raw control variance.
            Formula: (1 - Var(adjusted_control) / Var(raw_control)) * 100
        theta: OLS coefficient used for the CUPED adjustment (Cov(Y,X) / Var(X)).
    """

    adjusted_control_mean: float
    adjusted_treatment_mean: float
    adjusted_effect: float
    adjusted_se: float
    adjusted_p_value: float
    adjusted_ci: Tuple[float, float]
    variance_reduction_pct: float
    theta: float


# ---------------------------------------------------------------------------
# CupedService
# ---------------------------------------------------------------------------


class CupedService:
    """Service for CUPED and Winsorization variance-reduction methods."""

    # ------------------------------------------------------------------
    # Core CUPED primitives
    # ------------------------------------------------------------------

    @staticmethod
    def compute_theta(control_Y: np.ndarray, control_X: np.ndarray) -> float:
        """Compute the OLS coefficient for CUPED adjustment.

        θ = Cov(Y, X) / Var(X)

        When X has zero variance (constant covariate) θ is set to 0.0
        to indicate that no adjustment should be applied.

        Args:
            control_Y: Outcome metric observations from the control group.
            control_X: Pre-experiment covariate observations for the same users.

        Returns:
            The OLS regression coefficient θ as a Python float.
        """
        X = np.asarray(control_X, dtype=float)
        Y = np.asarray(control_Y, dtype=float)

        var_x = np.var(X, ddof=1) if len(X) > 1 else 0.0
        if var_x == 0.0:
            return 0.0

        # Using np.cov with ddof=1 (sample covariance) for consistency
        cov_matrix = np.cov(Y, X, ddof=1)
        cov_yx = cov_matrix[0, 1]
        return float(cov_yx / var_x)

    @staticmethod
    def apply_cuped(
        Y: np.ndarray,
        X: np.ndarray,
        theta: float,
        E_X: float,
    ) -> np.ndarray:
        """Apply the CUPED transformation to a set of observations.

        Y_cuped = Y - θ * (X - E[X])

        Args:
            Y: Outcome metric observations.
            X: Pre-experiment covariate observations.
            theta: OLS coefficient from compute_theta.
            E_X: Population mean of the covariate (typically estimated from the
                 pooled data across control and treatment groups).

        Returns:
            CUPED-adjusted observations as a numpy array.
        """
        Y = np.asarray(Y, dtype=float)
        X = np.asarray(X, dtype=float)
        return Y - theta * (X - E_X)

    # ------------------------------------------------------------------
    # Winsorization
    # ------------------------------------------------------------------

    @staticmethod
    def apply_winsorization(
        values: np.ndarray,
        percentile: float = 99.0,
    ) -> np.ndarray:
        """Clip metric values at the given upper percentile (Winsorization).

        Values above the specified percentile are clipped to the percentile
        value.  Values at or below the percentile are left unchanged.

        Args:
            values: Array of metric observations to Winsorize.
            percentile: Upper percentile threshold (0–100). Default 99.0.

        Returns:
            Winsorized numpy array of the same shape as *values*.
        """
        values = np.asarray(values, dtype=float)
        upper = np.percentile(values, percentile)
        return np.clip(values, a_min=None, a_max=upper)

    # ------------------------------------------------------------------
    # Full CUPED pipeline
    # ------------------------------------------------------------------

    @staticmethod
    def compute_cuped_effect(
        control_Y: np.ndarray,
        control_X: np.ndarray,
        treatment_Y: np.ndarray,
        treatment_X: np.ndarray,
        alpha: float = 0.05,
    ) -> CupedEffect:
        """Run the full CUPED pipeline and return a CupedEffect result.

        Pipeline:
          1. Estimate θ from the control group (Cov(Y,X) / Var(X)).
          2. Compute E[X] from the pooled covariate observations.
          3. Adjust both groups: Y_adj = Y - θ*(X - E[X]).
          4. Compute the adjusted effect (difference of adjusted means).
          5. Compute the pooled SE of the adjusted effect.
          6. Perform a two-tailed z-test to obtain p-value and CI.
          7. Compute variance reduction percentage for the control group.

        Args:
            control_Y: Outcome metric observations for the control group.
            control_X: Pre-experiment covariate for control users.
            treatment_Y: Outcome metric observations for the treatment group.
            treatment_X: Pre-experiment covariate for treatment users.
            alpha: Significance level for confidence interval construction.

        Returns:
            CupedEffect dataclass with all adjusted statistics.
        """
        control_Y = np.asarray(control_Y, dtype=float)
        control_X = np.asarray(control_X, dtype=float)
        treatment_Y = np.asarray(treatment_Y, dtype=float)
        treatment_X = np.asarray(treatment_X, dtype=float)

        n_c = len(control_Y)
        n_t = len(treatment_Y)

        # Step 1: Estimate theta from control group
        theta = CupedService.compute_theta(control_Y, control_X)

        # Step 2: E[X] from pooled covariate
        E_X = np.concatenate([control_X, treatment_X]).mean()

        # Step 3: Adjust both groups
        control_Y_adj = CupedService.apply_cuped(control_Y, control_X, theta, E_X)
        treatment_Y_adj = CupedService.apply_cuped(
            treatment_Y, treatment_X, theta, E_X
        )

        # Step 4: Adjusted means and effect
        adj_control_mean = float(control_Y_adj.mean())
        adj_treatment_mean = float(treatment_Y_adj.mean())
        adjusted_effect = adj_treatment_mean - adj_control_mean

        # Step 5: Pooled SE (Welch-style — different group sizes / variances)
        var_c = float(np.var(control_Y_adj, ddof=1)) if n_c > 1 else 0.0
        var_t = float(np.var(treatment_Y_adj, ddof=1)) if n_t > 1 else 0.0
        se = math.sqrt(var_c / n_c + var_t / n_t) if (n_c > 0 and n_t > 0) else 0.0
        se = max(se, 1e-12)  # guard against division-by-zero below

        # Step 6: Two-tailed z-test
        z_stat = adjusted_effect / se
        p_value = float(2.0 * (1.0 - stats.norm.cdf(abs(z_stat))))
        p_value = min(1.0, max(0.0, p_value))

        z_crit = float(stats.norm.ppf(1.0 - alpha / 2.0))
        ci_lower = adjusted_effect - z_crit * se
        ci_upper = adjusted_effect + z_crit * se

        # Step 7: Variance reduction percentage (control group)
        var_original = float(np.var(control_Y, ddof=1)) if n_c > 1 else 0.0
        if var_original > 0.0:
            var_adj = float(np.var(control_Y_adj, ddof=1))
            reduction_pct = (1.0 - var_adj / var_original) * 100.0
        else:
            reduction_pct = 0.0

        return CupedEffect(
            adjusted_control_mean=adj_control_mean,
            adjusted_treatment_mean=adj_treatment_mean,
            adjusted_effect=adjusted_effect,
            adjusted_se=se,
            adjusted_p_value=p_value,
            adjusted_ci=(float(ci_lower), float(ci_upper)),
            variance_reduction_pct=float(reduction_pct),
            theta=float(theta),
        )

    # ------------------------------------------------------------------
    # Ratio metric CUPED (CUPED++)
    # ------------------------------------------------------------------

    @staticmethod
    def apply_cuped_ratio(
        Y_num: np.ndarray,
        Y_den: np.ndarray,
        X_num: np.ndarray,
        X_den: np.ndarray,
    ) -> float:
        """Compute a delta-method-adjusted ratio estimate (CUPED++).

        Estimates the ratio metric R = mean(Y_num) / mean(Y_den) using the
        delta method for variance stabilisation:

            R ≈ mean(Y_num) / mean(Y_den)

        This is the first-order Taylor approximation of the ratio, which
        serves as the CUPED++ estimator for ratio metrics (e.g. revenue per
        session, clicks per impression).

        Args:
            Y_num: Numerator metric observations (e.g. revenue).
            Y_den: Denominator metric observations (e.g. sessions).
            X_num: Pre-experiment numerator covariate.
            X_den: Pre-experiment denominator covariate.

        Returns:
            The delta-method ratio estimate as a Python float.
        """
        Y_num = np.asarray(Y_num, dtype=float)
        Y_den = np.asarray(Y_den, dtype=float)
        X_num = np.asarray(X_num, dtype=float)
        X_den = np.asarray(X_den, dtype=float)

        mean_num = float(Y_num.mean())
        mean_den = float(Y_den.mean())

        if mean_den == 0.0:
            return 0.0

        # Delta method ratio estimator
        ratio = mean_num / mean_den
        return ratio
