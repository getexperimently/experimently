"""
DB-backed tests for ExperimentService enum handling.

Two bugs live here, both invisible to mock-based unit tests:

1. ``Experiment.status`` is a SQLAlchemy ``Enum(ExperimentStatus)``, which
   stores enum *names* (``DRAFT``).  The dashboard sends the enum *value*
   (``status_filter=draft``); SQLAlchemy passes that raw string straight
   through, so the filter matched nothing.
2. ``ExperimentType["mv".upper()]`` is a lookup by *name* and raises KeyError
   for ``MULTIVARIATE`` (whose value is ``"mv"``), so multivariate experiments
   were silently downgraded to A/B.
"""

import uuid

import pytest

from backend.app.models.experiment import Experiment, ExperimentStatus, ExperimentType
from backend.app.schemas.experiment import ExperimentCreate
from backend.app.services.experiment_service import ExperimentService


def _marker() -> str:
    """A search term unique to one test (rows persist across tests)."""
    return f"enumfilter{uuid.uuid4().hex[:10]}"


def _create_payload(name: str, experiment_type: str = "a_b") -> dict:
    return {
        "name": name,
        "description": "Enum filter integration test",
        "hypothesis": "Enum round-tripping works",
        "experiment_type": experiment_type,
        "variants": [
            {"name": "Control", "is_control": True, "traffic_allocation": 50},
            {"name": "Treatment", "is_control": False, "traffic_allocation": 50},
        ],
        "metrics": [
            {
                "name": "Conversion Rate",
                "event_name": "purchase",
                "metric_type": "conversion",
                "is_primary": True,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Status filter
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStatusFilterSpellings:
    """Every spelling of a status filter must find the same rows."""

    @pytest.fixture
    def seeded(self, db_session, make_experiment, admin_user):
        """One DRAFT and one ACTIVE experiment sharing a unique name marker."""
        marker = _marker()
        draft = make_experiment(name=f"Draft {marker}", status=ExperimentStatus.DRAFT)
        active = make_experiment(
            name=f"Active {marker}", status=ExperimentStatus.ACTIVE
        )
        return marker, draft, active, admin_user

    @pytest.mark.parametrize(
        "spelling",
        ["draft", "DRAFT", "Draft", ExperimentStatus.DRAFT],
        ids=["value", "name", "mixed-case", "enum-member"],
    )
    def test_status_filter_matches_draft_rows(self, db_session, seeded, spelling):
        marker, draft, active, owner = seeded
        service = ExperimentService(db_session)

        by_owner = service.get_experiments_by_owner(owner_id=owner.id, status=spelling)
        ids = {row["id"] for row in by_owner}
        assert str(draft.id) in ids
        assert str(active.id) not in ids

        listed = service.get_experiments(status=spelling, search=marker)
        assert [row["id"] for row in listed] == [str(draft.id)]
        assert service.count_experiments(status=spelling, search=marker) == 1

        searched = service.search_experiments(search_term=marker, status=spelling)
        assert [row["id"] for row in searched] == [str(draft.id)]
        assert service.count_search_results(search_term=marker, status=spelling) == 1

    def test_owner_scoped_count_matches_the_listing(self, db_session, seeded):
        marker, draft, active, owner = seeded
        service = ExperimentService(db_session)

        listed = service.get_experiments_by_owner(owner_id=owner.id, status="draft")
        assert service.count_experiments_by_owner(
            owner_id=owner.id, status="draft"
        ) == len(listed)

    @pytest.mark.parametrize("garbage", ["not-a-status", "drafts", "123", "  "])
    def test_unknown_status_returns_empty_rather_than_raising(
        self, db_session, seeded, garbage
    ):
        """Unknown filter values are answered with an empty result, not a 500."""
        marker, draft, active, owner = seeded
        service = ExperimentService(db_session)

        assert service.get_experiments(status=garbage) == []
        assert service.count_experiments(status=garbage) == 0
        assert service.get_experiments_by_owner(owner_id=owner.id, status=garbage) == []
        assert (
            service.count_experiments_by_owner(owner_id=owner.id, status=garbage) == 0
        )
        assert service.search_experiments(search_term=marker, status=garbage) == []
        assert service.count_search_results(search_term=marker, status=garbage) == 0

    def test_no_status_filter_still_returns_every_status(self, db_session, seeded):
        marker, draft, active, owner = seeded
        service = ExperimentService(db_session)

        ids = {row["id"] for row in service.get_experiments(search=marker)}
        assert {str(draft.id), str(active.id)} <= ids


@pytest.mark.integration
class TestStatusFilterThroughTheApi:
    """GET /api/v1/experiments/?status_filter=... — what the dashboard sends."""

    def _create(self, client, marker: str) -> str:
        response = client.post(
            "/api/v1/experiments/", json=_create_payload(f"API {marker}")
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    @pytest.mark.parametrize("spelling", ["draft", "DRAFT"])
    def test_lower_and_upper_case_status_filter_find_the_experiment(
        self, admin_client, spelling
    ):
        marker = _marker()
        experiment_id = self._create(admin_client, marker)

        response = admin_client.get(
            "/api/v1/experiments/", params={"status_filter": spelling, "search": marker}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [item["id"] for item in body["items"]] == [experiment_id]
        assert body["total"] == 1

    def test_unknown_status_filter_returns_an_empty_page_not_a_500(self, admin_client):
        marker = _marker()
        self._create(admin_client, marker)

        response = admin_client.get(
            "/api/v1/experiments/",
            params={"status_filter": "nonsense", "search": marker},
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
        assert response.json()["total"] == 0


# ---------------------------------------------------------------------------
# Experiment type
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExperimentTypeResolution:
    """create_experiment must store the type the caller asked for."""

    @pytest.mark.parametrize("member", list(ExperimentType), ids=lambda m: m.name)
    def test_type_resolved_from_its_value(self, db_session, admin_user, member):
        """``"mv"`` must become MULTIVARIATE, not a silent A/B downgrade."""
        service = ExperimentService(db_session)
        payload = _create_payload(
            f"By value {member.value} {uuid.uuid4().hex[:8]}", member.value
        )

        created = service.create_experiment(
            obj_in=ExperimentCreate(**payload), user_id=admin_user.id
        )

        row = (
            db_session.query(Experiment).filter(Experiment.id == created["id"]).first()
        )
        assert row.experiment_type is member

    @pytest.mark.parametrize("member", list(ExperimentType), ids=lambda m: m.name)
    def test_type_resolved_from_its_name(self, db_session, admin_user, member):
        """The enum *name* (what the DB stores) is accepted too."""
        service = ExperimentService(db_session)
        payload = _create_payload(f"By name {member.name} {uuid.uuid4().hex[:8]}")
        payload["experiment_type"] = member.name

        created = service.create_experiment(obj_in=payload, user_id=admin_user.id)

        row = (
            db_session.query(Experiment).filter(Experiment.id == created["id"]).first()
        )
        assert row.experiment_type is member

    def test_unknown_type_falls_back_to_ab_with_a_warning(
        self, db_session, admin_user, caplog
    ):
        service = ExperimentService(db_session)
        payload = _create_payload(f"Bad type {uuid.uuid4().hex[:8]}")
        payload["experiment_type"] = "teleportation"

        with caplog.at_level("WARNING"):
            created = service.create_experiment(obj_in=payload, user_id=admin_user.id)

        row = (
            db_session.query(Experiment).filter(Experiment.id == created["id"]).first()
        )
        assert row.experiment_type is ExperimentType.A_B
        assert any("teleportation" in record.getMessage() for record in caplog.records)

    def test_update_resolves_the_type_by_value(self, db_session, admin_user):
        service = ExperimentService(db_session)
        payload = _create_payload(f"Update type {uuid.uuid4().hex[:8]}")
        created = service.create_experiment(
            obj_in=ExperimentCreate(**payload), user_id=admin_user.id
        )
        row = (
            db_session.query(Experiment).filter(Experiment.id == created["id"]).first()
        )

        service.update_experiment(row, {"experiment_type": "mv"})

        db_session.refresh(row)
        assert row.experiment_type is ExperimentType.MULTIVARIATE
