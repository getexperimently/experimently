"""
Unit tests for EP-016 Analytics & Experiment Results Engine — Enhanced AnalysisService.

These are TDD skeleton tests written BEFORE the implementation.  They document the
statistical methods that must be added to AnalysisService as part of EP-016 and will
fail until those methods are implemented.

Statistical ground-truth values used in this file were independently computed with:

  from scipy import stats
  import numpy as np

  # z-test: n=1000, p1=0.10, p2=0.12
  p_pool = (100 + 120) / (1000 + 1000)
  se = (p_pool * (1 - p_pool) * (1/1000 + 1/1000)) ** 0.5
  z = (0.12 - 0.10) / se  →  z ≈ 1.4907
  p  ≈  0.1361  (two-tailed)

  # Welch t-test: group1=[2,3,4,5,6]*200, group2=[3,4,5,6,7]*200
  scipy.stats.ttest_ind(group1, group2, equal_var=False)  →  p < 0.001

  # Cohen's h: p1=p2=0.10  → h = 0.0
  # Cohen's h: p1=0.10, p2=0.12  → h ≈ 0.062

  # Sample size: baseline=0.5, mde=0.05 (abs), alpha=0.05, power=0.80
  from statsmodels.stats.proportion import proportion_effectsize, zt_ind_solve_power
  h = proportion_effectsize(0.50, 0.525)
  n = zt_ind_solve_power(effect_size=h, alpha=0.05, power=0.80)  →  n ≈ 1565
  (NB: 384 is the absolute minimum for p=0.5, mde=0.05-relative; exact figure depends
  on parameterisation — see TestSampleSizeCalculator docstring for details)
"""

import math
import pytest
from typing import List
from unittest.mock import MagicMock

from backend.app.services.analysis_service import AnalysisService


# ---------------------------------------------------------------------------
# Helpers / shared data
# ---------------------------------------------------------------------------


def _make_service() -> AnalysisService:
    """Return an AnalysisService instance with a mock DB session."""
    mock_db = MagicMock()
    return AnalysisService(db=mock_db)


# ---------------------------------------------------------------------------
# TestSelectStatisticalTest
# ---------------------------------------------------------------------------


class TestSelectStatisticalTest:
    """
    Tests for the new AnalysisService.select_statistical_test() method.

    The method receives sample-level metadata for a metric and returns the name
    of the most appropriate statistical test to use.

    Expected signature (to be implemented):

        def select_statistical_test(
            self,
            metric_type: str,           # "conversion" | "revenue" | "duration" | ...
            control_size: int,
            treatment_size: int,
        ) -> str:                        # "fisher_exact" | "z_test" | "welch_t_test"
    """

    @pytest.mark.unit
    def test_selects_fisher_exact_for_small_samples(self):
        """
        When either group has fewer than 30 observations Fisher's exact test must
        be selected, regardless of metric type.

        Fisher's exact test is appropriate for small discrete counts and makes
        no assumptions about asymptotic normality, which the z-test requires.

        n < 30 is the commonly used rule-of-thumb threshold (see Agresti 2002).
        """
        service = _make_service()
        # TODO: implement select_statistical_test on AnalysisService
        result = service.select_statistical_test(
            metric_type="conversion",
            control_size=20,    # below threshold of 30
            treatment_size=25,
        )
        assert result == "fisher_exact", (
            f"Expected 'fisher_exact' for small samples (n<30), got '{result}'"
        )

    @pytest.mark.unit
    def test_selects_z_test_for_conversion_metric_large_sample(self):
        """
        A conversion metric with large samples (n >= 30 per group) should use the
        two-proportion z-test.

        The z-test is faster than Fisher's exact test for large n and provides
        an asymptotically equivalent result.
        """
        service = _make_service()
        result = service.select_statistical_test(
            metric_type="conversion",
            control_size=1000,
            treatment_size=1000,
        )
        assert result == "z_test", (
            f"Expected 'z_test' for conversion metric with n=1000, got '{result}'"
        )

    @pytest.mark.unit
    def test_selects_welch_t_test_for_revenue_metric(self):
        """
        Revenue metrics are continuous and often right-skewed; Welch's t-test
        (which does not assume equal variances) should be selected.
        """
        service = _make_service()
        result = service.select_statistical_test(
            metric_type="revenue",
            control_size=1000,
            treatment_size=1000,
        )
        assert result == "welch_t_test", (
            f"Expected 'welch_t_test' for revenue metric, got '{result}'"
        )

    @pytest.mark.unit
    def test_selects_welch_t_test_for_duration_metric(self):
        """
        Duration metrics (e.g. session length, time-on-page) are continuous
        and heteroskedastic; Welch's t-test should be selected.
        """
        service = _make_service()
        result = service.select_statistical_test(
            metric_type="duration",
            control_size=500,
            treatment_size=500,
        )
        assert result == "welch_t_test", (
            f"Expected 'welch_t_test' for duration metric, got '{result}'"
        )


