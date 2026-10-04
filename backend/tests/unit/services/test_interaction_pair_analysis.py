"""
The pair analysis of ``GET /interactions/{a}/{b}`` (beta, #219), on fake readers.

The readers (``_arm_totals``, ``_shared_assignments`` and
``converting_user_ids``) are replaced by an in-memory population, so these
tests check what the service decides from the counts: the overlap, the reason
codes and their order, the rows that are never dropped, and the null that
never reads as "no interaction".  The readers themselves run against
PostgreSQL in ``backend/tests/integration/api/test_interaction_pair_api.py``.
"""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.models.experiment import MetricType
from backend.app.services import interaction_analysis as ia
from backend.app.services.interaction_detection_service import (
    InteractionDetectionService,
)

pytestmark = pytest.mark.unit

SERVICE = "backend.app.services.interaction_detection_service"


def _experiment(
    name: str,
    variants=("control", "treatment"),
    metric_type=MetricType.CONVERSION,
    with_metric: bool = True,
    with_control: bool = True,
    group=None,
    correction: str = "benjamini_hochberg",
    level: float = 0.95,
):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        variants=[
            SimpleNamespace(id=uuid4(), name=v, is_control=(with_control and i == 0))
            for i, v in zip(range(len(variants)), variants)
        ],
        metric_definitions=(
            [
                SimpleNamespace(
                    id=uuid4(),
                    name="Signup",
                    event_name="signup",
                    metric_type=metric_type,
                    is_primary=True,
                )
            ]
            if with_metric
            else []
        ),
        mutual_exclusion_group_id=group,
        correction_method=correction,
        confidence_level=level,
    )


@dataclass
class User:
    user_id: str
    a: Optional[str]  # variant name in experiment A, or None
    b: Optional[str]
    converts_a: bool = False
    converts_b: bool = False


def cell(a, b, n, converts_a=0, converts_b=0, tag="") -> List[User]:
    """``n`` users in (a, b); the first ``converts_*`` of them convert."""
    return [
        User(f"{tag}{a}-{b}-{i}", a, b, i < converts_a, i < converts_b)
        for i in range(n)
    ]


class Population:
    """The readers' answers for a population of users."""

    def __init__(self, exp_a, exp_b, users: List[User]):
        self.exps = {str(exp_a.id): (exp_a, "a"), str(exp_b.id): (exp_b, "b")}
        self.users = users

    def _vid(self, exp, name):
        return str(next(v.id for v in exp.variants if v.name == name))

    def arm_totals(self, db, experiment_id) -> Dict[str, int]:
        exp, side = self.exps[str(experiment_id)]
        out: Dict[str, int] = {}
        for u in self.users:
            name = getattr(u, side)
            if name is not None:
                vid = self._vid(exp, name)
                out[vid] = out.get(vid, 0) + 1
        return out

    def shared(self, db, smaller_id, larger_id):
        s_exp, s_side = self.exps[str(smaller_id)]
        l_exp, l_side = self.exps[str(larger_id)]
        return {
            u.user_id: (
                self._vid(s_exp, getattr(u, s_side)),
                self._vid(l_exp, getattr(u, l_side)),
            )
            for u in self.users
            if u.a is not None and u.b is not None
        }

    def converters(self, db, experiment_id, variant_id, event_name):
        exp, side = self.exps[str(experiment_id)]
        return {
            u.user_id
            for u in self.users
            if getattr(u, side) is not None
            and self._vid(exp, getattr(u, side)) == str(variant_id)
            and getattr(u, f"converts_{side}")
        }


def analyse(exp_a, exp_b, users: List[User]):
    population = Population(exp_a, exp_b, users)
    service = InteractionDetectionService()
    with (
        patch.object(
            InteractionDetectionService,
            "_arm_totals",
            side_effect=population.arm_totals,
        ),
        patch.object(
            InteractionDetectionService,
            "_shared_assignments",
            side_effect=population.shared,
        ),
        patch(f"{SERVICE}.converting_user_ids", side_effect=population.converters),
    ):
        return service.analyze_pair_interactions(exp_a, exp_b, MagicMock())


def reasons(response):
    return [row.unavailable_reason for row in response.interaction_results]


# ---------------------------------------------------------------------------
# Overlap: the real value, never zeroed
# ---------------------------------------------------------------------------


