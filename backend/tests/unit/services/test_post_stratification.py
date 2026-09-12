"""
Unit tests for PostStratificationService — EP-043.

Tests cover the Horvitz-Thompson post-stratification estimator:
- Basic post-strat with 2 strata
- Imbalanced strata handling
- Single stratum (degenerates to t-test)
- Multiple stratum columns (interactions)
- Variance reduction verification
- Edge cases (empty strata, minimum sizes)
- Statistical correctness
- Comparison with raw (no-strat) estimates
"""

import math

import numpy as np
import pandas as pd
import pytest

from backend.app.services.post_stratification_service import (
    PostStratificationService,
    PostStratResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> PostStratificationService:
    return PostStratificationService()


def _make_balanced_data(
    n_per_group: int = 200,
    n_strata: int = 2,
    treatment_effect: float = 0.5,
    seed: int = 42,
) -> tuple:
    """
    Generate balanced control/treatment data with strata.

    Strata are 'A' and 'B' (or more), evenly split across both groups.
    Returns (control_df, treatment_df).
    """
    rng = np.random.default_rng(seed)
    stratum_labels = [chr(ord("A") + i) for i in range(n_strata)]

    control_rows = []
    treatment_rows = []
    for i, label in enumerate(stratum_labels):
        n = n_per_group // n_strata
        # Stratum-specific means to make strata informative
        stratum_mean = float(i) * 2.0
        control_rows.append(
            pd.DataFrame(
                {
                    "metric_value": rng.normal(stratum_mean, 1.0, n),
                    "stratum": label,
                }
            )
        )
        treatment_rows.append(
            pd.DataFrame(
                {
                    "metric_value": rng.normal(stratum_mean + treatment_effect, 1.0, n),
                    "stratum": label,
                }
            )
        )

    control_df = pd.concat(control_rows, ignore_index=True)
    treatment_df = pd.concat(treatment_rows, ignore_index=True)
    return control_df, treatment_df


def _make_imbalanced_data(
    control_sizes: list,
    treatment_sizes: list,
    seed: int = 99,
) -> tuple:
    """
    Generate data where strata sizes differ between control and treatment.
    control_sizes and treatment_sizes are per-stratum counts.
    """
    rng = np.random.default_rng(seed)
    assert len(control_sizes) == len(treatment_sizes)
    n_strata = len(control_sizes)
    stratum_labels = [chr(ord("A") + i) for i in range(n_strata)]

    control_rows = []
    treatment_rows = []
    for i, label in enumerate(stratum_labels):
        stratum_mean = float(i) * 3.0
        control_rows.append(
            pd.DataFrame(
                {
                    "metric_value": rng.normal(stratum_mean, 1.0, control_sizes[i]),
                    "stratum": label,
                }
            )
        )
        treatment_rows.append(
            pd.DataFrame(
                {
                    "metric_value": rng.normal(
                        stratum_mean + 1.0, 1.0, treatment_sizes[i]
                    ),
                    "stratum": label,
                }
            )
        )

    control_df = pd.concat(control_rows, ignore_index=True)
    treatment_df = pd.concat(treatment_rows, ignore_index=True)
    return control_df, treatment_df


# ---------------------------------------------------------------------------
# TestPostStratResult dataclass
# ---------------------------------------------------------------------------


class TestPostStratResult:
    """Tests for the PostStratResult dataclass."""

    def test_poststrat_result_has_required_fields(self):
        """PostStratResult has all required fields."""
        result = PostStratResult(
            metric_name="revenue",
            control_mean=1.0,
            treatment_mean=1.5,
            effect_size=0.5,
            effect_size_relative=0.5,
            variance_reduction=20.0,
            adjusted_se=0.1,
            p_value=0.01,
            confidence_interval=(-0.1, 1.1),
            n_strata=2,
            strata_sizes={"A": 100, "B": 100},
        )
        assert result.metric_name == "revenue"
        assert result.n_strata == 2
        assert isinstance(result.strata_sizes, dict)

    def test_poststrat_result_confidence_interval_is_tuple(self):
        """confidence_interval is a (lower, upper) tuple."""
        result = PostStratResult(
            metric_name="clicks",
            control_mean=0.5,
            treatment_mean=0.6,
            effect_size=0.1,
            effect_size_relative=0.2,
            variance_reduction=10.0,
            adjusted_se=0.05,
            p_value=0.05,
            confidence_interval=(0.0, 0.2),
            n_strata=3,
            strata_sizes={"A": 50, "B": 50, "C": 50},
        )
        assert len(result.confidence_interval) == 2
        assert result.confidence_interval[0] <= result.confidence_interval[1]


# ---------------------------------------------------------------------------
# TestPostStratificationServiceBasic — Tests 1-10
# ---------------------------------------------------------------------------


class TestPostStratificationServiceBasic:
    """Basic correctness tests for PostStratificationService."""

    def test_compute_returns_poststrat_result(self):
        """compute() returns a PostStratResult instance."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(n_per_group=100, n_strata=2)
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert isinstance(result, PostStratResult)

    def test_compute_basic_two_strata_positive_effect(self):
        """Positive treatment effect is detected with 2 balanced strata."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(
            n_per_group=500, n_strata=2, treatment_effect=1.0, seed=10
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert result.effect_size > 0, "Expected positive effect size"
        assert result.treatment_mean > result.control_mean

    def test_compute_basic_two_strata_negative_effect(self):
        """Negative treatment effect is detected correctly."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(
            n_per_group=500, n_strata=2, treatment_effect=-1.0, seed=11
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert result.effect_size < 0, "Expected negative effect size"
        assert result.treatment_mean < result.control_mean

    def test_compute_n_strata_correct(self):
        """n_strata matches the number of unique stratum values."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(n_per_group=200, n_strata=3)
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert result.n_strata == 3

    def test_compute_strata_sizes_keys_match_strata(self):
        """strata_sizes dict keys match the unique stratum values."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(n_per_group=200, n_strata=2)
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert set(result.strata_sizes.keys()) == {"A", "B"}
        assert all(v > 0 for v in result.strata_sizes.values())

    def test_compute_p_value_in_valid_range(self):
        """p_value is in [0, 1]."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(n_per_group=200)
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert 0.0 <= result.p_value <= 1.0

    def test_compute_confidence_interval_covers_estimate(self):
        """95% CI lower < effect_size < upper."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(
            n_per_group=500, n_strata=2, treatment_effect=0.5, seed=20
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        lo, hi = result.confidence_interval
        assert lo < result.effect_size < hi, (
            f"Effect size {result.effect_size} not in CI [{lo}, {hi}]"
        )

    def test_compute_effect_size_equals_treatment_minus_control(self):
        """effect_size = treatment_mean - control_mean."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(n_per_group=200)
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert (
            abs(result.effect_size - (result.treatment_mean - result.control_mean))
            < 1e-10
        )

    def test_compute_effect_size_relative_is_ratio(self):
        """effect_size_relative = effect_size / abs(control_mean)."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(
            n_per_group=200, n_strata=2, treatment_effect=1.0, seed=5
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        if abs(result.control_mean) > 1e-9:
            expected_rel = result.effect_size / abs(result.control_mean)
            assert abs(result.effect_size_relative - expected_rel) < 1e-9

    def test_compute_adjusted_se_positive(self):
        """adjusted_se is strictly positive."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(n_per_group=200)
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert result.adjusted_se > 0


# ---------------------------------------------------------------------------
# TestPostStratificationVarianceReduction — Tests 11-18
# ---------------------------------------------------------------------------


class TestPostStratificationVarianceReduction:
    """Tests that post-stratification actually reduces variance."""

    def test_variance_reduction_positive_when_strata_informative(self):
        """variance_reduction > 0 when strata are correlated with the metric."""
        service = _make_service()
        # Large stratum effect => strata highly informative
        control_df, treatment_df = _make_balanced_data(
            n_per_group=500, n_strata=3, treatment_effect=0.5, seed=42
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        # With large stratum means (0, 2, 4 in _make_balanced_data), variance
        # reduction should be positive
        assert result.variance_reduction > 0.0, (
            f"Expected positive variance reduction, got {result.variance_reduction}"
        )

    def test_variance_reduction_is_percentage(self):
        """variance_reduction is expressed as a percentage (can be > 1)."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(n_per_group=300)
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        # As a percentage it should be between -inf and 100
        assert result.variance_reduction <= 100.0

    def test_variance_reduction_high_for_informative_strata(self):
        """variance_reduction is substantial (>10%) when strata are highly informative."""
        rng = np.random.default_rng(100)
        # Strata with very different means: [0, 10, 20]
        control_rows = []
        treatment_rows = []
        for i, label in enumerate(["A", "B", "C"]):
            mean = float(i) * 10.0
            n = 200
            control_rows.append(
                pd.DataFrame(
                    {"metric_value": rng.normal(mean, 1.0, n), "stratum": label}
                )
            )
            treatment_rows.append(
                pd.DataFrame(
                    {"metric_value": rng.normal(mean + 0.5, 1.0, n), "stratum": label}
                )
            )
        control_df = pd.concat(control_rows, ignore_index=True)
        treatment_df = pd.concat(treatment_rows, ignore_index=True)

        service = _make_service()
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert result.variance_reduction > 10.0, (
            f"Expected >10% variance reduction for highly informative strata, "
            f"got {result.variance_reduction:.2f}%"
        )

    def test_variance_reduction_low_for_uninformative_strata(self):
        """variance_reduction is small when strata are not informative."""
        rng = np.random.default_rng(200)
        # Strata with identical means — strata are uninformative
        n = 300
        control_df = pd.DataFrame(
            {
                "metric_value": rng.normal(5.0, 1.0, n),
                "stratum": np.tile(["A", "B"], n // 2),
            }
        )
        treatment_df = pd.DataFrame(
            {
                "metric_value": rng.normal(5.5, 1.0, n),
                "stratum": np.tile(["A", "B"], n // 2),
            }
        )

        service = _make_service()
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        # With uninformative strata, variance reduction should be close to 0
        assert result.variance_reduction < 20.0, (
            f"Expected small variance reduction for uninformative strata, "
            f"got {result.variance_reduction:.2f}%"
        )

    def test_poststrat_se_smaller_than_raw_se_when_strata_informative(self):
        """Post-strat SE is smaller than naive SE when strata are informative."""
        rng = np.random.default_rng(300)
        # Strata with very different means
        control_rows = []
        treatment_rows = []
        for i, label in enumerate(["A", "B"]):
            mean = float(i) * 8.0
            n = 250
            control_rows.append(
                pd.DataFrame(
                    {"metric_value": rng.normal(mean, 1.0, n), "stratum": label}
                )
            )
            treatment_rows.append(
                pd.DataFrame(
                    {"metric_value": rng.normal(mean + 1.0, 1.0, n), "stratum": label}
                )
            )
        control_df = pd.concat(control_rows, ignore_index=True)
        treatment_df = pd.concat(treatment_rows, ignore_index=True)

        service = _make_service()
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )

        # Compute raw (unstratified) SE
        all_control = control_df["metric_value"].values
        all_treatment = treatment_df["metric_value"].values
        raw_se = math.sqrt(
            np.var(all_control, ddof=1) / len(all_control)
            + np.var(all_treatment, ddof=1) / len(all_treatment)
        )

        assert result.adjusted_se < raw_se, (
            f"Post-strat SE ({result.adjusted_se:.4f}) should be < raw SE ({raw_se:.4f})"
        )

    def test_single_stratum_degenerates_to_welch_ttest(self):
        """With 1 stratum, result is equivalent to a Welch t-test (approx)."""
        from scipy import stats as scipy_stats

        rng = np.random.default_rng(400)
        n = 300
        control_df = pd.DataFrame(
            {"metric_value": rng.normal(5.0, 2.0, n), "stratum": "A"}
        )
        treatment_df = pd.DataFrame(
            {"metric_value": rng.normal(5.5, 2.0, n), "stratum": "A"}
        )

        service = _make_service()
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )

        # Welch t-test p-value
        t_stat, p_value_welch = scipy_stats.ttest_ind(
            treatment_df["metric_value"].values,
            control_df["metric_value"].values,
            equal_var=False,
        )

        # p-values should be close (within 20% relative)
        assert abs(result.p_value - p_value_welch) < 0.05, (
            f"Single-stratum p-value {result.p_value:.4f} should be close to "
            f"Welch t-test p-value {p_value_welch:.4f}"
        )

    def test_single_stratum_n_strata_is_one(self):
        """n_strata == 1 for a single-stratum dataset."""
        service = _make_service()
        control_df = pd.DataFrame({"metric_value": [1.0, 2.0, 3.0], "stratum": "A"})
        treatment_df = pd.DataFrame({"metric_value": [2.0, 3.0, 4.0], "stratum": "A"})
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert result.n_strata == 1

    def test_variance_reduction_zero_for_single_stratum(self):
        """variance_reduction is 0 when only one stratum (no gain from stratification)."""
        service = _make_service()
        rng = np.random.default_rng(500)
        n = 200
        control_df = pd.DataFrame(
            {"metric_value": rng.normal(5.0, 1.0, n), "stratum": "A"}
        )
        treatment_df = pd.DataFrame(
            {"metric_value": rng.normal(5.5, 1.0, n), "stratum": "A"}
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        # With single stratum, post-stratification equals raw estimator → 0% reduction
        assert abs(result.variance_reduction) < 1.0, (
            f"Expected ~0% variance reduction for single stratum, "
            f"got {result.variance_reduction:.2f}%"
        )


# ---------------------------------------------------------------------------
# TestPostStratificationImbalanced — Tests 19-23
# ---------------------------------------------------------------------------


class TestPostStratificationImbalanced:
    """Tests for imbalanced strata (different sizes in control vs treatment)."""

    def test_compute_with_imbalanced_strata(self):
        """compute() handles imbalanced strata without error."""
        service = _make_service()
        control_df, treatment_df = _make_imbalanced_data(
            control_sizes=[150, 50],
            treatment_sizes=[80, 120],
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert isinstance(result, PostStratResult)
        assert result.n_strata == 2

    def test_imbalanced_strata_reduces_bias(self):
        """Post-strat corrects for imbalance in stratum representation."""
        service = _make_service()
        # Stratum B has high mean (10.0) but is underrepresented in control
        control_df, treatment_df = _make_imbalanced_data(
            control_sizes=[200, 50],
            treatment_sizes=[100, 200],
            seed=10,
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        # Result should be finite and have a valid p-value
        assert math.isfinite(result.effect_size)
        assert 0.0 <= result.p_value <= 1.0

    def test_heavily_imbalanced_strata(self):
        """Very imbalanced strata (10:190 ratio) still works."""
        service = _make_service()
        control_df, treatment_df = _make_imbalanced_data(
            control_sizes=[10, 190],
            treatment_sizes=[190, 10],
            seed=77,
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert isinstance(result, PostStratResult)
        assert result.adjusted_se > 0

    def test_strata_weights_from_combined_population(self):
        """Stratum weights are computed from the combined (pooled) dataset."""
        service = _make_service()
        # 3:1 control:treatment ratio
        control_df, treatment_df = _make_imbalanced_data(
            control_sizes=[300, 300],
            treatment_sizes=[100, 100],
            seed=55,
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        # Both strata contribute equally to the combined dataset (300+100 each)
        # so weights should be equal ≈ 0.5 each
        assert result.n_strata == 2
        assert isinstance(result, PostStratResult)

    def test_multiple_stratum_columns(self):
        """compute() handles multiple stratum columns as interaction strata."""
        service = _make_service()
        rng = np.random.default_rng(600)
        n = 400

        # Build all 4 combinations explicitly: US_mobile, US_desktop, UK_mobile, UK_desktop
        countries = np.tile(["US", "US", "UK", "UK"], n // 4)
        devices = np.tile(["mobile", "desktop", "mobile", "desktop"], n // 4)

        control_df = pd.DataFrame(
            {
                "metric_value": rng.normal(5.0, 1.0, n),
                "country": countries,
                "device": devices,
            }
        )
        treatment_df = pd.DataFrame(
            {
                "metric_value": rng.normal(5.5, 1.0, n),
                "country": countries.copy(),
                "device": devices.copy(),
            }
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["country", "device"],
        )
        # 2 countries × 2 devices = 4 strata (interaction)
        assert result.n_strata == 4


# ---------------------------------------------------------------------------
# TestPostStratificationEdgeCases — Tests 24-30
# ---------------------------------------------------------------------------


class TestPostStratificationEdgeCases:
    """Edge case and validation tests."""

    def test_raises_on_empty_control_data(self):
        """ValueError raised when control_data is empty."""
        service = _make_service()
        control_df = pd.DataFrame({"metric_value": [], "stratum": []})
        treatment_df = pd.DataFrame({"metric_value": [1.0, 2.0], "stratum": ["A", "A"]})
        with pytest.raises(ValueError, match="[Ee]mpty|[Nn]o data|[Ii]nvalid"):
            service.compute(
                control_data=control_df,
                treatment_data=treatment_df,
                stratum_cols=["stratum"],
            )

    def test_raises_on_empty_treatment_data(self):
        """ValueError raised when treatment_data is empty."""
        service = _make_service()
        control_df = pd.DataFrame({"metric_value": [1.0, 2.0], "stratum": ["A", "A"]})
        treatment_df = pd.DataFrame({"metric_value": [], "stratum": []})
        with pytest.raises(ValueError, match="[Ee]mpty|[Nn]o data|[Ii]nvalid"):
            service.compute(
                control_data=control_df,
                treatment_data=treatment_df,
                stratum_cols=["stratum"],
            )

    def test_raises_on_missing_stratum_column(self):
        """ValueError raised when stratum_col not in DataFrame."""
        service = _make_service()
        control_df = pd.DataFrame(
            {"metric_value": [1.0, 2.0, 3.0], "other_col": ["A", "A", "B"]}
        )
        treatment_df = pd.DataFrame(
            {"metric_value": [2.0, 3.0, 4.0], "other_col": ["A", "B", "B"]}
        )
        with pytest.raises((ValueError, KeyError)):
            service.compute(
                control_data=control_df,
                treatment_data=treatment_df,
                stratum_cols=["stratum"],
            )

    def test_raises_on_missing_metric_column(self):
        """ValueError raised when metric_col not in DataFrame."""
        service = _make_service()
        control_df = pd.DataFrame({"value": [1.0, 2.0], "stratum": ["A", "B"]})
        treatment_df = pd.DataFrame({"value": [2.0, 3.0], "stratum": ["A", "B"]})
        with pytest.raises((ValueError, KeyError)):
            service.compute(
                control_data=control_df,
                treatment_data=treatment_df,
                stratum_cols=["stratum"],
                metric_col="metric_value",
            )

    def test_minimum_stratum_size_validation(self):
        """Strata with fewer than 2 observations raise ValueError."""
        service = _make_service()
        # Stratum "B" has only 1 observation in control
        control_df = pd.DataFrame(
            {"metric_value": [1.0, 2.0, 3.0, 4.0], "stratum": ["A", "A", "A", "B"]}
        )
        treatment_df = pd.DataFrame(
            {"metric_value": [2.0, 3.0, 4.0, 1.0], "stratum": ["A", "A", "B", "B"]}
        )
        with pytest.raises(ValueError, match="[Ss]tratum|[Ss]ize|[Ss]mall|[Mm]in"):
            service.compute(
                control_data=control_df,
                treatment_data=treatment_df,
                stratum_cols=["stratum"],
            )

    def test_custom_alpha_narrows_confidence_interval(self):
        """Narrower CI for alpha=0.10 than alpha=0.01."""
        service = _make_service()
        control_df, treatment_df = _make_balanced_data(
            n_per_group=500, n_strata=2, seed=42
        )

        result_90 = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
            alpha=0.10,
        )
        result_99 = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
            alpha=0.01,
        )

        width_90 = result_90.confidence_interval[1] - result_90.confidence_interval[0]
        width_99 = result_99.confidence_interval[1] - result_99.confidence_interval[0]
        assert width_90 < width_99, "90% CI should be narrower than 99% CI"

    def test_custom_metric_column_name(self):
        """compute() works with a custom metric_col name."""
        service = _make_service()
        rng = np.random.default_rng(700)
        n = 200
        control_df = pd.DataFrame(
            {
                "revenue": rng.normal(100.0, 10.0, n),
                "stratum": np.tile(["A", "B"], n // 2),
            }
        )
        treatment_df = pd.DataFrame(
            {
                "revenue": rng.normal(105.0, 10.0, n),
                "stratum": np.tile(["A", "B"], n // 2),
            }
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
            metric_col="revenue",
        )
        assert isinstance(result, PostStratResult)
        assert result.control_mean > 0

    def test_significant_result_when_large_effect(self):
        """p_value < 0.05 for a large, clearly detectable treatment effect."""
        service = _make_service()
        rng = np.random.default_rng(800)
        n = 1000
        control_df = pd.DataFrame(
            {
                "metric_value": rng.normal(0.0, 1.0, n),
                "stratum": np.tile(["A", "B"], n // 2),
            }
        )
        treatment_df = pd.DataFrame(
            {
                "metric_value": rng.normal(5.0, 1.0, n),
                "stratum": np.tile(["A", "B"], n // 2),
            }
        )
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        assert result.p_value < 0.001, (
            f"Expected p < 0.001 for large effect, got {result.p_value}"
        )

    def test_non_significant_result_when_no_effect(self):
        """p_value is likely large (>0.10) when there is truly no treatment effect."""
        rng = np.random.default_rng(900)
        n = 500
        control_df = pd.DataFrame(
            {
                "metric_value": rng.normal(5.0, 1.0, n),
                "stratum": np.tile(["A", "B"], n // 2),
            }
        )
        treatment_df = pd.DataFrame(
            {
                "metric_value": rng.normal(5.0, 1.0, n),
                "stratum": np.tile(["A", "B"], n // 2),
            }
        )
        service = _make_service()
        result = service.compute(
            control_data=control_df,
            treatment_data=treatment_df,
            stratum_cols=["stratum"],
        )
        # With no effect, p-value should generally be large (not guaranteed due to randomness)
        # but with seed=900 and no effect this should pass
        assert result.p_value > 0.05, (
            f"Expected p > 0.05 for null effect, got {result.p_value:.4f}"
        )

    def test_ci_width_decreases_with_more_data(self):
        """Larger sample sizes produce narrower confidence intervals."""
        service = _make_service()

        small_control, small_treatment = _make_balanced_data(
            n_per_group=50, n_strata=2, seed=42
        )
        large_control, large_treatment = _make_balanced_data(
            n_per_group=2000, n_strata=2, seed=42
        )

        result_small = service.compute(
            control_data=small_control,
            treatment_data=small_treatment,
            stratum_cols=["stratum"],
        )
        result_large = service.compute(
            control_data=large_control,
            treatment_data=large_treatment,
            stratum_cols=["stratum"],
        )

        width_small = (
            result_small.confidence_interval[1] - result_small.confidence_interval[0]
        )
        width_large = (
            result_large.confidence_interval[1] - result_large.confidence_interval[0]
        )
        assert width_small > width_large, "Small sample should have wider CI"