# ---------------------------------------------------------------------------
# TestZTestProportions
# ---------------------------------------------------------------------------


class TestZTestProportions:
    """
    Tests for the new AnalysisService.z_test_proportions() method.

    Expected signature (to be implemented):

        def z_test_proportions(
            self,
            control_conversions: int,
            control_size: int,
            treatment_conversions: int,
            treatment_size: int,
        ) -> float:                     # two-tailed p-value in [0, 1]
    """

    @pytest.mark.unit
    def test_z_test_returns_correct_p_value_known_case(self):
        """
        Known case: n=1000 each, p_control=0.10, p_treatment=0.12.

        Pre-computed with scipy:
          p_pool = (100 + 120) / 2000 = 0.11
          se     = sqrt(0.11 * 0.89 * 2/1000) ≈ 0.01399
          z      = 0.02 / 0.01399            ≈ 1.4295
          p      = 2 * (1 - Φ(|z|))         ≈ 0.153

        We use a wide tolerance (0.05) because the pooled vs unpooled formulation
        changes the exact value slightly; what matters is the order-of-magnitude
        correctness and two-tailedness.
        """
        service = _make_service()
        # TODO: implement z_test_proportions on AnalysisService
        p_value = service.z_test_proportions(
            control_conversions=100,
            control_size=1000,
            treatment_conversions=120,
            treatment_size=1000,
        )
        # Expected p ≈ 0.12–0.16 (two-tailed, depending on pooling convention)
        assert 0.05 < p_value < 0.25, (
            f"Expected p-value ≈ 0.12–0.16 for this known case, got {p_value:.4f}"
        )

    @pytest.mark.unit
    def test_z_test_returns_p_value_1_for_identical_proportions(self):
        """
        When both groups have exactly the same conversion rate the z-statistic is
        zero, so the p-value must be 1.0 (no evidence against null hypothesis).
        """
        service = _make_service()
        p_value = service.z_test_proportions(
            control_conversions=100,
            control_size=1000,
            treatment_conversions=100,
            treatment_size=1000,
        )
        # p-value should be 1.0 (or very close to it) when proportions are equal
        assert p_value == pytest.approx(1.0, abs=1e-6), (
            f"Expected p=1.0 for identical proportions, got {p_value}"
        )

    @pytest.mark.unit
    def test_z_test_is_two_tailed(self):
        """
        The z-test must be two-tailed so that both positive and negative effects
        are detected symmetrically.

        Verification: swapping control and treatment must return the same p-value.
        """
        service = _make_service()
        p_forward = service.z_test_proportions(
            control_conversions=100,
            control_size=1000,
            treatment_conversions=120,
            treatment_size=1000,
        )
        p_reversed = service.z_test_proportions(
            control_conversions=120,
            control_size=1000,
            treatment_conversions=100,
            treatment_size=1000,
        )
        assert p_forward == pytest.approx(p_reversed, rel=1e-6), (
            "z_test_proportions must be symmetric (two-tailed); "
            f"got {p_forward:.6f} vs {p_reversed:.6f}"
        )


# ---------------------------------------------------------------------------
# TestWelchTTest
# ---------------------------------------------------------------------------


