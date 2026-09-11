"""
Conversion events must be counted the same way whichever producer wrote them.

``EventService.track_conversion`` stores ``event_type="conversion"``, while the
public tracking API and the SDKs store the event's own name in ``event_type``
(``event_type="purchase", event_name="purchase"``).  The results engine used to
require ``event_type == "conversion"``, so every conversion sent through the
SDK-facing API was silently ignored and dashboards showed 0% everywhere.
"""

import uuid
from datetime import datetime, timezone

import pytest

from backend.app.core.bandit_scheduler import BanditScheduler
from backend.app.models.assignment import Assignment
from backend.app.models.event import Event
from backend.app.models.experiment import (
    ExperimentStatus,
    Metric,
    MetricType,
    Variant,
)
from backend.app.services.analysis_service import AnalysisService
from backend.app.services.event_matching import (
    EXPOSURE_EVENT_TYPES,
    conversion_event_filter,
)


@pytest.fixture
def seeded_experiment(db_session, make_experiment):
    """
    ACTIVE experiment, 4 users per variant.

    control:  2 conversions — one SDK-shaped, one EventService-shaped
    treatment: 3 conversions — two SDK-shaped, one EventService-shaped
    Every user also has an exposure row; one control user has an unrelated
    ``page_view`` event that must not count.
    """
    suffix = uuid.uuid4().hex[:8]
    experiment = make_experiment(
        name=f"Event matching {suffix}",
        key=f"event-matching-{suffix}",
        status=ExperimentStatus.ACTIVE,
        start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    control = Variant(
        experiment_id=experiment.id,
        name="control",
        is_control=True,
        traffic_allocation=50,
    )
    treatment = Variant(
        experiment_id=experiment.id,
        name="treatment",
        is_control=False,
        traffic_allocation=50,
    )
    db_session.add_all([control, treatment])
    db_session.flush()
    db_session.add(
        Metric(
            experiment_id=experiment.id,
            name="Purchase",
            event_name="purchase",
            metric_type=MetricType.CONVERSION,
            is_primary=True,
        )
    )

    now = datetime.now(timezone.utc).isoformat()

    def add_user(variant, index, conversion_shape):
        user_id = f"em-{suffix}-{variant.name}-{index}"
        db_session.add(
            Assignment(
                experiment_id=experiment.id, variant_id=variant.id, user_id=user_id
            )
        )
        db_session.add(
            Event(
                event_type="exposure",
                event_name="variant_exposure",
                user_id=user_id,
                experiment_id=experiment.id,
                variant_id=variant.id,
                created_at=now,
            )
        )
        if conversion_shape == "sdk":
            event_type = "purchase"  # tracking API: event_type == event_name
        elif conversion_shape == "service":
            event_type = "conversion"  # EventService.track_conversion
        else:
            return
        db_session.add(
            Event(
                event_type=event_type,
                event_name="purchase",
                user_id=user_id,
                experiment_id=experiment.id,
                variant_id=variant.id,
                value=1.0,
                created_at=now,
            )
        )

    add_user(control, 0, "sdk")
    add_user(control, 1, "service")
    add_user(control, 2, None)
    add_user(control, 3, None)
    add_user(treatment, 0, "sdk")
    add_user(treatment, 1, "sdk")
    add_user(treatment, 2, "service")
    add_user(treatment, 3, None)

    # Noise: a non-conversion event with a different name on a control user
    db_session.add(
        Event(
            event_type="page_view",
            event_name="page_view",
            user_id=f"em-{suffix}-control-2",
            experiment_id=experiment.id,
            variant_id=control.id,
            created_at=now,
        )
    )
    db_session.commit()
    db_session.refresh(experiment)

    yield experiment, control, treatment

    db_session.rollback()
    db_session.query(Event).filter(Event.experiment_id == experiment.id).delete()
    db_session.query(Assignment).filter(
        Assignment.experiment_id == experiment.id
    ).delete()
    db_session.commit()


class TestConversionEventFilter:
    def test_matches_both_producer_shapes_and_excludes_exposures(
        self, db_session, seeded_experiment
    ):
        experiment, control, treatment = seeded_experiment
        base = db_session.query(Event).filter(Event.experiment_id == experiment.id)

        assert base.filter(conversion_event_filter("purchase")).count() == 5
        assert (
            base.filter(
                conversion_event_filter("purchase"), Event.variant_id == control.id
            ).count()
            == 2
        )
        assert (
            base.filter(
                conversion_event_filter("purchase"), Event.variant_id == treatment.id
            ).count()
            == 3
        )
        assert base.filter(Event.event_type.in_(EXPOSURE_EVENT_TYPES)).count() == 8


class TestResultsEngineCountsSdkEvents:
    def test_get_experiment_results_uses_event_name(
        self, db_session, seeded_experiment
    ):
        experiment, control, treatment = seeded_experiment

        results = AnalysisService(db_session).get_experiment_results(str(experiment.id))

        metric = results["metrics"][0]
        assert metric["metric_name"] == "Purchase"
        by_variant = {v["variant_name"]: v for v in metric["variants"]}
        assert by_variant["control"]["sample_size"] == 4
        assert by_variant["treatment"]["sample_size"] == 4
        assert by_variant["control"]["conversions"] == 2
        assert by_variant["treatment"]["conversions"] == 3
        assert by_variant["control"]["mean"] == pytest.approx(0.5)
        assert by_variant["treatment"]["mean"] == pytest.approx(0.75)
        assert results["summary"]["total_conversions"] == 5

    def test_results_endpoint_reports_the_same_rates(
        self, admin_client, seeded_experiment
    ):
        experiment, _, _ = seeded_experiment

        resp = admin_client.get(f"/api/v1/results/{experiment.id}?use_cache=false")
        assert resp.status_code == 200, resp.text
        metric = resp.json()["metrics"][0]
        means = {v["variant_name"]: v["mean"] for v in metric["variants"]}
        assert means == {
            "control": pytest.approx(0.5),
            "treatment": pytest.approx(0.75),
        }
        conversions = {v["variant_name"]: v["conversions"] for v in metric["variants"]}
        assert conversions == {"control": 2, "treatment": 3}


class TestBanditSchedulerCountsSdkEvents:
    def test_postgres_fallback_counts_sdk_shaped_conversions(
        self, db_session, seeded_experiment
    ):
        experiment, control, treatment = seeded_experiment
        scheduler = BanditScheduler(db=db_session)

        stats = scheduler._stats_from_postgres(
            experiment.id, [str(control.id), str(treatment.id)], experiment
        )

        assert stats[str(control.id)].pulls == 4
        assert stats[str(control.id)].successes == 2
        assert stats[str(treatment.id)].pulls == 4
        assert stats[str(treatment.id)].successes == 3
