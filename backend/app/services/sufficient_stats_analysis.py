"""
Metric results from per-variant sufficient statistics.

For a proportion metric, everything ``/results`` reports about a variant
follows from two numbers: the units in it and the units that converted.  This
module turns those counts into results; it reads no database.  ``/results``
counts assignments and converting users and passes the counts here, and a
caller that has the counts from somewhere else (a customer's warehouse, #312)
gets the same numbers for the same counts.

``binomial_metric_result`` was extracted, without numeric change, from
``AnalysisService.calculate_metric_results`` and ``_to_metric_result`` (#404).
``test_binomial_metric_result_characterisation.py`` pins the ``/results``
output it has to reproduce, and ``test_sufficient_stats_fingerprint.py`` pins
its own output per ``ENGINE_VERSION``.

``mean_metric_result`` does the same for a mean metric, from each variant's
unit count and its sums of ``y - k`` and ``(y - k) ** 2`` centred on the grand
mean ``k``.  ``test_mean_metric_result.py`` holds it to an exact reference.
"""

import logging
import math
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from scipy import stats

logger = logging.getLogger(__name__)


class BinomialVariant(NamedTuple):
    """The identity of a variant; any object with these attributes will do
    (an ORM ``Variant`` included)."""

    id: Any
    name: str
    is_control: bool


#: ``(variant, n, n_converted)``: units in the variant and units that converted.
BinomialCounts = Tuple[Any, int, int]


def adjusted_p_values(
    p_values: List[Optional[float]], method: str
) -> List[Optional[float]]:
    """Multiple-comparison correction across the treatment variants of one metric."""
    valid = [(i, p) for i, p in enumerate(p_values) if p is not None]
    adjusted: List[Optional[float]] = [None] * len(p_values)
    if not valid or method == "none":
        return adjusted
    k = len(valid)
    if method == "bonferroni":
        for i, p in valid:
            adjusted[i] = min(1.0, p * k)
        return adjusted
    if method == "benjamini_hochberg":
        ordered = sorted(valid, key=lambda ip: ip[1])
        running = 1.0
        for rank in range(k, 0, -1):
            i, p = ordered[rank - 1]
            running = min(running, p * k / rank)
            adjusted[i] = min(1.0, running)
        return adjusted
    return adjusted


def effect_size_label(abs_effect: float) -> str:
    """Map absolute effect size to a human-readable label (EP-016 thresholds)."""
    if abs_effect < 0.2:
        return "negligible"
    elif abs_effect < 0.5:
        return "small"
    elif abs_effect < 0.8:
        return "medium"
    else:
        return "large"


def binomial_variant_results(
    variants: Sequence[BinomialCounts],
) -> List[Dict[str, Any]]:
    """Per-variant results on the legacy percent scale.

    These are the ``variant_results`` of ``/results``' ``metrics_results``:
    conversion rate and a 95% normal-approximation interval in percent, and,
    for each treatment, Fisher's exact p-value against the control, its
    significance at 0.05 and the relative improvement in percent.  The first
    variant flagged ``is_control`` is the control.

    Raises:
        ValueError: when no variant is the control.
    """
    control = next((v for v, _, _ in variants if v.is_control), None)
    if control is None:
        raise ValueError("No variant is the control")
    control_id = str(control.id)

    assignments: Dict[str, int] = {}
    conversions: Dict[str, int] = {}
    for variant, n, n_converted in variants:
        assignments[str(variant.id)] = n
        conversions[str(variant.id)] = n_converted

    rates: Dict[str, float] = {}
    for variant_id, n in assignments.items():
        if n > 0:
            rate = (conversions[variant_id] / n) * 100
        else:
            rate = 0
        rates[variant_id] = rate

    results: List[Dict[str, Any]] = []
    control_conversions = conversions[control_id]
    control_non_conversions = assignments[control_id] - control_conversions

    for variant, _, _ in variants:
        variant_id = str(variant.id)
        # The literal 0s below stay ints, as they were in /results' output.
        p_value: Optional[float]
        relative_improvement: Optional[float]

        if variant.is_control:
            p_value = 1.0
            is_significant = False
            relative_improvement = 0
        else:
            variant_conversions = conversions[variant_id]
            variant_non_conversions = assignments[variant_id] - variant_conversions

            contingency_table = [
                [variant_conversions, variant_non_conversions],
                [control_conversions, control_non_conversions],
            ]

            try:
                odds_ratio, p_value = stats.fisher_exact(contingency_table)
                is_significant = p_value < 0.05  # Using 95% confidence level

                if rates[control_id] > 0:
                    relative_improvement = (
                        (rates[variant_id] - rates[control_id]) / rates[control_id]
                    ) * 100
                else:
                    relative_improvement = float("inf") if rates[variant_id] > 0 else 0
            except Exception as e:
                logger.error(f"Error calculating statistics: {e!s}")
                p_value = None
                is_significant = False
                relative_improvement = None

        # Confidence interval using the normal approximation
        if assignments[variant_id] > 0:
            proportion = rates[variant_id] / 100  # Convert percentage to proportion
            z = 1.96  # For 95% confidence level

            se = math.sqrt((proportion * (1 - proportion)) / assignments[variant_id])

            ci_lower = max(0, (proportion - z * se) * 100)
            ci_upper = min(100, (proportion + z * se) * 100)
        else:
            ci_lower = 0
            ci_upper = 0

        results.append(
            {
                "variant_id": variant_id,
                "variant_name": variant.name,
                "is_control": variant.is_control,
                "sample_size": assignments[variant_id],
                "conversions": conversions[variant_id],
                "conversion_rate": rates[variant_id],
                "confidence_interval": [ci_lower, ci_upper],
                "p_value": p_value,
                "is_significant": is_significant,
                "relative_improvement": relative_improvement,
            }
        )

    return results