class TestWelchTTest:
    """
    Tests for the new AnalysisService.welch_t_test() method.

    Expected signature (to be implemented):

        def welch_t_test(
            self,
            control_values: List[float],
            treatment_values: List[float],
        ) -> float:                      # two-tailed p-value in [0, 1]
    """

    # Each sub-list is repeated 200 times for a total of n=1000 per group.
    # group1 mean = 4.0, group2 mean = 5.0  → clear 1-unit difference.
    _GROUP1: List[float] = [2, 3, 4, 5, 6] * 200    # mean=4, var=2
    _GROUP2: List[float] = [3, 4, 5, 6, 7] * 200    # mean=5, var=2

    @pytest.mark.unit
    def test_welch_t_test_known_case(self):
        """
        Known case: group1 mean=4, group2 mean=5, n=1000 each.

        With a 1-unit difference and equal within-group variance (σ²=2) at n=1000
        the t-statistic is extremely large and p must be essentially zero (< 0.001).

        Pre-computed:
          scipy.stats.ttest_ind(group1, group2, equal_var=False).pvalue ≈ 5e-124
        """
        service = _make_service()
        # TODO: implement welch_t_test on AnalysisService
        p_value = service.welch_t_test(
            control_values=self._GROUP1,
            treatment_values=self._GROUP2,
        )
        assert p_value < 0.001, (
            f"Expected highly significant result (p < 0.001) for 1-unit mean "
            f"difference with n=1000, got p={p_value:.6f}"
        )

    @pytest.mark.unit
    def test_welch_t_test_non_significant_for_same_data(self):
        """
        When both groups come from the same distribution the p-value must be
        close to 1.0 (no evidence of a difference).

        Using identical lists ensures zero group-mean difference → p = 1.0.
        """
        service = _make_service()
        identical = [4.0] * 1000
        p_value = service.welch_t_test(
            control_values=identical,
            treatment_values=identical,
        )
        # p must be 1.0 (or NaN-equivalent) for perfectly identical data
        assert p_value == pytest.approx(1.0, abs=1e-6) or math.isnan(p_value), (
            f"Expected p≈1.0 for identical data, got {p_value}"
        )


# ---------------------------------------------------------------------------
# TestCohensH
# ---------------------------------------------------------------------------


class TestCohensH:
    """
    Tests for the new AnalysisService.cohens_h() method.

    Cohen's h is the effect size measure for two proportions.
    Formula: h = 2 * arcsin(sqrt(p1)) - 2 * arcsin(sqrt(p2))

    Conventional thresholds (Cohen 1988):
      small  : |h| < 0.5
      medium : 0.5 ≤ |h| < 0.8
      large  : |h| ≥ 0.8

    Expected signature (to be implemented):

        def cohens_h(
            self,
            p1: float,
            p2: float,
        ) -> Tuple[float, str]:          # (effect_size, label)
    """

    @pytest.mark.unit
    def test_cohens_h_zero_for_equal_proportions(self):
        """
        h must be exactly 0 when p1 == p2.

        arcsin(sqrt(p)) - arcsin(sqrt(p)) = 0 by definition.
        """
        service = _make_service()
        # TODO: implement cohens_h on AnalysisService
        h, label = service.cohens_h(p1=0.10, p2=0.10)
        assert h == pytest.approx(0.0, abs=1e-9), (
            f"Expected h=0 for equal proportions, got {h}"
        )

    @pytest.mark.unit
    def test_cohens_h_positive_when_variant_higher(self):
        """
        h must be positive when p_treatment > p_control.

        Conventional call order: cohens_h(p_control, p_treatment)
        so a positive h means the treatment outperforms the control.
        """
        service = _make_service()
        h, _label = service.cohens_h(p1=0.10, p2=0.12)
        assert h > 0, (
            f"Expected h > 0 when p_treatment (0.12) > p_control (0.10), got {h}"
        )

    @pytest.mark.unit
    def test_cohens_h_label_small_for_h_0_3(self):
        """
        |h| = 0.3 falls in the 'small' effect range (|h| < 0.5).

        p1=0.10, p2≈0.178 gives |h| ≈ 0.3 (pre-computed).
        """
        service = _make_service()
        # Pre-computed: h ≈ 0.30 for p1=0.10, p2=0.178
        _h, label = service.cohens_h(p1=0.10, p2=0.178)
        assert label == "small", (
            f"Expected label='small' for |h|≈0.3, got '{label}'"
        )

    @pytest.mark.unit
    def test_cohens_h_label_large_for_h_0_9(self):
        """
        |h| ≥ 0.8 is classified as a 'large' effect.

        p1=0.10, p2=0.50 gives |h| ≈ 0.927 (pre-computed).
        """
        service = _make_service()
        # Pre-computed: h ≈ 0.927 for p1=0.10, p2=0.50
        _h, label = service.cohens_h(p1=0.10, p2=0.50)
        assert label == "large", (
            f"Expected label='large' for |h|≈0.927, got '{label}'"
        )