def test_no_shared_users_gives_one_row_per_experiment_and_a_null_verdict():
    """The demo's two running experiments: no_shared_users on both rows."""
    a, b = _experiment("Checkout"), _experiment("Recommendations")
    users = cell("control", None, 5, tag="a") + cell(None, "control", 5, tag="b")
    response = analyse(a, b, users)
    assert response.shared_users == 0
    assert response.overlap_coefficient == 0.0
    assert reasons(response) == [ia.NO_SHARED_USERS, ia.NO_SHARED_USERS]
    assert [row.variant_id for row in response.interaction_results] == [None, None]
    assert response.has_interaction is None


@pytest.mark.regression
def test_a_small_experiment_inside_a_large_one_reports_its_real_overlap():
    """A (100 users) entirely inside B (1,000): Jaccard 0.1, share_of_a 1.0.

    The old route answered overlap 0.0, risk low and "not required" here.
    """
    a, b = _experiment("Small"), _experiment("Large")
    users = cell("control", "control", 50) + cell("treatment", "control", 50)
    users += cell(None, "treatment", 900, tag="b-only")
    response = analyse(a, b, users)
    assert response.shared_users == 100
    assert response.share_of_a == 1.0
    assert response.share_of_b == pytest.approx(0.1)
    assert response.overlap_coefficient == pytest.approx(0.1)
    assert response.has_significant_overlap is False
    assert not any("not required" in rec for rec in response.recommendations)
    assert "overall_risk" not in response.model_dump()


def test_an_overlap_below_the_threshold_is_reported_as_it_is():
    a, b = _experiment("A"), _experiment("B")
    # 20 shared, 40 only in A, 40 only in B: 20 / 100 = 0.2
    users = cell("control", "control", 20)
    users += cell("treatment", None, 40, tag="a") + cell(None, "treatment", 40, tag="b")
    response = analyse(a, b, users)
    assert response.overlap_coefficient == pytest.approx(0.2)
    assert response.share_of_a == pytest.approx(20 / 60)


# ---------------------------------------------------------------------------
# Reason codes and their order
# ---------------------------------------------------------------------------


def _docs_40() -> List[User]:
    """The docs page's 40 shared users: 9/10/12/9, nobody converts."""
    return (
        cell("control", "control", 9)
        + cell("control", "treatment", 10)
        + cell("treatment", "control", 12)
        + cell("treatment", "treatment", 9)
    )


@pytest.mark.regression
def test_forty_shared_users_with_no_conversions_are_too_few_users_first():
    """6 before 7: too_few_shared_users wins over too_few_conversions."""
    a, b = _experiment("Pricing page"), _experiment("Onboarding flow")
    response = analyse(a, b, _docs_40())
    assert response.shared_users == 40
    assert reasons(response) == [ia.TOO_FEW_SHARED_USERS] * 2
    row = response.interaction_results[0]
    assert [(arm.n_control, arm.n_treatment) for arm in row.arms] == [(9, 12), (10, 9)]
    assert response.has_interaction is None
    assert response.min_users_per_cell == 100
    assert response.min_expected_per_cell == 25


def test_same_group_with_no_shared_users_is_reported_as_the_group():
    """1 before 2, and the group id is returned."""
    group = uuid4()
    a, b = _experiment("A", group=group), _experiment("B", group=group)
    users = cell("control", None, 5, tag="a") + cell(None, "control", 5, tag="b")
    response = analyse(a, b, users)
    assert reasons(response) == [ia.MUTUAL_EXCLUSION_GROUP] * 2
    assert response.mutual_exclusion_group_id == str(group)


def test_same_group_still_reports_the_overlap():
    group = uuid4()
    a, b = _experiment("A", group=group), _experiment("B", group=group)
    response = analyse(a, b, _docs_40())
    assert response.shared_users == 40
    assert response.overlap_coefficient == 1.0
    assert reasons(response) == [ia.MUTUAL_EXCLUSION_GROUP] * 2


def test_different_groups_are_not_the_same_group():
    a, b = _experiment("A", group=uuid4()), _experiment("B", group=uuid4())
    response = analyse(a, b, _docs_40())
    assert response.mutual_exclusion_group_id is None
    assert reasons(response) == [ia.TOO_FEW_SHARED_USERS] * 2


