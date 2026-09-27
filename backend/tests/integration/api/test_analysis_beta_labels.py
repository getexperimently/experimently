"""
DB-backed regressions for #217 (CUPED) and #219 (interaction analysis).

* ``GET /results/{id}/cuped`` with the method ``none`` applies no adjustment:
  θ is exactly 0.0, ``variance_reduction_pct`` exactly 0.0, and the "adjusted"
  means are the raw conversion rates.  Before the fix θ was estimated from the
  assignment-order covariate anyway (3.8e-8 on the demo experiment, larger on
  the ordered data below).
* CUPED counts conversions with ``event_matching.conversion_event_filter``: an
  exposure row carrying the metric's event name is not a conversion.
* #219's exact case -- two experiments sharing the same 40 users and no events
  -- answers with the overlap (1.0) and null interaction, novelty and SUTVA
  results, and ``/novelty`` never answers ``has_novelty: false``.
* Every one of these responses carries the ``analysis_status`` and
  ``analysis_notice`` the table in ``backend/app/core/analysis_status.py`` holds.

Rows created here are deleted in fixture teardown because the shared test
database is not truncated between tests.
"""

import uuid
from datetime import datetime, timezone

import pytest

from backend.app.core.analysis_status import ANALYSIS_STATUS
from backend.app.models.analysis_snapshot import AnalysisSnapshot
from backend.app.models.assignment import Assignment
from backend.app.models.event import Event
from backend.app.models.experiment import (
    ExperimentStatus,
    ExperimentType,
    Metric,
    MetricType,
    Variant,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]


def _cleanup(db_session, experiment_ids):
    db_session.rollback()
    for model in (AnalysisSnapshot, Event, Assignment):
        db_session.query(model).filter(model.experiment_id.in_(experiment_ids)).delete(
            synchronize_session=False
        )
    db_session.commit()


def _make_ab(make_experiment, db_session, label, **kwargs):
    suffix = uuid.uuid4().hex[:8]
    experiment = make_experiment(
        name=f"{label} {suffix}",
        key=f"{label.lower().replace(' ', '-')}-{suffix}",
        status=ExperimentStatus.ACTIVE,
        experiment_type=ExperimentType.A_B,
        start_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
        **kwargs,
    )
    for name, is_control in (("control", True), ("treatment", False)):
        db_session.add(
            Variant(
                experiment_id=experiment.id,
                name=name,
                is_control=is_control,
                traffic_allocation=50,
            )
        )
    db_session.add(
        Metric(
            experiment_id=experiment.id,
            name="Purchase",
            event_name="purchase",
            metric_type=MetricType.CONVERSION,
            is_primary=True,
        )
    )
    db_session.commit()
    db_session.refresh(experiment)
    return experiment


def _variant(experiment, name):
    return next(v for v in experiment.variants if v.name == name)


# ---------------------------------------------------------------------------
# CUPED (#217)
# ---------------------------------------------------------------------------


@pytest.fixture
def cuped_experiment(db_session, make_experiment):
    """ACTIVE 50/50 experiment, no variance_reduction_config (method none)."""
    experiment = _make_ab(make_experiment, db_session, "Cuped none")
    yield experiment
    _cleanup(db_session, [experiment.id])


def _seed_ordered(db_session, experiment, variant, n_users, n_converted, n_exposed):
    """Assign ``n_users``; the FIRST ``n_converted`` purchase.

    Conversions concentrated at the start of the assignment order make the
    assignment-order covariate correlate with the outcome, so any θ estimated
    from it is clearly non-zero.  ``n_exposed`` of the non-converting users also
    get an *exposure* row named after the metric: never a conversion.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    prefix = f"{variant.name}-{uuid.uuid4().hex[:6]}"
    for i in range(n_users):
        user_id = f"{prefix}-{i:05d}"
        db_session.add(
            Assignment(
                experiment_id=experiment.id, variant_id=variant.id, user_id=user_id
            )
        )
        # One commit per assignment keeps the rows in assignment order.
        db_session.commit()
        if i < n_converted:
            event_type = "purchase"
        elif i < n_converted + n_exposed:
            event_type = "exposure"
        else:
            continue
        db_session.add(
            Event(
                event_type=event_type,
                event_name="purchase",
                user_id=user_id,
                experiment_id=experiment.id,
                variant_id=variant.id,
                value=1.0,
                created_at=now_iso,
            )
        )
        db_session.commit()


@pytest.mark.regression
def test_cuped_method_none_applies_no_adjustment(
    admin_client, db_session, cuped_experiment
):
    """#217: ``none`` gives θ exactly 0 and the unadjusted estimate."""
    _seed_ordered(
        db_session, cuped_experiment, _variant(cuped_experiment, "control"), 40, 4, 0
    )
    _seed_ordered(
        db_session, cuped_experiment, _variant(cuped_experiment, "treatment"), 40, 10, 0
    )

    response = admin_client.get(f"/api/v1/results/{cuped_experiment.id}/cuped")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["method"] == "none"
    [metric] = body["metrics"]
    assert metric["method"] == "none"
    assert metric["theta"] == 0.0
    assert metric["variance_reduction_pct"] == 0.0
    assert metric["adjusted_control_mean"] == pytest.approx(4 / 40, abs=1e-12)
    assert metric["adjusted_treatment_mean"] == pytest.approx(10 / 40, abs=1e-12)
    assert metric["adjusted_effect"] == pytest.approx(6 / 40, abs=1e-12)