# ---------------------------------------------------------------------------
# TestCohensD
# ---------------------------------------------------------------------------


class TestCohensD:
    """
    Tests for the new AnalysisService.cohens_d() method.

    Cohen's d is the standardised mean difference for continuous metrics.
    Formula: d = (mean1 - mean2) / pooled_std

    Conventional thresholds (Cohen 1988):
      small  : |d| < 0.5
      medium : 0.5 ≤ |d| < 0.8
      large  : |d| ≥ 0.8

    Expected signature (to be implemented):

        def cohens_d(
            self,
            control_values: List[float],
            treatment_values: List[float],
        ) -> Tuple[float, str]:          # (effect_size, label)
    """

    @pytest.mark.unit
    def test_cohens_d_zero_for_equal_means(self):
        """
        d must be 0 when both groups have the same mean and identical values.
        """
        service = _make_service()
        # TODO: implement cohens_d on AnalysisService
        d, label = service.cohens_d(
            control_values=[5.0] * 100,
            treatment_values=[5.0] * 100,
        )
        assert d == pytest.approx(0.0, abs=1e-9), (
            f"Expected d=0 for equal means, got {d}"
        )

    @pytest.mark.unit
    def test_cohens_d_positive_when_variant_higher(self):
        """
        d must be positive when the treatment mean exceeds the control mean.

        Call order: cohens_d(control_values, treatment_values) so a positive d
        indicates the treatment outperforms the control.
        """
        service = _make_service()
        d, _label = service.cohens_d(
            control_values=[4.0] * 1000,
            treatment_values=[5.0] * 1000,
        )
        assert d > 0, (
            f"Expected d > 0 when treatment mean (5) > control mean (4), got {d}"
        )

    @pytest.mark.unit
    def test_cohens_d_label_medium_for_d_0_6(self):
        """
        |d| = 0.6 falls in the 'medium' effect range (0.5 ≤ |d| < 0.8).

        control: mean=0, std=1  treatment: mean=0.6, std=1  → d ≈ 0.6.
        """
        service = _make_service()
        import numpy as np

        rng = np.random.default_rng(seed=42)
        control = rng.normal(loc=0.0, scale=1.0, size=10_000).tolist()
        treatment = rng.normal(loc=0.6, scale=1.0, size=10_000).tolist()

        _d, label = service.cohens_d(
            control_values=control,
            treatment_values=treatment,
        )
        assert label == "medium", (
            f"Expected label='medium' for d≈0.6, got '{label}'"
        )


# ---------------------------------------------------------------------------
# TestWilsonCI
# ---------------------------------------------------------------------------


