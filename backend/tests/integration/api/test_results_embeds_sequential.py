"""
The results routes embed the sequential analysis (#922).

``GET /api/v1/results/{id}`` and ``GET /api/v1/experiments/{id}/results``
declare a ``sequential_testing`` field.  Until #922 nothing filled it: the
route read a key the analysis service never set, so it was ``null`` for every
experiment, sequential testing on or off.  With sequential testing on it now
carries the block ``GET /api/v1/results/{id}/sequential`` serves without an
``alpha`` parameter, computed by the same function.

Real ``AnalysisService`` and real rows: two variants, one primary conversion
metric (the analysis compares the control with the first treatment).
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text

from backend.app.api.v1.endpoints import results as results_endpoints
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

ROUTES = ("/api/v1/results/{id}", "/api/v1/experiments/{id}/results")


@pytest.fixture
def make_sequential_experiment(db_session, make_experiment):
    """An ACTIVE two-variant experiment with a primary metric; rows removed after."""
    created = []

    def _make(enabled=True, config=None, users=(400, 400), converted=(40, 60)):
        suffix = uuid.uuid4().hex[:8]
        experiment = make_experiment(
            name=f"Embedded sequential {suffix}",
            key=f"embedded-sequential-{suffix}",
            status=ExperimentStatus.ACTIVE,
            experiment_type=ExperimentType.A_B,
            start_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
            sequential_testing_enabled=enabled,
            sequential_testing_config=config or {"method": "msprt"},
        )
        created.append(experiment)
        variants = []
        for name, is_control in (("control", True), ("treatment", False)):
            variant = Variant(
                experiment_id=experiment.id,
                name=name,
                is_control=is_control,
                traffic_allocation=50,
            )
            db_session.add(variant)
            variants.append(variant)
        db_session.add(
            Metric(
                experiment_id=experiment.id,
                name="Purchase",
                event_name="purchase",
                metric_type=MetricType.CONVERSION,
                is_primary=True,
            )
        )
        db_session.flush()
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = []
        for variant, n_users, n_converted in zip(variants, users, converted):
            for i in range(n_users):
                user_id = f"{variant.name}-{suffix}-{i:05d}"
                rows.append(
                    Assignment(
                        experiment_id=experiment.id,
                        variant_id=variant.id,
                        user_id=user_id,
                    )
                )
                if i < n_converted:
                    rows.append(
                        Event(
                            event_type="purchase",
                            event_name="purchase",
                            user_id=user_id,
                            experiment_id=experiment.id,
                            variant_id=variant.id,
                            value=1.0,
                            created_at=now_iso,
                        )
                    )
        db_session.add_all(rows)
        db_session.commit()
        db_session.refresh(experiment)
        return experiment

    yield _make
    db_session.rollback()
    for experiment in created:
        for model in (AnalysisSnapshot, Event, Assignment):
            db_session.query(model).filter(model.experiment_id == experiment.id).delete(
                synchronize_session=False
            )
    db_session.commit()


def _get(client, path, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _sequential_rows(db_session, experiment_id):
    db_session.expire_all()
    return (
        db_session.query(AnalysisSnapshot)
        .filter(
            AnalysisSnapshot.experiment_id == experiment_id,
            AnalysisSnapshot.kind == "sequential",
        )
        .all()
    )


@pytest.mark.integration
@pytest.mark.requires_db
@pytest.mark.regression
@pytest.mark.parametrize("route", ROUTES)
def test_results_embed_the_sequential_analysis(
    admin_client, make_sequential_experiment, route
):
    """The embedded block is the one /sequential serves, field for field."""
    experiment = make_sequential_experiment()
    served = _get(admin_client, f"/api/v1/results/{experiment.id}/sequential")

    embedded = _get(admin_client, route.format(id=experiment.id), use_cache="false")[
        "sequential_testing"
    ]

    assert embedded == served
    # Real counts reached the analysis (400 + 400 users).
    assert embedded["confidence_sequence"]["sample_size"] == 800
    assert embedded["analysis_status"] == "beta"


@pytest.mark.integration
@pytest.mark.requires_db
@pytest.mark.parametrize("route", ROUTES)
def test_the_embedded_block_uses_the_stored_alpha(
    admin_client, make_sequential_experiment, route
):
    experiment = make_sequential_experiment(config={"method": "msprt", "alpha": 0.01})

    embedded = _get(admin_client, route.format(id=experiment.id), use_cache="false")[
        "sequential_testing"
    ]

    assert embedded["msprt_result"]["boundary"] == pytest.approx(100.0)


@pytest.mark.integration
@pytest.mark.requires_db
@pytest.mark.parametrize("route", ROUTES)
def test_sequential_testing_off_is_null_and_writes_no_sequential_row(
    admin_client, db_session, make_sequential_experiment, route
):
    experiment = make_sequential_experiment(enabled=False)

    body = _get(admin_client, route.format(id=experiment.id), use_cache="false")

    assert body["sequential_testing"] is None
    assert _sequential_rows(db_session, experiment.id) == []


@pytest.mark.integration
@pytest.mark.requires_db
@pytest.mark.regression
def test_a_failed_query_leaves_the_request_session_usable(
    db_session, make_sequential_experiment
):
    """The analysis runs in a savepoint: a failed statement inside it is rolled
    back to the savepoint, and the session can run the next statement."""
    experiment = make_sequential_experiment()

    def failing_query(_experiment, db):
        db.execute(text("SELECT 1/0"))

    with patch.object(results_endpoints, "_get_sequential_data", failing_query):
        block = results_endpoints._embedded_sequential(experiment, db_session)

    assert block is None
    assert db_session.execute(text("SELECT 1")).scalar() == 1
    db_session.rollback()


@pytest.mark.integration
@pytest.mark.requires_db
@pytest.mark.regression
def test_a_sequential_row_only_for_a_fresh_computation_under_stored_settings(
    admin_client, db_session, make_sequential_experiment
):
    """/results writes the sequential snapshot the dashboard no longer gets from
    /sequential, and only when the request uses the stored settings, like the
    frequentist and Bayesian rows.  The shared computation itself writes none."""
    experiment = make_sequential_experiment()

    # Other settings than the stored ones: no audit row of any sequential kind.
    _get(
        admin_client,
        f"/api/v1/results/{experiment.id}",
        use_cache="false",
        confidence_level=0.9,
    )
    assert _sequential_rows(db_session, experiment.id) == []

    # The stored settings: one row, carrying the embedded block.
    body = _get(admin_client, f"/api/v1/results/{experiment.id}", use_cache="false")
    rows = _sequential_rows(db_session, experiment.id)
    assert len(rows) == 1
    assert rows[0].payload == body["sequential_testing"]