def test_one_experiment_in_a_group_is_not_the_same_group():
    a, b = _experiment("A", group=uuid4()), _experiment("B")
    response = analyse(a, b, _docs_40())
    assert response.mutual_exclusion_group_id is None


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"with_metric": False}, ia.NO_METRIC),
        ({"metric_type": MetricType.REVENUE}, ia.NOT_A_PROPORTION_METRIC),
        ({"metric_type": MetricType.COUNT}, ia.NOT_A_PROPORTION_METRIC),
        ({"with_control": False}, ia.NO_CONTROL_VARIANT),
        # The order: 3 before 4 before 5.
        ({"with_metric": False, "with_control": False}, ia.NO_METRIC),
        (
            {"metric_type": MetricType.REVENUE, "with_control": False},
            ia.NOT_A_PROPORTION_METRIC,
        ),
    ],
)
def test_experiment_level_reasons_give_one_row_and_spare_the_other(kwargs, reason):
    a = _experiment("A", variants=("control", "t1", "t2"), **kwargs)
    b = _experiment("B")
    users = []
    for va in ("control", "t1", "t2"):
        users += cell(va, "control", 10, tag="x") + cell(va, "treatment", 10, tag="y")
    response = analyse(a, b, users)
    rows_a = [r for r in response.interaction_results if r.experiment_id == str(a.id)]
    rows_b = [r for r in response.interaction_results if r.experiment_id == str(b.id)]
    assert [r.unavailable_reason for r in rows_a] == [reason]
    assert rows_a[0].variant_id is None
    assert rows_a[0].arms == []
    # B's direction is still worked out (too few users here, but per treatment).
    assert [r.unavailable_reason for r in rows_b] == [ia.TOO_FEW_SHARED_USERS]
    assert rows_b[0].variant_id is not None


def test_every_treatment_has_a_row():
    a = _experiment("A", variants=("control", "t1", "t2", "t3"))
    b = _experiment("B", variants=("control", "t1"))
    users = []
    for va in ("control", "t1", "t2", "t3"):
        users += cell(va, "control", 5, tag="x") + cell(va, "t1", 5, tag="y")
    response = analyse(a, b, users)
    assert len(response.interaction_results) == 3 + 1
    assert [r.variant_name for r in response.interaction_results] == [
        "t1",
        "t2",
        "t3",
        "t1",
    ]


def test_one_arm_with_shared_users_is_too_few():
    a, b = _experiment("A"), _experiment("B")
    users = cell("control", "control", 500, 100, 100)
    users += cell("treatment", "control", 500, 100, 100)
    users += cell(None, "treatment", 500, tag="b-only")
    response = analyse(a, b, users)
    assert reasons(response)[0] == ia.TOO_FEW_SHARED_USERS
    assert len(response.interaction_results[0].arms) == 1


@pytest.mark.regression
def test_ninety_nine_users_in_one_cell_is_too_few():
    a, b = _experiment("A"), _experiment("B")
    users = cell("control", "control", 99, 50, 50)
    users += cell("control", "treatment", 1000, 500, 500)
    users += cell("treatment", "control", 1000, 500, 500)
    users += cell("treatment", "treatment", 1000, 500, 500)
    response = analyse(a, b, users)
    assert reasons(response) == [ia.TOO_FEW_SHARED_USERS] * 2


def test_too_few_expected_conversions():
    a, b = _experiment("A"), _experiment("B")
    users = []
    for va in ("control", "treatment"):
        for vb in ("control", "treatment"):
            users += cell(va, vb, 200, 2, 2)
    response = analyse(a, b, users)
    assert reasons(response) == [ia.TOO_FEW_CONVERSIONS] * 2


def test_arms_are_ordered_control_first_then_by_name():
    a = _experiment("A")
    b = _experiment("B", variants=("base", "zeta", "alpha"))
    users = []
    for vb in ("zeta", "alpha", "base"):
        users += cell("control", vb, 3, tag="c") + cell("treatment", vb, 3, tag="t")
    response = analyse(a, b, users)
    names = [arm.other_variant_name for arm in response.interaction_results[0].arms]
    assert names == ["base", "alpha", "zeta"]


def test_null_is_never_false_and_no_text_says_unadjusted_or_confounded():
    a, b = _experiment("A"), _experiment("B")
    response = analyse(a, b, _docs_40())
    for row in response.interaction_results:
        assert row.is_significant is None
        assert row.p_value is None
        assert row.corrected_p_value is None
    for rec in response.recommendations:
        for word in ("unadjusted", "confounded", "invalid", "wrong"):
            assert word not in rec.lower()
    assert any("not tested" in rec for rec in response.recommendations)


def test_the_reason_order_is_published():
    assert ia.UNAVAILABLE_REASONS == (
        "mutual_exclusion_group",
        "no_shared_users",
        "no_metric",
        "not_a_proportion_metric",
        "no_control_variant",
        "too_few_shared_users",
        "too_few_conversions",
    )


# ---------------------------------------------------------------------------
# Tested rows: the decision (needs the fit)
# ---------------------------------------------------------------------------