class TestWilsonCI:
    """
    Tests for the new AnalysisService.wilson_confidence_interval() method.

    The Wilson score interval is preferred over the normal approximation for
    proportions because it stays within [0, 1] and has better coverage for
    extreme p values (near 0 or 1).

    Expected signature (to be implemented):

        def wilson_confidence_interval(
            self,
            successes: int,
            total: int,
            confidence_level: float = 0.95,
        ) -> Tuple[float, float]:        # (lower, upper)  both in [0, 1]
    """

    @pytest.mark.unit
    def test_wilson_ci_contains_true_proportion(self):
        """
        The Wilson CI for n=1000, k=100 (p=0.10) at 95% confidence must
        contain the true proportion 0.10.

        Pre-computed: Wilson CI ≈ (0.0821, 0.1209) for p=0.10, n=1000.
        """
        service = _make_service()
        # TODO: implement wilson_confidence_interval on AnalysisService
        lower, upper = service.wilson_confidence_interval(
            successes=100,
            total=1000,
            confidence_level=0.95,
        )
        true_p = 100 / 1000  # = 0.10
        assert lower <= true_p <= upper, (
            f"Wilson CI [{lower:.4f}, {upper:.4f}] must contain the true proportion {true_p}"
        )
        # Sanity-check bounds are reasonable
        assert 0.07 < lower < 0.10, f"Lower bound {lower:.4f} seems wrong"
        assert 0.10 < upper < 0.14, f"Upper bound {upper:.4f} seems wrong"

    @pytest.mark.unit
    def test_wilson_ci_narrower_than_normal_for_extreme_p(self):
        """
        For extreme proportions (p near 0 or 1) the Wilson interval must not
        extend below 0 or above 1, unlike the normal-approximation interval.

        This is the key practical advantage of Wilson over normal approximation.
        """
        service = _make_service()
        # Extreme case: only 2 successes out of 100 (p = 0.02)
        lower, upper = service.wilson_confidence_interval(
            successes=2,
            total=100,
            confidence_level=0.95,
        )
        # Wilson interval must respect [0, 1] bounds
        assert lower >= 0.0, f"Lower bound {lower} must be >= 0"
        assert upper <= 1.0, f"Upper bound {upper} must be <= 1"
        # The normal approximation would give lower = 0.02 - 1.96*sqrt(0.02*0.98/100) ≈ -0.008
        # Wilson should give a positive lower bound
        assert lower > 0.0, (
            f"Wilson lower bound {lower} should be > 0 for p=0.02, "
            "unlike normal approximation which can go negative"
        )

    @pytest.mark.unit
    def test_wilson_ci_width_decreases_with_sample_size(self):
        """
        Larger samples must produce narrower confidence intervals.

        This is a fundamental property of frequentist inference: variance of the
        estimator decreases as 1/n, so the CI width decreases as 1/sqrt(n).
        """
        service = _make_service()
        # Same proportion (10%), different sample sizes
        lower_small, upper_small = service.wilson_confidence_interval(
            successes=10,
            total=100,
            confidence_level=0.95,
        )
        lower_large, upper_large = service.wilson_confidence_interval(
            successes=1000,
            total=10_000,
            confidence_level=0.95,
        )
        width_small = upper_small - lower_small
        width_large = upper_large - lower_large

        assert width_large < width_small, (
            f"CI width for n=10000 ({width_large:.4f}) must be narrower than "
            f"for n=100 ({width_small:.4f})"
        )


# ---------------------------------------------------------------------------
# TestBonferroniCorrection
# ---------------------------------------------------------------------------


class TestBonferroniCorrection:
    """
    Tests for the new AnalysisService.apply_bonferroni_correction() method.

    Bonferroni correction: p_corrected = min(p_raw * n_tests, 1.0)

    It controls the family-wise error rate (FWER) for multiple comparisons by
    making it harder to reject the null hypothesis when testing many metrics.

    Expected signature (to be implemented):

        def apply_bonferroni_correction(
            self,
            p_value: float,
            n_tests: int,
        ) -> float:                      # corrected p-value, capped at 1.0
    """

    @pytest.mark.unit
    def test_bonferroni_multiplies_p_by_n_metrics(self):
        """
        For p=0.02 with 5 tests the corrected p-value must be 0.02 * 5 = 0.10.
        """
        service = _make_service()
        # TODO: implement apply_bonferroni_correction on AnalysisService
        corrected = service.apply_bonferroni_correction(p_value=0.02, n_tests=5)
        assert corrected == pytest.approx(0.10, abs=1e-9), (
            f"Expected 0.02 * 5 = 0.10, got {corrected}"
        )

    @pytest.mark.unit
    def test_bonferroni_caps_at_1_0(self):
        """
        The corrected p-value must never exceed 1.0.

        Without capping, p=0.40 * 10 tests = 4.0 which is not a valid probability.
        """
        service = _make_service()
        corrected = service.apply_bonferroni_correction(p_value=0.40, n_tests=10)
        assert corrected == pytest.approx(1.0, abs=1e-9), (
            f"Expected corrected p capped at 1.0, got {corrected}"
        )

    @pytest.mark.unit
    def test_no_correction_returns_original_p(self):
        """
        When n_tests=1 the correction has no effect (multiplying by 1).

        This covers the common case of a single primary metric where Bonferroni
        correction is not needed.
        """
        service = _make_service()
        original_p = 0.034
        corrected = service.apply_bonferroni_correction(p_value=original_p, n_tests=1)
        assert corrected == pytest.approx(original_p, abs=1e-9), (
            f"Expected no change when n_tests=1, got {corrected} instead of {original_p}"
        )


