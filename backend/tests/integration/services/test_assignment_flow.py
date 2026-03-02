"""
Integration tests for the assignment data flow (Phase 4).

Tests verify that Assignment records can be created, queried, and
cascade-deleted through the ORM relationships, forming the foundation
for future assignment service integration.
"""
import pytest
import uuid

from sqlalchemy.exc import IntegrityError

from backend.app.models.assignment import Assignment
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.experiment import Variant


@pytest.mark.integration
@pytest.mark.requires_db
class TestAssignmentFlow:
    """Tests for assignment creation, retrieval, and uniqueness."""

    def test_assign_user_to_variant(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """A user can be assigned to a variant in an experiment."""
        exp = make_experiment(name="Assign Flow Test")
        control = make_variant(
            experiment=exp, name="Control", is_control=True, traffic_allocation=50
        )
        user_id = f"flow-user-{uuid.uuid4().hex[:8]}"

        assignment = make_assignment(experiment=exp, variant=control, user_id=user_id)

        assert assignment.id is not None
        assert str(assignment.experiment_id) == str(exp.id)
        assert str(assignment.variant_id) == str(control.id)
        assert assignment.user_id == user_id

    def test_same_user_same_variant_consistent(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Once a user is assigned, querying gives back the same variant every time."""
        exp = make_experiment(name="Consistent Assignment Test")
        control = make_variant(
            experiment=exp, name="Control", is_control=True, traffic_allocation=50
        )
        user_id = f"consistent-user-{uuid.uuid4().hex[:8]}"

        make_assignment(experiment=exp, variant=control, user_id=user_id)

        # Query back multiple times — same record, same variant
        for _ in range(3):
            result = (
                db_session.query(Assignment)
                .filter(
                    Assignment.experiment_id == exp.id,
                    Assignment.user_id == user_id,
                )
                .first()
            )
            assert result is not None
            assert str(result.variant_id) == str(control.id)

    def test_duplicate_assignment_raises_integrity_error(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Assigning the same user to the same experiment twice violates uniqueness."""
        exp = make_experiment(name="Duplicate Assignment Test")
        control = make_variant(
            experiment=exp, name="C", is_control=True, traffic_allocation=100
        )
        user_id = f"dup-user-{uuid.uuid4().hex[:8]}"

        make_assignment(experiment=exp, variant=control, user_id=user_id)

        with pytest.raises(IntegrityError):
            make_assignment(experiment=exp, variant=control, user_id=user_id)

    def test_different_users_get_different_assignment_records(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Distinct users each get their own Assignment row in the DB."""
        exp = make_experiment(name="Multi User Assignment Flow")
        control = make_variant(
            experiment=exp, name="Control", is_control=True, traffic_allocation=50
        )
        treatment = make_variant(
            experiment=exp, name="Treatment", is_control=False, traffic_allocation=50
        )

        users = [f"flow-user-{uuid.uuid4().hex[:6]}" for _ in range(5)]
        for i, uid in enumerate(users):
            variant = control if i % 2 == 0 else treatment
            make_assignment(experiment=exp, variant=variant, user_id=uid)

        count = (
            db_session.query(Assignment)
            .filter(Assignment.experiment_id == exp.id)
            .count()
        )
        assert count == len(users)

    def test_assignment_respects_traffic_allocation(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Both variants receive assignments when both have 50% traffic allocation."""
        exp = make_experiment(name="Traffic Allocation Flow")
        control = make_variant(
            experiment=exp, name="Control", is_control=True, traffic_allocation=50
        )
        treatment = make_variant(
            experiment=exp, name="Treatment", is_control=False, traffic_allocation=50
        )

        # Assign half to control, half to treatment
        for i in range(10):
            uid = f"alloc-user-{uuid.uuid4().hex[:6]}"
            variant = control if i < 5 else treatment
            make_assignment(experiment=exp, variant=variant, user_id=uid)

        control_count = (
            db_session.query(Assignment)
            .filter(
                Assignment.experiment_id == exp.id,
                Assignment.variant_id == control.id,
            )
            .count()
        )
        treatment_count = (
            db_session.query(Assignment)
            .filter(
                Assignment.experiment_id == exp.id,
                Assignment.variant_id == treatment.id,
            )
            .count()
        )
        assert control_count == 5
        assert treatment_count == 5

    def test_user_can_be_assigned_to_different_experiments(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """The same user ID can have assignments in multiple distinct experiments."""
        exp_a = make_experiment(name="Exp A Multi Exp Flow")
        exp_b = make_experiment(name="Exp B Multi Exp Flow")

        control_a = make_variant(
            experiment=exp_a, name="C", is_control=True, traffic_allocation=100
        )
        control_b = make_variant(
            experiment=exp_b, name="C", is_control=True, traffic_allocation=100
        )

        shared_user = "shared-user-across-experiments"
        a1 = make_assignment(experiment=exp_a, variant=control_a, user_id=shared_user)
        a2 = make_assignment(experiment=exp_b, variant=control_b, user_id=shared_user)

        # Both assignments exist, with different experiment IDs
        assert str(a1.experiment_id) != str(a2.experiment_id)
        assert a1.user_id == a2.user_id == shared_user

    def test_assignments_cascade_delete_when_experiment_deleted(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Deleting an Experiment removes its associated Assignment records via cascade."""
        exp = make_experiment(name="Cascade Delete Flow")
        control = make_variant(
            experiment=exp, name="Control", is_control=True, traffic_allocation=100
        )
        user_ids = [f"cascade-user-{i}" for i in range(3)]
        for uid in user_ids:
            make_assignment(experiment=exp, variant=control, user_id=uid)

        exp_id = exp.id
        # Confirm assignments exist
        assert (
            db_session.query(Assignment)
            .filter(Assignment.experiment_id == exp_id)
            .count()
        ) == 3

        # Delete the experiment
        db_session.delete(exp)
        db_session.commit()

        # Assignments should be gone due to CASCADE
        remaining = (
            db_session.query(Assignment)
            .filter(Assignment.experiment_id == exp_id)
            .count()
        )
        assert remaining == 0

    def test_assignment_stores_and_retrieves_context(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Context JSONB is correctly stored and retrieved for an assignment."""
        exp = make_experiment(name="Context Flow Test")
        control = make_variant(
            experiment=exp, name="Control", is_control=True, traffic_allocation=100
        )
        user_id = f"ctx-user-{uuid.uuid4().hex[:8]}"
        context = {"platform": "ios", "version": "2.1.0", "country": "CA"}

        assignment = make_assignment(
            experiment=exp, variant=control, user_id=user_id, context=context
        )
        db_session.refresh(assignment)

        assert assignment.context is not None
        assert assignment.context["platform"] == "ios"
        assert assignment.context["country"] == "CA"

    def test_query_all_assignments_for_a_user(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Can query all assignments for a given user_id across all experiments."""
        exp1 = make_experiment(name="User Query Exp 1")
        exp2 = make_experiment(name="User Query Exp 2")
        c1 = make_variant(experiment=exp1, name="C", is_control=True, traffic_allocation=100)
        c2 = make_variant(experiment=exp2, name="C", is_control=True, traffic_allocation=100)

        target_user = f"target-user-{uuid.uuid4().hex[:8]}"
        make_assignment(experiment=exp1, variant=c1, user_id=target_user)
        make_assignment(experiment=exp2, variant=c2, user_id=target_user)

        # Another user shouldn't pollute
        other_user = f"other-user-{uuid.uuid4().hex[:8]}"
        make_assignment(experiment=exp1, variant=c1, user_id=other_user)

        user_assignments = (
            db_session.query(Assignment)
            .filter(Assignment.user_id == target_user)
            .all()
        )
        assert len(user_assignments) == 2
        exp_ids = {str(a.experiment_id) for a in user_assignments}
        assert str(exp1.id) in exp_ids
        assert str(exp2.id) in exp_ids