def _masked(a_variants=("control", "treatment")) -> List[User]:
    """A's treatment: +5 points in B's control, -5 points in B's treatment.

    2,000 users per cell, base 10%: A's pooled lift is 0, the interaction is
    large.  B has no effect of its own.
    """
    users = cell("control", "control", 2000, 200, 200)
    users += cell("control", "treatment", 2000, 200, 200)
    users += cell(a_variants[1], "control", 2000, 300, 200)
    users += cell(a_variants[1], "treatment", 2000, 100, 200)
    return users


@pytest.mark.regression
def test_s3_a_masked_effect_is_found():
    """The pooled lift is 0, so /results sees nothing; the interaction is found."""
    a, b = _experiment("Pricing"), _experiment("Onboarding")
    response = analyse(a, b, _masked())
    row_a, row_b = response.interaction_results
    assert row_a.unavailable_reason is None
    assert row_a.is_significant is True
    assert row_a.p_value < 1e-10
    assert [arm.effect for arm in row_a.arms] == pytest.approx([0.05, -0.05])
    assert [arm.relative_lift for arm in row_a.arms] == pytest.approx([0.5, -0.5])
    assert response.has_interaction is True
    found = [rec for rec in response.recommendations if "differs across" in rec]
    assert len(found) == 1
    assert "percentage points" in found[0]
    assert "corrected p" in found[0]
    assert "who enters" in found[0]
    # The two experiments' rows are 2 x 2 tables of different outcomes here.
    assert row_b.experiment_id == str(b.id)


def test_no_interaction_gives_false_only_when_every_row_was_tested():
    a, b = _experiment("A"), _experiment("B")
    users = []
    for va, xa in (("control", 200), ("treatment", 300)):
        for vb in ("control", "treatment"):
            users += cell(va, vb, 2000, xa, 200, tag=va)
    response = analyse(a, b, users)
    assert reasons(response) == [None, None]
    assert [row.is_significant for row in response.interaction_results] == [False] * 2
    assert response.has_interaction is False
    assert any("no interaction found" in rec for rec in response.recommendations)


def test_has_interaction_is_null_when_a_row_has_a_reason_and_none_is_significant():
    a, b = _experiment("A"), _experiment("B", metric_type=MetricType.REVENUE)
    users = []
    for va, xa in (("control", 200), ("treatment", 300)):
        for vb in ("control", "treatment"):
            users += cell(va, vb, 2000, xa, 200, tag=va)
    response = analyse(a, b, users)
    assert reasons(response) == [None, ia.NOT_A_PROPORTION_METRIC]
    assert response.interaction_results[0].is_significant is False
    assert response.has_interaction is None


def _two_treatments(correction):
    a = _experiment("A", variants=("control", "t1", "t2"), correction=correction)
    b = _experiment("B")
    users = _masked(("control", "t1"))
    users += cell("t2", "control", 2000, 220, 200, tag="t2")
    users += cell("t2", "treatment", 2000, 220, 200, tag="t2")
    return analyse(a, b, users)


def test_the_stored_correction_is_applied_across_the_experiments_rows():
    response = _two_treatments("bonferroni")
    t1, t2 = response.interaction_results[:2]
    assert t1.correction_method == "bonferroni"
    assert t1.corrected_p_value == pytest.approx(min(1.0, 2 * t1.p_value))
    assert t2.corrected_p_value == pytest.approx(min(1.0, 2 * t2.p_value))
    assert t1.is_significant is True


def test_correction_none_leaves_corrected_null_and_decides_on_p():
    response = _two_treatments("none")
    t1 = response.interaction_results[0]
    assert t1.corrected_p_value is None
    assert t1.is_significant is (t1.p_value < 0.05)
    found = [rec for rec in response.recommendations if "differs across" in rec]
    assert "(p = " in found[0]


def test_the_stored_level_decides():
    """A p-value between 0.01 and 0.05: significant at 0.95, not at 0.99."""
    users = []
    for va, lift in (("control", 0), ("treatment", 1)):
        users += cell(va, "control", 3000, 300 + 75 * lift, 300, tag="c")
        users += cell(va, "treatment", 3000, 300 + 0 * lift, 300, tag="t")
    rows = {}
    for level in (0.95, 0.99):
        a, b = _experiment("A", level=level), _experiment("B")
        rows[level] = analyse(a, b, users).interaction_results[0]
    p = rows[0.95].p_value
    assert 0.01 < p < 0.05
    assert rows[0.95].is_significant is True
    assert rows[0.99].is_significant is False
