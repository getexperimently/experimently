"""
Benjamini-Hochberg FDR Correction Service — EP-043.

Implements the Benjamini-Hochberg (1995) step-up procedure for controlling
the False Discovery Rate (FDR) across multiple simultaneous hypothesis tests.

BH is less conservative than Bonferroni for ≥5 metrics while still
controlling the expected proportion of false discoveries among rejected
hypotheses at the specified FDR threshold.

Reference:
    Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate:
    A practical and powerful approach to multiple testing.
    Journal of the Royal Statistical Society. Series B, 57(1), 289–300.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class FDRResult:
    """Result for a single metric after Benjamini-Hochberg FDR correction.

    Attributes:
        metric_name: Name of the metric / hypothesis tested.
        raw_p_value: Original uncorrected p-value.
        adjusted_p_value: BH-adjusted p-value (Holm step-up formula).
            Monotonically non-decreasing when sorted by rank.
        rank: Rank of this metric when p-values are sorted ascending (1 = smallest).
        is_significant: True if this metric is rejected after BH correction.
    """

    metric_name: str
    raw_p_value: float
    adjusted_p_value: float
    rank: int
    is_significant: bool


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class BenjaminiHochbergService:
    """
    Service for Benjamini-Hochberg FDR correction of multiple p-values.

    The BH procedure:
    1. Sort m p-values in ascending order: p(1) ≤ p(2) ≤ … ≤ p(m).
    2. For each rank k (1-indexed), compute the BH threshold: k/m * α.
    3. Find the largest k where p(k) ≤ k/m * α. Call it k*.
    4. Reject (declare significant) all hypotheses with rank ≤ k*.

    Adjusted p-values follow the Holm step-up formula for the BH procedure:
        p_adj(k) = min(p(k) * m/k, 1.0)
    applied in reverse rank order to enforce monotonicity (non-decreasing).

    Usage::

        svc = BenjaminiHochbergService()
        results = svc.correct(
            p_values={"revenue": 0.001, "clicks": 0.08, "churn": 0.5},
            fdr_threshold=0.05,
        )
    """

    def correct(
        self,
        p_values: Dict[str, float],
        fdr_threshold: float = 0.05,
    ) -> List[FDRResult]:
        """
        Apply the Benjamini-Hochberg FDR correction to a set of p-values.

        Args:
            p_values: Mapping of metric_name → raw p-value. All p-values must
                be in [0, 1]. The dict must be non-empty.
            fdr_threshold: Desired FDR control level (α). Default 0.05.

        Returns:
            List of FDRResult objects, one per metric, in rank-ascending order
            (smallest raw p-value first).
        """
        if not p_values:
            return []

        m = len(p_values)

        # Step 1: Sort by p-value ascending
        sorted_items: List[Tuple[str, float]] = sorted(
            p_values.items(), key=lambda x: x[1]
        )

        # Step 2-3: Find the largest rank k* where p(k) ≤ (k/m) * α
        cutoff_rank = 0
        for k, (name, p) in enumerate(sorted_items, start=1):
            bh_threshold = (k / m) * fdr_threshold
            if p <= bh_threshold:
                cutoff_rank = k
        # All hypotheses with rank ≤ cutoff_rank are rejected

        # Step 4: Compute adjusted p-values (Holm step-up BH formula)
        # Raw adjusted: p_adj(k) = min(p(k) * m / k, 1.0)
        # Then enforce monotonicity from largest rank downward (step-up):
        # p_adj_monotone(k) = min(p_adj(k), p_adj_monotone(k+1))
        raw_adjusted = []
        for k, (name, p) in enumerate(sorted_items, start=1):
            raw_adjusted.append(min(p * m / k, 1.0))

        # Enforce non-decreasing monotonicity (step-up from the right)
        monotone_adjusted = raw_adjusted[:]
        for i in range(len(monotone_adjusted) - 2, -1, -1):
            monotone_adjusted[i] = min(monotone_adjusted[i], monotone_adjusted[i + 1])

        # Build results
        results: List[FDRResult] = []
        for rank_idx, ((name, p), adj_p) in enumerate(
            zip(sorted_items, monotone_adjusted), start=1
        ):
            results.append(
                FDRResult(
                    metric_name=name,
                    raw_p_value=float(p),
                    adjusted_p_value=float(adj_p),
                    rank=rank_idx,
                    is_significant=rank_idx <= cutoff_rank,
                )
            )

        return results
