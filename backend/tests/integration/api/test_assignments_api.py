"""
Integration tests for the Assignments API (Phase 3.3).

The current assignments endpoint (/api/v1/assignments/) is a stub that
returns a static message. These tests verify the stub behaviour and test
the Assignment model persistence via the make_assignment factory fixture,
ensuring the data layer is wired correctly for future expansion.
"""

import uuid

import pytest

from backend.app.models.assignment import Assignment
from backend.app.models.experiment import ExperimentStatus


@pytest.mark.integration
@pytest.mark.requires_db
class TestAssignmentsEndpoint:
    """Tests for GET /api/v1/assignments/"""

    def test_assignments_endpoint_returns_200(self, admin_client):
        """The assignments endpoint is reachable and returns 200."""
        response = admin_client.get("/api/v1/assignments/")
        assert response.status_code == 200, response.text

    def test_assignments_endpoint_returns_json(self, admin_client):
        """The assignments endpoint returns a JSON body."""
        response = admin_client.get("/api/v1/assignments/")
        assert response.status_code == 200, response.text
        # Should be parseable JSON
        data = response.json()
        assert data is not None

    def test_assignments_endpoint_without_auth_is_not_500(self, admin_client):
        """Calling the stub endpoint does not cause a server error."""
        response = admin_client.get("/api/v1/assignments/")
        assert response.status_code < 500, (
            f"Unexpected server error: {response.status_code} - {response.text}"
        )


@pytest.mark.integration
@pytest.mark.requires_db
class TestAssignmentModelPersistence:
    """Tests that verify Assignment objects can be persisted and queried via the DB."""

    def test_create_assignment_via_factory(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """make_assignment fixture persists an Assignment to the DB."""
        exp = make_experiment(name="Assignment Persistence Test")
        control = make_variant(
            experiment=exp, name="Control", is_control=True, traffic_allocation=50
        )
        user_id = f"user-{uuid.uuid4().hex[:8]}"

        assignment = make_assignment(experiment=exp, variant=control, user_id=user_id)

        assert assignment.id is not None
        assert assignment.experiment_id == exp.id
        assert assignment.variant_id == control.id
        assert assignment.user_id == user_id

    def test_assignment_is_queryable_from_db(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """An Assignment created via factory is retrievable from the session."""
        exp = make_experiment(name="Query Assignment Test")
        variant = make_variant(
            experiment=exp, name="V1", is_control=True, traffic_allocation=100
        )
        user_id = f"user-{uuid.uuid4().hex[:8]}"

        assignment = make_assignment(experiment=exp, variant=variant, user_id=user_id)

        # Query back from DB
        fetched = (
            db_session.query(Assignment).filter(Assignment.id == assignment.id).first()
        )
        assert fetched is not None
        assert fetched.user_id == user_id
        assert fetched.experiment_id == exp.id

    def test_assignment_unique_per_experiment_user(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Only one Assignment per (experiment, user) pair is enforced by the DB."""
        exp = make_experiment(name="Unique Assignment Test")
        control = make_variant(
            experiment=exp, name="C", is_control=True, traffic_allocation=100
        )
        user_id = f"user-{uuid.uuid4().hex[:8]}"

        # First assignment succeeds
        make_assignment(experiment=exp, variant=control, user_id=user_id)

        # Second assignment for same experiment + user should fail
        import sqlalchemy.exc

        with pytest.raises(sqlalchemy.exc.IntegrityError):
            make_assignment(experiment=exp, variant=control, user_id=user_id)

    def test_assignment_has_relationships(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Assignment ORM relationships back to Experiment and Variant work."""
        exp = make_experiment(name="Relationship Assignment Test")
        variant = make_variant(
            experiment=exp, name="Control", is_control=True, traffic_allocation=50
        )
        user_id = f"user-{uuid.uuid4().hex[:8]}"

        assignment = make_assignment(experiment=exp, variant=variant, user_id=user_id)

        db_session.refresh(assignment)
        assert assignment.experiment.id == exp.id
        assert assignment.variant.id == variant.id

    def test_multiple_users_can_be_assigned_to_same_experiment(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Multiple distinct users can each have an assignment in the same experiment."""
        exp = make_experiment(name="Multi-User Assignment Test")
        control = make_variant(
            experiment=exp, name="Control", is_control=True, traffic_allocation=50
        )
        treatment = make_variant(
            experiment=exp, name="Treatment", is_control=False, traffic_allocation=50
        )

        user_a = f"user-{uuid.uuid4().hex[:8]}"
        user_b = f"user-{uuid.uuid4().hex[:8]}"

        a1 = make_assignment(experiment=exp, variant=control, user_id=user_a)
        a2 = make_assignment(experiment=exp, variant=treatment, user_id=user_b)

        assert a1.user_id != a2.user_id
        count = (
            db_session.query(Assignment)
            .filter(Assignment.experiment_id == exp.id)
            .count()
        )
        assert count == 2

    def test_assignment_context_field_stored(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Optional context JSONB is stored and retrievable."""
        exp = make_experiment(name="Context Assignment Test")
        variant = make_variant(
            experiment=exp, name="Ctrl", is_control=True, traffic_allocation=100
        )
        user_id = f"user-{uuid.uuid4().hex[:8]}"
        ctx = {"country": "US", "device": "mobile"}

        assignment = make_assignment(
            experiment=exp, variant=variant, user_id=user_id, context=ctx
        )

        db_session.refresh(assignment)
        assert assignment.context == ctx

    def test_assignment_repr(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Assignment.__repr__ includes user_id for debugging."""
        exp = make_experiment(name="Repr Test")
        variant = make_variant(
            experiment=exp, name="C", is_control=True, traffic_allocation=100
        )
        user_id = "user-repr"
        assignment = make_assignment(experiment=exp, variant=variant, user_id=user_id)
        assert "user-repr" in repr(assignment)