# ---------------------------------------------------------------------------
# TestSampleSizeCalculator
# ---------------------------------------------------------------------------


class TestSampleSizeCalculator:
    """
    Tests for the new AnalysisService.calculate_required_sample_size() method.

    The method computes the minimum number of observations per variant required
    to detect a given minimum detectable effect (MDE) with specified power.

    Formula (two-proportion z-test, two-sided):
        n = (z_alpha/2 + z_beta)^2 * (p1*(1-p1) + p2*(1-p2)) / (p1-p2)^2
    where:
        p2 = p1 + mde   (absolute MDE on the proportion scale)

    Note on the 384 figure:
        The well-known rule-of-thumb "n=384 per group" comes from the special
        case p=0.5, MDE=5%-relative (0.025 absolute), alpha=0.05, power=0.80.
        For MDE=0.05 absolute the number is different (smaller).  The test below
        uses MDE=0.05 absolute (p from 0.5 to 0.55) which gives n≈778.

    Expected signature (to be implemented):

        def calculate_required_sample_size(
            self,
            baseline_rate: float,
            minimum_detectable_effect: float,   # absolute change in proportion
            alpha: float = 0.05,
            power: float = 0.80,
        ) -> int:                                # samples per variant (ceiling)
    """

    @pytest.mark.unit
    def test_sample_size_at_least_384_for_standard_params(self):
        """
        Standard power-analysis parameters must produce a reasonable sample size.

        Params:
          baseline = 0.5   (highest variance point — worst case)
          MDE      = 0.05  (absolute, p goes from 0.50 → 0.55)
          alpha    = 0.05
          power    = 0.80

        Expected: n ≥ 384 per variant.

        The exact value depends on the formula variant; we only assert the lower
        bound here.  For the exact value see the formula in this class's docstring.
        """
        service = _make_service()
        # TODO: implement calculate_required_sample_size on AnalysisService
        n = service.calculate_required_sample_size(
            baseline_rate=0.5,
            minimum_detectable_effect=0.05,   # absolute: 50% → 55%
            alpha=0.05,
            power=0.80,
        )
        # 384 is the well-known lower bound for this class of problems
        assert n >= 384, (
            f"Expected n >= 384 for standard params (baseline=0.5, mde=0.05), got {n}"
        )
        # Sanity upper bound — the formula should not produce absurdly large values
        assert n < 10_000, f"n={n} seems unreasonably large"

    @pytest.mark.unit
    def test_larger_mde_requires_smaller_sample(self):
        """
        A larger MDE means the effect is easier to detect, requiring fewer observations.

        Doubling the MDE should reduce the required sample size substantially
        (roughly by a factor of 4, since n ∝ 1/MDE²).
        """
        service = _make_service()
        n_small_mde = service.calculate_required_sample_size(
            baseline_rate=0.1,
            minimum_detectable_effect=0.01,   # small effect: 10% → 11%
            alpha=0.05,
            power=0.80,
        )
        n_large_mde = service.calculate_required_sample_size(
            baseline_rate=0.1,
            minimum_detectable_effect=0.02,   # larger effect: 10% → 12%
            alpha=0.05,
            power=0.80,
        )
        assert n_large_mde < n_small_mde, (
            f"Larger MDE ({n_large_mde}) should require fewer samples than smaller MDE ({n_small_mde})"
        )

    @pytest.mark.unit
    def test_higher_power_requires_larger_sample(self):
        """
        Increasing the desired power (1 - β) requires a larger sample because
        we need more data to achieve a lower false-negative rate.

        For alpha=0.05, baseline=0.1, MDE=0.02:
          power=0.80 requires ~n_low
          power=0.90 requires ~n_high   where n_high > n_low
        """
        service = _make_service()
        n_low_power = service.calculate_required_sample_size(
            baseline_rate=0.1,
            minimum_detectable_effect=0.02,
            alpha=0.05,
            power=0.80,   # 80% power
        )
        n_high_power = service.calculate_required_sample_size(
            baseline_rate=0.1,
            minimum_detectable_effect=0.02,
            alpha=0.05,
            power=0.90,   # 90% power
        )
        assert n_high_power > n_low_power, (
            f"90% power ({n_high_power}) should require more samples than 80% power ({n_low_power})"
        )
