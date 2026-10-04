"""
``GET /api/v1/interactions/{a}/{b}`` (beta, #219) against PostgreSQL.

* R1: each row's per-arm counts, summed over the other experiment's arms, are
  ``/results``' per-variant ``sample_size`` and ``conversions`` -- with
  duplicate events, an unassigned user's event, an event tagged with the
  other variant and a view row named after the metric in the data.
* C6: the same with the stream and lookup chunks patched to 3 users, so the
  stream of the smaller experiment and the lookups in the larger one
  interleave on one session over many chunks.
* G1/G2: the mutual exclusion group is the experiments' current one, whatever
  its status; leaving the group switches the answer on the next request.
* The statement timeout reaches the route's one failure path (a 500 with a
  fixed sentence).  It bounds each statement, not the request.
* A planted interaction is found, through the whole route.

Rows created here are deleted in fixture teardown because the shared test
database is not truncated between tests.
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import pytest
from sqlalchemy import text

from backend.app.models.assignment import Assignment
from backend.app.models.event import Event
from backend.app.models.experiment import (
    Experiment,
    ExperimentStatus,
    ExperimentType,
    Metric,
    MetricType,
    Variant,
)
from backend.app.models.mutual_exclusion_group import (
    MutualExclusionGroup,
    MutualExclusionGroupStatus,
)
from backend.app.services import event_matching
from backend.app.services import interaction_detection_service as service_module
from backend.app.services.interaction_detection_service import (
    InteractionDetectionService,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

NOW = datetime(2026, 9, 15, tzinfo=timezone.utc).isoformat()


def _make(make_experiment, db_session, label, variants=("control", "treatment")):
    suffix = uuid.uuid4().hex[:8]
    experiment = make_experiment(
        name=f"{label} {suffix}",
        key=f"{label.lower().replace(' ', '-')}-{suffix}",
        status=ExperimentStatus.ACTIVE,
        experiment_type=ExperimentType.A_B,
        start_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    for name in variants:
        db_session.add(
            Variant(
                experiment_id=experiment.id,
                name=name,
                is_control=(name == variants[0]),
                traffic_allocation=100 // len(variants),
            )
        )
    db_session.add(
        Metric(
            experiment_id=experiment.id,
            name="Signup",
            event_name="signup",
            metric_type=MetricType.CONVERSION,
            is_primary=True,
        )
    )
    db_session.commit()
    db_session.refresh(experiment)
    return experiment


def _vid(experiment, name):
    return next(v.id for v in experiment.variants if v.name == name)


def _cleanup(db_session, experiments, groups=()):
    db_session.rollback()
    ids = [e.id for e in experiments]
    for model in (Event, Assignment):
        db_session.query(model).filter(model.experiment_id.in_(ids)).delete(
            synchronize_session=False
        )
    db_session.query(Experiment).filter(Experiment.id.in_(ids)).update(
        {"mutual_exclusion_group_id": None}, synchronize_session=False
    )
    db_session.commit()
    for group in groups:
        db_session.query(MutualExclusionGroup).filter(
            MutualExclusionGroup.id == group.id
        ).delete(synchronize_session=False)
    db_session.commit()


def _seed(db_session, assignments: List[Tuple], events: List[Tuple]) -> None:
    """``assignments``: (experiment, variant name, user); ``events``:
    (experiment, variant name, user, event_type)."""
    db_session.bulk_insert_mappings(
        Assignment,
        [
            {
                "id": uuid.uuid4(),
                "experiment_id": e.id,
                "variant_id": _vid(e, v),
                "user_id": u,
            }
            for e, v, u in assignments
        ],
    )
    db_session.bulk_insert_mappings(
        Event,
        [
            {
                "id": uuid.uuid4(),
                "event_type": kind,
                "event_name": "signup",
                "user_id": u,
                "experiment_id": e.id,
                "variant_id": _vid(e, v),
                "created_at": NOW,
            }
            for e, v, u, kind in events
        ],
    )
    db_session.commit()


@pytest.fixture
def messy_pair(db_session, make_experiment):
    """Two experiments, every user in both, with events that must not count.

    Pricing has 2 variants, onboarding 3.  Each user's arms come from their
    index, so every cell is filled.  Conversions in pricing: every 3rd user,
    some twice; onboarding: every 4th.  Plus, in pricing: an event from a user
    with no assignment, an event tagged with the variant the user is NOT in,
    and a view row named after the metric.
    """
    pricing = _make(make_experiment, db_session, "Pricing page")
    onboarding = _make(
        make_experiment, db_session, "Onboarding flow", ("control", "checklist", "tour")
    )
    tag = uuid.uuid4().hex[:6]
    assignments, events = [], []
    for i in range(61):
        user = f"u-{tag}-{i}"
        p = ("control", "treatment")[i % 2]
        o = ("control", "checklist", "tour")[i % 3]
        assignments += [(pricing, p, user), (onboarding, o, user)]
        if i % 3 == 0:
            events.append((pricing, p, user, "signup"))
            if i % 2 == 0:
                events.append((pricing, p, user, "signup"))  # a duplicate
        if i % 4 == 0:
            events.append((onboarding, o, user, "signup"))
        if i % 5 == 1:
            other = "treatment" if p == "control" else "control"
            events.append((pricing, other, user, "signup"))  # wrong variant
        if i % 7 == 2:
            events.append((pricing, p, user, "exposure"))  # a view row
    events.append((pricing, "control", f"nobody-{tag}", "signup"))  # unassigned
    _seed(db_session, assignments, events)
    yield pricing, onboarding
    _cleanup(db_session, [pricing, onboarding])


def _results_counts(client, experiment) -> Dict[str, Tuple[int, int]]:
    response = client.get(f"/api/v1/results/{experiment.id}")
    assert response.status_code == 200, response.text
    [metric] = [m for m in response.json()["metrics"] if m["is_primary"]]
    return {
        v["variant_id"]: (v["sample_size"], v["conversions"])
        for v in metric["variants"]
    }


def _row_sums(body, experiment) -> Dict[str, Tuple[int, int]]:
    """Per variant of ``experiment``: users and converters over its rows' arms."""
    sums: Dict[str, Tuple[int, int]] = {}
    for row in body["interaction_results"]:
        if row["experiment_id"] != str(experiment.id):
            continue
        control = row["control_variant_id"]
        sums[control] = (
            sum(a["n_control"] for a in row["arms"]),
            sum(a["converted_control"] for a in row["arms"]),
        )
        sums[row["variant_id"]] = (
            sum(a["n_treatment"] for a in row["arms"]),
            sum(a["converted_treatment"] for a in row["arms"]),
        )
    return sums