def binomial_metric_result(
    variants: Sequence[BinomialCounts],
    alpha: float,
    correction_method: str,
    *,
    metric: Any,
) -> Dict[str, Any]:
    """One proportion metric's result from per-variant counts.

    Args:
        variants: ``(variant, n, n_converted)`` per variant, in report order.
            ``variant`` has ``id``, ``name`` and ``is_control``
            (``BinomialVariant`` or an ORM ``Variant``); exactly one should be
            the control.
        alpha: significance level for ``is_significant`` and observed power.
        correction_method: ``none``, ``bonferroni`` or ``benjamini_hochberg``,
            applied across the treatments of this metric.
        metric: the metric's identity: ``id``, ``name``, ``metric_type`` and
            ``is_primary``, which the result carries.

    Returns:
        A dict in the shape of ``schemas.results.MetricResult``, exactly what
        ``/results`` returns in ``metrics`` for the same counts.

    Raises:
        ValueError: when no variant is the control.
    """
    variant_results = binomial_variant_results(variants)

    control = next((v for v in variant_results if v["is_control"]), None)
    control_rate = (control["conversion_rate"] / 100.0) if control else 0.0
    treatments = [v for v in variant_results if not v["is_control"]]
    adjusted = adjusted_p_values(
        [v.get("p_value") for v in treatments], correction_method
    )
    adjusted_by_id = {v["variant_id"]: a for v, a in zip(treatments, adjusted)}

    results: List[Dict[str, Any]] = []
    for v in variant_results:
        rate = v["conversion_rate"] / 100.0
        n = v["sample_size"]
        std_dev = math.sqrt(rate * (1 - rate)) if n > 0 else None
        ci_low, ci_high = v["confidence_interval"]
        entry: Dict[str, Any] = {
            "variant_id": v["variant_id"],
            "variant_name": v["variant_name"],
            "is_control": v["is_control"],
            "sample_size": n,
            "conversions": v["conversions"],
            "mean": rate,
            "std_dev": std_dev,
            "confidence_interval": (ci_low / 100.0, ci_high / 100.0),
            "p_value": None,
            "adjusted_p_value": None,
            "is_significant": False,
            "effect_size": None,
            "effect_size_label": None,
            "relative_improvement_pct": None,
            "power": None,
            "statistical_test_used": None,
        }
        if not v["is_control"]:
            p_value = v.get("p_value")
            adj = adjusted_by_id.get(v["variant_id"])
            decisive = adj if adj is not None else p_value
            improvement = v.get("relative_improvement")
            if improvement is not None and not math.isfinite(improvement):
                improvement = None
            effect = None
            if n > 0 and control and control["sample_size"] > 0:
                # Cohen's h for two proportions
                effect = 2 * math.asin(math.sqrt(rate)) - 2 * math.asin(
                    math.sqrt(control_rate)
                )
            power = None
            if effect is not None and control and control["sample_size"] > 0 and n > 0:
                try:
                    from statsmodels.stats.power import NormalIndPower

                    power = float(
                        NormalIndPower().power(
                            effect_size=abs(effect),
                            nobs1=n,
                            alpha=alpha,
                            ratio=control["sample_size"] / n,
                        )
                    )
                except Exception:
                    power = None
            entry.update(
                p_value=p_value,
                adjusted_p_value=adj,
                is_significant=bool(decisive is not None and decisive < alpha),
                effect_size=effect,
                effect_size_label=effect_size_label(abs(effect))
                if effect is not None
                else None,
                relative_improvement_pct=improvement,
                power=power,
                statistical_test_used="fisher_exact" if p_value is not None else None,
            )
        results.append(entry)

    winners = [
        v
        for v in results
        if not v["is_control"]
        and v["is_significant"]
        and (v["relative_improvement_pct"] or 0) > 0
    ]
    winner = max(winners, key=lambda v: v["mean"]) if winners else None
    metric_type = (
        metric.metric_type.value
        if hasattr(metric.metric_type, "value")
        else str(metric.metric_type)
    )
    return {
        "metric_id": str(metric.id),
        "metric_name": metric.name,
        "metric_type": metric_type,
        "is_primary": bool(metric.is_primary),
        "variants": results,
        "has_significant_result": any(v["is_significant"] for v in results),
        "winning_variant_id": winner["variant_id"] if winner else None,
    }


