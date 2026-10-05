"""A segment that targeting uses cannot be archived or deactivated (#440).

``DELETE /segments/{id}`` and ``PUT /segments/{id}`` with a status other than
active answer 409 with a structured ``detail`` while the segment is referenced
by a flag that is not archived (a disabled flag included) or by an experiment
that is draft, active or paused (a paused one included). An archived flag or a
completed experiment does not block. The check fails closed: a row the text
prefilter finds but whose rules cannot be read counts, and a query error
answers 500 rather than "not used".
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.segment import Segment, SegmentKind
from backend.app.models.segment import SegmentStatus as ModelSegmentStatus
from backend.app.services import segment_membership

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

SEGMENTS = "/api/v1/segments"


def _rules(segment_id: str, op: str = "not_in_segment"):
    return {
        "groups": [
            {
                "conditions": [
                    {"attribute": "segment", "operator": op, "value": segment_id}
                ]
            }
        ]
    }


@pytest.fixture
def made(db_session, admin_user):
    rows = {"segments": [], "flags": [], "experiments": []}

    def segment() -> str:
        row = Segment(
            name=f"In use {uuid.uuid4().hex[:8]}",
            kind=SegmentKind.ID_LIST.value,
            status=ModelSegmentStatus.ACTIVE,
            owner_id=admin_user.id,
        )
        db_session.add(row)
        db_session.commit()
        rows["segments"].append(row.id)
        return str(row.id)

    def flag(rules, status) -> FeatureFlag:
        row = FeatureFlag(
            key=f"in-use-{uuid.uuid4().hex[:10]}",
            name="In use flag",
            status=status,
            owner_id=admin_user.id,
            rollout_percentage=0,
            targeting_rules=rules,
        )
        db_session.add(row)
        db_session.commit()
        rows["flags"].append(row.id)
        return row

    def experiment(rules, status) -> Experiment:
        suffix = uuid.uuid4().hex[:10]
        row = Experiment(
            name=f"In use {suffix}",
            key=f"in-use-{suffix}",
            status=status,
            owner_id=admin_user.id,
            targeting_rules=rules,
        )
        db_session.add(row)
        db_session.commit()
        rows["experiments"].append(row.id)
        return row

    yield type("Made", (), {"segment": segment, "flag": flag, "experiment": experiment})
    db_session.rollback()
    db_session.query(FeatureFlag).filter(FeatureFlag.id.in_(rows["flags"])).delete(
        False
    )
    db_session.query(Experiment).filter(Experiment.id.in_(rows["experiments"])).delete(
        False
    )
    db_session.query(Segment).filter(Segment.id.in_(rows["segments"])).delete(False)
    db_session.commit()


def _status(db_session, segment_id: str) -> ModelSegmentStatus:
    db_session.rollback()
    return db_session.query(Segment).filter(Segment.id == segment_id).one().status


def test_a_disabled_flag_and_a_paused_experiment_block(admin_client, made, db_session):
    segment_id = made.segment()
    flag = made.flag(_rules(segment_id), FeatureFlagStatus.INACTIVE)
    experiment = made.experiment(_rules(segment_id), ExperimentStatus.PAUSED)
    # These do not block: they can no longer evaluate.
    made.flag(_rules(segment_id), FeatureFlagStatus.ARCHIVED)
    made.experiment(_rules(segment_id), ExperimentStatus.COMPLETED)

    expected = {
        "detail": {
            "code": "segment_in_use",
            "message": (
                "This segment is used by 1 feature flag and 1 experiment. Remove it "
                "from their targeting rules first."
            ),
            "feature_flags": [{"id": str(flag.id), "key": flag.key, "name": flag.name}],
            "experiments": [
                {
                    "id": str(experiment.id),
                    "key": experiment.key,
                    "name": experiment.name,
                    "status": "paused",
                }
            ],
        }
    }
    archive = admin_client.delete(f"{SEGMENTS}/{segment_id}")
    assert archive.status_code == 409, archive.text
    assert archive.json() == expected
    for status in ("inactive", "archived"):
        deactivate = admin_client.put(
            f"{SEGMENTS}/{segment_id}", json={"status": status}
        )
        assert deactivate.status_code == 409, deactivate.text
        assert deactivate.json() == expected
    assert _status(db_session, segment_id) == ModelSegmentStatus.ACTIVE
    # A change that keeps it active is not refused.
    renamed = admin_client.put(
        f"{SEGMENTS}/{segment_id}", json={"name": "Renamed", "status": "active"}
    )
    assert renamed.status_code == 200, renamed.text


@pytest.mark.parametrize(
    "status", [ExperimentStatus.DRAFT, ExperimentStatus.ACTIVE, ExperimentStatus.PAUSED]
)
def test_each_live_experiment_status_blocks(admin_client, made, status):
    segment_id = made.segment()
    made.experiment(_rules(segment_id, "in_segment"), status)
    assert admin_client.delete(f"{SEGMENTS}/{segment_id}").status_code == 409


def test_an_unused_segment_archives(admin_client, made, db_session):
    segment_id = made.segment()
    other = made.segment()
    made.flag(_rules(other), FeatureFlagStatus.ACTIVE)
    # The id in a non-segment condition's value is not a reference.
    made.flag(
        {
            "groups": [
                {
                    "conditions": [
                        {
                            "attribute": "user_id",
                            "operator": "equals",
                            "value": segment_id,
                        }
                    ]
                }
            ]
        },
        FeatureFlagStatus.ACTIVE,
    )
    made.flag(_rules(segment_id), FeatureFlagStatus.ARCHIVED)
    made.experiment(_rules(segment_id), ExperimentStatus.ARCHIVED)
    response = admin_client.delete(f"{SEGMENTS}/{segment_id}")
    assert response.status_code == 204, response.text
    assert _status(db_session, segment_id) == ModelSegmentStatus.ARCHIVED


def test_unreadable_reference_counts(admin_client, made, db_session):
    """A row that mentions the segment but whose rules cannot be read counts."""
    segment_id = made.segment()
    flag = made.flag(
        {"groups": "not a list", "note": segment_id}, FeatureFlagStatus.INACTIVE
    )
    response = admin_client.delete(f"{SEGMENTS}/{segment_id}")
    assert response.status_code == 409, response.text
    assert [f["id"] for f in response.json()["detail"]["feature_flags"]] == [
        str(flag.id)
    ]
    assert _status(db_session, segment_id) == ModelSegmentStatus.ACTIVE


def test_query_error_is_500(admin_client, made, db_session, monkeypatch):
    segment_id = made.segment()

    def broken(db, sid):
        raise OperationalError("SELECT 1", {}, Exception("connection lost"))

    monkeypatch.setattr(
        "backend.app.services.audience_service.segment_references", broken
    )
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete(f"{SEGMENTS}/{segment_id}")
    assert response.status_code == 500, response.text
    assert "connection lost" not in response.text
    assert _status(db_session, segment_id) == ModelSegmentStatus.ACTIVE
    assert segment_membership.segment_references is not broken
