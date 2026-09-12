"""
Integration tests for ORM relationships between models.

Tests that verify the SQLAlchemy relationships between Experiment, Variant,
Metric, Assignment, and FeatureFlag models work correctly end-to-end.
"""

import pytest

from backend.app.models.experiment import (
    Experiment,
    ExperimentStatus,
    ExperimentType,
    Metric,
    MetricType,
    Variant,
)

# MetricType.CONVERSION string value — used when creating Metric objects directly
METRIC_TYPE_CONVERSION = MetricType.CONVERSION
from backend.app.models.assignment import Assignment
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.user import User, UserRole


@pytest.mark.integration
@pytest.mark.requires_db
class TestExperimentRelationships:
    """Test ORM relationships on the Experiment model."""

    def test_experiment_has_variants(self, db_session, make_experiment, make_variant):
        """Experiment.variants relationship returns all associated variants."""
        exp = make_experiment(name="Relationship Test")
        v1 = make_variant(experiment=exp, name="Control", is_control=True)
        v2 = make_variant(experiment=exp, name="Treatment", is_control=False)

        db_session.refresh(exp)
        assert len(exp.variants) == 2
        names = {v.name for v in exp.variants}
        assert "Control" in names
        assert "Treatment" in names

    def test_experiment_has_control_variant(
        self, db_session, make_experiment, make_variant
    ):
        """Can identify the control variant via the relationship."""
        exp = make_experiment(name="Control Check")
        make_variant(experiment=exp, name="Control", is_control=True)
        make_variant(experiment=exp, name="Treatment", is_control=False)

        db_session.refresh(exp)
        control = next(v for v in exp.variants if v.is_control)
        assert control.name == "Control"

    def test_variant_belongs_to_experiment(
        self, db_session, make_experiment, make_variant
    ):
        """Variant.experiment_id is correctly set to the parent experiment."""
        exp = make_experiment(name="Parent Experiment")
        variant = make_variant(experiment=exp, name="V1")

        db_session.refresh(variant)
        assert variant.experiment_id == exp.id

    def test_variant_back_reference_to_experiment(
        self, db_session, make_experiment, make_variant
    ):
        """Variant.experiment back-reference returns the correct Experiment object."""
        exp = make_experiment(name="Back-ref Experiment")
        variant = make_variant(experiment=exp, name="V1")

        db_session.refresh(variant)
        assert variant.experiment is not None
        assert variant.experiment.id == exp.id
        assert variant.experiment.name == "Back-ref Experiment"

    def test_experiment_has_metrics(self, db_session, make_experiment, make_metric):
        """Experiment.metric_definitions relationship includes all associated metrics."""
        exp = make_experiment()
        make_metric(
            experiment=exp, name="Conversion Rate", metric_type=MetricType.CONVERSION
        )
        make_metric(
            experiment=exp,
            name="Revenue",
            event_name="purchase_value",
            metric_type=MetricType.REVENUE,
        )

        db_session.refresh(exp)
        assert len(exp.metric_definitions) == 2
        metric_names = {m.name for m in exp.metric_definitions}
        assert "Conversion Rate" in metric_names
        assert "Revenue" in metric_names

    def test_metric_belongs_to_experiment(
        self, db_session, make_experiment, make_metric
    ):
        """Metric.experiment_id is correctly set to the parent experiment."""
        exp = make_experiment(name="Metric Parent")
        metric = make_metric(
            experiment=exp,
            name="CTR",
            event_name="click",
            metric_type=MetricType.CONVERSION,
        )

        db_session.refresh(metric)
        assert metric.experiment_id == exp.id

    def test_metric_back_reference_to_experiment(
        self, db_session, make_experiment, make_metric
    ):
        """Metric.experiment back-reference returns the correct Experiment object."""
        exp = make_experiment(name="Metric Back-ref")
        metric = make_metric(
            experiment=exp,
            name="CTR",
            event_name="click",
            metric_type=MetricType.CONVERSION,
        )

        db_session.refresh(metric)
        assert metric.experiment is not None
        assert metric.experiment.id == exp.id

    def test_experiment_owner_relationship(
        self, db_session, make_experiment, admin_user
    ):
        """Experiment.owner relationship returns the owning User object."""
        exp = make_experiment(name="Owner Test")

        db_session.refresh(exp)
        assert exp.owner is not None
        assert exp.owner.id == admin_user.id

    def test_user_experiments_back_reference(
        self, db_session, make_experiment, admin_user
    ):
        """User.experiments back-reference includes experiments owned by the user."""
        exp1 = make_experiment(name="User Exp 1")
        exp2 = make_experiment(name="User Exp 2")

        db_session.refresh(admin_user)
        owned_ids = {e.id for e in admin_user.experiments}
        assert exp1.id in owned_ids
        assert exp2.id in owned_ids

    def test_cascade_delete_variants_with_experiment(
        self, db_session, make_experiment, make_variant
    ):
        """Deleting an experiment cascades to delete its variants."""
        exp = make_experiment(name="Cascade Delete Test")
        v = make_variant(experiment=exp, name="Variant A")
        variant_id = v.id

        db_session.delete(exp)
        db_session.commit()

        deleted_variant = (
            db_session.query(Variant).filter(Variant.id == variant_id).first()
        )
        assert deleted_variant is None

    def test_cascade_delete_metrics_with_experiment(
        self, db_session, make_experiment, make_metric
    ):
        """Deleting an experiment cascades to delete its metrics."""
        exp = make_experiment(name="Cascade Metric Test")
        m = make_metric(
            experiment=exp,
            name="Cascade Metric",
            event_name="ev",
            metric_type=MetricType.CONVERSION,
        )
        metric_id = m.id

        db_session.delete(exp)
        db_session.commit()

        deleted_metric = db_session.query(Metric).filter(Metric.id == metric_id).first()
        assert deleted_metric is None

    def test_experiment_assignments_relationship(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Experiment.assignments relationship returns all assignments for that experiment."""
        exp = make_experiment(name="Assignment Rel Test")
        variant = make_variant(experiment=exp, name="Control", is_control=True)
        a1 = make_assignment(experiment=exp, variant=variant, user_id="user-001")
        a2 = make_assignment(experiment=exp, variant=variant, user_id="user-002")

        db_session.refresh(exp)
        assignment_ids = {a.id for a in exp.assignments}
        assert a1.id in assignment_ids
        assert a2.id in assignment_ids

    def test_variant_assignments_relationship(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Variant.assignments relationship returns all assignments for that variant."""
        exp = make_experiment(name="Variant Assignment Test")
        variant = make_variant(experiment=exp, name="Control", is_control=True)
        make_assignment(experiment=exp, variant=variant, user_id="user-v1")
        make_assignment(experiment=exp, variant=variant, user_id="user-v2")

        db_session.refresh(variant)
        assert len(variant.assignments) == 2

    def test_assignment_back_references(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        """Assignment.experiment and Assignment.variant back-references are correct."""
        exp = make_experiment(name="Assignment Back-ref")
        variant = make_variant(experiment=exp, name="Control", is_control=True)
        assignment = make_assignment(experiment=exp, variant=variant, user_id="user-br")

        db_session.refresh(assignment)
        assert assignment.experiment.id == exp.id
        assert assignment.variant.id == variant.id


@pytest.mark.integration
@pytest.mark.requires_db
class TestFeatureFlagRelationships:
    """Test ORM relationships on the FeatureFlag model."""

    def test_feature_flag_owner_relationship(
        self, db_session, make_feature_flag, admin_user
    ):
        """FeatureFlag.owner relationship returns the owning User object."""
        flag = make_feature_flag(name="Owner Flag", key="owner-flag-001")

        db_session.refresh(flag)
        assert flag.owner is not None
        assert flag.owner.id == admin_user.id

    def test_user_feature_flags_back_reference(
        self, db_session, make_feature_flag, admin_user
    ):
        """User.feature_flags back-reference includes flags owned by the user."""
        flag1 = make_feature_flag(name="Flag A", key="flag-rel-a")
        flag2 = make_feature_flag(name="Flag B", key="flag-rel-b")

        db_session.refresh(admin_user)
        flag_ids = {f.id for f in admin_user.feature_flags}
        assert flag1.id in flag_ids
        assert flag2.id in flag_ids