# ---------------------------------------------------------------------------
# Mean metrics from centred sums
# ---------------------------------------------------------------------------

#: ``(variant, n, sum_d, sum_d2)``: the units in the variant and, over their
#: values ``y``, ``sum(y - k)`` and ``sum((y - k) ** 2)`` for the grand mean
#: ``k`` the caller centred on.
MeanSums = Tuple[Any, int, float, float]

FEWER_THAN_2_UNITS = "fewer_than_2_units"
NO_VARIATION = "Not computed: no variation"


class SufficientStatsRefused(ValueError):
    """Sums that no sample could produce (a negative variance, a non-finite
    sum): the metric is refused, never computed.  ``code`` is
    ``result_invalid``."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "result_invalid"


class SufficientStatsNotComputed(ValueError):
    """Valid sums, but too few units to compute the metric from.

    ``code`` is ``fewer_than_2_units``; ``message`` is the text a reader sees.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _MeanArm(NamedTuple):
    variant: Any
    n: int
    c: float  # the centred mean, sum_d / n
    var: float  # the sample variance, ddof 1


def _mean_arm(variant: Any, n: Any, sum_d: Any, sum_d2: Any) -> _MeanArm:
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise SufficientStatsRefused("n is not a non-negative integer")
    sum_d = float(sum_d)
    sum_d2 = float(sum_d2)
    if not (math.isfinite(sum_d) and math.isfinite(sum_d2)):
        raise SufficientStatsRefused("a sum is not finite")
    if n < 2:
        raise SufficientStatsNotComputed(
            FEWER_THAN_2_UNITS, "Not computed: fewer than 2 units"
        )
    c = sum_d / n
    var = (sum_d2 - sum_d * sum_d / n) / (n - 1)
    if not math.isfinite(var) or var < 0:
        # No sample has these sums; refused rather than clamped to 0.
        raise SufficientStatsRefused("the sums give a negative variance")
    return _MeanArm(variant, n, c, var)


def _mean_comparison(
    arm: _MeanArm, control: _MeanArm, k: float, alpha: float
) -> Dict[str, Any]:
    """One treatment against the control: p-value, effect size, power and
    relative improvement, or None for each that cannot be computed."""
    from statsmodels.stats.power import NormalIndPower

    diff = arm.c - control.c
    control_mean = k + control.c
    improvement = diff / abs(control_mean) * 100 if control_mean != 0 else None
    if arm.var == 0 and control.var == 0:
        return {
            "p_value": None,
            "effect_size": None,
            "power": None,
            "relative_improvement_pct": improvement,
            "note": NO_VARIATION,
        }
    # The centred means go in, never k + c: at a large k the reconstructed
    # means round away most of the difference.
    p_value = float(
        stats.ttest_ind_from_stats(
            arm.c,
            math.sqrt(arm.var),
            arm.n,
            control.c,
            math.sqrt(control.var),
            control.n,
            equal_var=False,
        ).pvalue
    )
    effect = diff / math.sqrt((control.var + arm.var) / 2.0)
    power: Optional[float]
    try:
        power = float(
            NormalIndPower().power(
                effect_size=abs(effect),
                nobs1=arm.n,
                alpha=alpha,
                ratio=control.n / arm.n,
            )
        )
    except Exception:
        power = None
    return {
        "p_value": p_value,
        "effect_size": effect,
        "power": power,
        "relative_improvement_pct": improvement,
        "note": None,
    }