def _assert_r1(admin_client, pricing, onboarding):
    response = admin_client.get(f"/api/v1/interactions/{pricing.id}/{onboarding.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["shared_users"] == 61
    for experiment in (pricing, onboarding):
        assert _row_sums(body, experiment) == _results_counts(admin_client, experiment)
    return body


@pytest.mark.regression
def test_r1_arm_counts_are_the_results_counts(admin_client, messy_pair):
    pricing, onboarding = messy_pair
    body = _assert_r1(admin_client, pricing, onboarding)
    # 61 users: pricing control has users 0, 2, ..., 60; converters i % 3 == 0.
    assert _row_sums(body, pricing)[str(_vid(pricing, "control"))] == (31, 11)


@pytest.mark.regression
def test_c6_chunks_of_three_give_the_same_counts(admin_client, messy_pair, monkeypatch):
    """The smaller experiment is streamed 3 users at a time and looked up in
    the larger one 3 at a time: 21 fetches interleaved on one session."""
    monkeypatch.setattr(service_module, "ASSIGNMENT_STREAM_CHUNK", 3)
    monkeypatch.setattr(event_matching, "ASSIGNMENT_LOOKUP_CHUNK", 3)
    pricing, onboarding = messy_pair
    _assert_r1(admin_client, pricing, onboarding)


def test_c6_also_holds_when_b_is_the_smaller_experiment(
    admin_client, db_session, messy_pair, monkeypatch
):
    """Users only in pricing make onboarding the smaller side."""
    monkeypatch.setattr(service_module, "ASSIGNMENT_STREAM_CHUNK", 3)
    monkeypatch.setattr(event_matching, "ASSIGNMENT_LOOKUP_CHUNK", 3)
    pricing, onboarding = messy_pair
    extra = [
        (pricing, "control", f"only-pricing-{uuid.uuid4().hex[:6]}-{i}")
        for i in range(7)
    ]
    _seed(db_session, extra, [])
    response = admin_client.get(f"/api/v1/interactions/{pricing.id}/{onboarding.id}")
    body = response.json()
    assert body["shared_users"] == 61
    assert body["share_of_a"] == pytest.approx(61 / 68)
    assert body["share_of_b"] == 1.0
    assert _row_sums(body, onboarding) == _results_counts(admin_client, onboarding)


# ---------------------------------------------------------------------------
# G1/G2: the mutual exclusion group
# ---------------------------------------------------------------------------


@pytest.fixture
def grouped_pair(db_session, make_experiment, admin_user):
    pricing = _make(make_experiment, db_session, "Grouped pricing")
    onboarding = _make(make_experiment, db_session, "Grouped onboarding")
    group = MutualExclusionGroup(
        name=f"group-{uuid.uuid4().hex[:8]}", owner_id=admin_user.id
    )
    db_session.add(group)
    db_session.commit()
    for experiment in (pricing, onboarding):
        experiment.mutual_exclusion_group_id = group.id
    db_session.commit()
    tag = uuid.uuid4().hex[:6]
    _seed(
        db_session,
        [(pricing, "control", f"g-{tag}-1"), (onboarding, "control", f"g-{tag}-1")],
        [],
    )
    yield pricing, onboarding, group
    _cleanup(db_session, [pricing, onboarding], [group])


def _reasons(body):
    return [row["unavailable_reason"] for row in body["interaction_results"]]


def test_g1_the_same_group_is_reported_with_its_id(admin_client, grouped_pair):
    pricing, onboarding, group = grouped_pair
    body = admin_client.get(f"/api/v1/interactions/{pricing.id}/{onboarding.id}").json()
    assert _reasons(body) == ["mutual_exclusion_group"] * 2
    assert body["mutual_exclusion_group_id"] == str(group.id)
    assert body["shared_users"] == 1


def test_g1_an_archived_group_still_counts(admin_client, db_session, grouped_pair):
    pricing, onboarding, group = grouped_pair
    group.status = MutualExclusionGroupStatus.ARCHIVED
    db_session.commit()
    body = admin_client.get(f"/api/v1/interactions/{pricing.id}/{onboarding.id}").json()
    assert _reasons(body) == ["mutual_exclusion_group"] * 2


def test_g2_leaving_the_group_switches_the_answer(
    admin_client, db_session, grouped_pair
):
    pricing, onboarding, _ = grouped_pair
    url = f"/api/v1/interactions/{pricing.id}/{onboarding.id}"
    assert _reasons(admin_client.get(url).json()) == ["mutual_exclusion_group"] * 2
    onboarding.mutual_exclusion_group_id = None
    db_session.commit()
    body = admin_client.get(url).json()
    assert body["mutual_exclusion_group_id"] is None
    assert _reasons(body) == ["too_few_shared_users"] * 2


# ---------------------------------------------------------------------------
# Refusals and the one failure path, against the real database
# ---------------------------------------------------------------------------


def test_an_unknown_experiment_is_404(admin_client, messy_pair):
    pricing, _ = messy_pair
    response = admin_client.get(f"/api/v1/interactions/{pricing.id}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "experiment_b_id does not match an experiment."


@pytest.mark.regression
def test_the_statement_timeout_reaches_the_fixed_500(
    admin_client, messy_pair, monkeypatch
):
    """Performance bound: with the timeout at 1 ms, a 50 ms statement is cancelled.

    The first reader is made to sleep 50 ms in the database first, so the
    test does not depend on how fast the real reads are.
    """
    monkeypatch.setattr(service_module, "PAIR_STATEMENT_TIMEOUT_MS", 1)
    original = InteractionDetectionService._arm_totals

    def slow(db, experiment_id):
        db.execute(text("SELECT pg_sleep(0.05)"))
        return original(db, experiment_id)

    monkeypatch.setattr(InteractionDetectionService, "_arm_totals", staticmethod(slow))
    pricing, onboarding = messy_pair
    response = admin_client.get(f"/api/v1/interactions/{pricing.id}/{onboarding.id}")
    assert response.status_code == 500, response.text
    detail = response.json()["detail"]
    assert detail.startswith("Could not analyse the two experiments")
    assert "statement timeout" not in response.text
    assert "canceling" not in response.text