@pytest.mark.regression
def test_cuped_does_not_count_an_exposure_row_as_a_conversion(
    admin_client, db_session, cuped_experiment
):
    """#217: conversions are matched with event_matching, not event_name alone."""
    # control: 4 purchases, 10 exposure rows named "purchase"; treatment: 8, 0.
    _seed_ordered(
        db_session, cuped_experiment, _variant(cuped_experiment, "control"), 40, 4, 10
    )
    _seed_ordered(
        db_session, cuped_experiment, _variant(cuped_experiment, "treatment"), 40, 8, 0
    )

    response = admin_client.get(f"/api/v1/results/{cuped_experiment.id}/cuped")

    assert response.status_code == 200, response.text
    [metric] = response.json()["metrics"]
    # 4/40, not (4 + 10)/40
    assert metric["adjusted_control_mean"] == pytest.approx(4 / 40, abs=1e-12)
    assert metric["adjusted_treatment_mean"] == pytest.approx(8 / 40, abs=1e-12)


def test_cuped_response_carries_the_tables_label(
    admin_client, db_session, cuped_experiment
):
    """``analysis_status``/``analysis_notice`` come from the one table."""
    response = admin_client.get(f"/api/v1/results/{cuped_experiment.id}/cuped")

    assert response.status_code == 200, response.text
    body = response.json()
    label = ANALYSIS_STATUS["cuped"]
    assert body["analysis_status"] == label.status == "beta"
    assert body["analysis_notice"] == label.notice
    assert "/issues/217" in body["analysis_notice"]


# ---------------------------------------------------------------------------
# Interaction analysis (#219)
# ---------------------------------------------------------------------------


@pytest.fixture
def shared_pair(db_session, make_experiment):
    """#219's case: two experiments, the same 40 users in both, no events."""
    first = _make_ab(make_experiment, db_session, "Pricing page")
    second = _make_ab(make_experiment, db_session, "Onboarding flow")
    rows = []
    for i in range(40):
        user_id = f"shared-user-{uuid.uuid4().hex[:6]}-{i}"
        for experiment in (first, second):
            variant = _variant(experiment, "control" if i % 2 else "treatment")
            rows.append(
                Assignment(
                    experiment_id=experiment.id,
                    variant_id=variant.id,
                    user_id=user_id,
                )
            )
    db_session.add_all(rows)
    db_session.commit()
    yield first, second
    _cleanup(db_session, [first.id, second.id])


@pytest.mark.regression
def test_shared_users_and_no_events_give_the_overlap_and_nulls(
    admin_client, shared_pair
):
    """#219: no interaction/novelty/SUTVA result is invented from user counts."""
    first, second = shared_pair

    response = admin_client.get(f"/api/v1/interactions/{first.id}/{second.id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["overlap_coefficient"] == 1.0
    assert body["has_significant_overlap"] is True
    assert body["interaction_result"] is None
    assert body["novelty_result"] is None
    assert body["sutva_result"] is None
    # From the overlap alone: 1.0 is above the 0.6 high-overlap band.
    assert body["overall_risk"] == "high"
    label = ANALYSIS_STATUS["interactions"]
    assert body["analysis_status"] == label.status == "beta"
    assert body["analysis_notice"] == label.notice
    assert "/issues/219" in body["analysis_notice"]


@pytest.mark.regression
def test_novelty_is_not_computed_never_false(admin_client, shared_pair):
    """#219: /novelty says not computed; it never answers has_novelty false."""
    first, second = shared_pair

    response = admin_client.get(f"/api/v1/interactions/{first.id}/{second.id}/novelty")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_novelty"] is not False
    assert body["computed"] is False
    assert body["has_novelty"] is None
    assert body["decline_rate"] is None
    label = ANALYSIS_STATUS["novelty"]
    assert body["analysis_status"] == label.status == "beta"
    assert body["analysis_notice"] == label.notice