def mean_metric_result(
    k: float,
    variants: Sequence[MeanSums],
    alpha: float,
    correction_method: str,
    *,
    metric: Any,
) -> Dict[str, Any]:
    """One mean metric's result from per-variant sums centred on ``k``.

    The sums are centred so that a large offset (order values in the
    thousands, say) does not cancel the variance away: ``k`` is the grand mean
    over every unit, ``sum_d = sum(y - k)`` and ``sum_d2 = sum((y - k) ** 2)``.
    Everything compared across variants uses the centred means ``sum_d / n``,
    in which ``k`` cancels; ``k`` is added back only to the reported ``mean``
    and interval.

    Per variant: ``mean = k + sum_d / n``; the sample variance (ddof 1) and
    its square root as ``std_dev``; and ``mean +/- t(1 - alpha/2, n - 1) *
    sqrt(var / n)`` as the interval.  Per treatment, against the control:
    Welch's t-test p-value, Cohen's d as ``AnalysisService.cohens_d`` defines
    it, observed power at ``alpha`` (``NormalIndPower``, the convention of the
    proportion results) and the relative improvement in percent, which is None
    when the control's mean is 0.  When neither the treatment nor the control
    varies, the p-value, effect size and power are None and the treatment's
    ``note`` says so.

    Args:
        k: the grand mean the sums are centred on.
        variants: ``(variant, n, sum_d, sum_d2)`` per variant, in report
            order; ``variant`` has ``id``, ``name`` and ``is_control``, and
            exactly one should be the control.
        alpha: significance level for the interval, ``is_significant`` and
            observed power.
        correction_method: ``none``, ``bonferroni`` or ``benjamini_hochberg``,
            applied across the treatments of this metric.
        metric: the metric's identity: ``id``, ``name``, ``metric_type`` and
            ``is_primary``, which the result carries.

    Returns:
        A dict in the shape of ``schemas.results.MetricResult``.  Each variant
        also carries ``note``: None, or why a comparison was not computed.

    Raises:
        SufficientStatsRefused: a count or sum is malformed or not finite, or
            the sums give a negative variance.
        SufficientStatsNotComputed: a variant has fewer than 2 units.
        ValueError: when no variant is the control.
    """
    k = float(k)
    if not math.isfinite(k):
        raise SufficientStatsRefused("k is not finite")
    arms = [_mean_arm(*row) for row in variants]
    control = next((a for a in arms if a.variant.is_control), None)
    if control is None:
        raise ValueError("No variant is the control")

    comparisons = [
        _mean_comparison(arm, control, k, alpha)
        for arm in arms
        if not arm.variant.is_control
    ]
    adjusted = adjusted_p_values(
        [comparison["p_value"] for comparison in comparisons], correction_method
    )
    pending = list(zip(comparisons, adjusted))

    results: List[Dict[str, Any]] = []
    for arm in arms:
        mean = k + arm.c
        half_width = float(stats.t.ppf(1 - alpha / 2, arm.n - 1)) * math.sqrt(
            arm.var / arm.n
        )
        entry: Dict[str, Any] = {
            "variant_id": str(arm.variant.id),
            "variant_name": arm.variant.name,
            "is_control": arm.variant.is_control,
            "sample_size": arm.n,
            "conversions": None,
            "mean": mean,
            "std_dev": math.sqrt(arm.var),
            "confidence_interval": (mean - half_width, mean + half_width),
            "p_value": None,
            "adjusted_p_value": None,
            "is_significant": False,
            "effect_size": None,
            "effect_size_label": None,
            "relative_improvement_pct": None,
            "power": None,
            "statistical_test_used": None,
            "note": None,
        }
        if not arm.variant.is_control:
            # Treatments come out of `pending` in the order they went in.
            comparison, adj = pending.pop(0)
            p_value = comparison["p_value"]
            decisive = adj if adj is not None else p_value
            effect = comparison["effect_size"]
            entry.update(
                p_value=p_value,
                adjusted_p_value=adj,
                is_significant=bool(decisive is not None and decisive < alpha),
                effect_size=effect,
                effect_size_label=effect_size_label(abs(effect))
                if effect is not None
                else None,
                relative_improvement_pct=comparison["relative_improvement_pct"],
                power=comparison["power"],
                statistical_test_used="welch_t_test" if p_value is not None else None,
                note=comparison["note"],
            )
        results.append(entry)

    # A winner is significant and above the control, compared on the centred
    # means (a relative improvement is None when the control's mean is 0).
    winners = [
        (entry, arm)
        for entry, arm in zip(results, arms)
        if not entry["is_control"] and entry["is_significant"] and arm.c > control.c
    ]
    winner = max(winners, key=lambda pair: pair[1].c)[0] if winners else None
    metric_type = (
        metric.metric_type.value
        if hasattr(metric.metric_type, "value")
        else str(metric.metric_type)
    )
    return {
        "metric_id": str(metric.id),
        "metric_name": metric.name,
        "metric_type": metric_type,
        "is_primary": bool(metric.is_primary),
        "variants": results,
        "has_significant_result": any(v["is_significant"] for v in results),
        "winning_variant_id": winner["variant_id"] if winner else None,
    }
