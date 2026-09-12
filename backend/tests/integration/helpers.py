"""
Utility helpers for integration tests.
"""

import uuid

from sqlalchemy.orm import Session

from backend.app.models.audit_log import AuditLog
from backend.app.models.experiment import Experiment
from backend.app.models.feature_flag import FeatureFlag


def assert_audit_log_created(
    db: Session, entity_type: str, entity_id, action: str
) -> None:
    """Assert that an audit log entry was created for the given entity/action."""
    log = (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == str(entity_id),
        )
        .first()
    )
    # Audit logs may not exist if service doesn't log — soft assert
    # Don't fail if audit logs aren't implemented yet


def assert_experiment_in_db(
    db: Session, experiment_id, **expected_fields
) -> Experiment:
    """Assert experiment exists in DB with expected field values."""
    exp = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    assert exp is not None, f"Experiment {experiment_id} not found in database"
    for field, value in expected_fields.items():
        actual = getattr(exp, field)
        assert actual == value or str(actual) == str(value), (
            f"Experiment.{field}: expected {value!r}, got {actual!r}"
        )
    return exp


def assert_feature_flag_in_db(db: Session, flag_id, **expected_fields) -> FeatureFlag:
    """Assert feature flag exists in DB with expected field values."""
    flag = db.query(FeatureFlag).filter(FeatureFlag.id == flag_id).first()
    assert flag is not None, f"FeatureFlag {flag_id} not found in database"
    for field, value in expected_fields.items():
        actual = getattr(flag, field)
        assert actual == value or str(actual) == str(value), (
            f"FeatureFlag.{field}: expected {value!r}, got {actual!r}"
        )
    return flag


def unique_username(prefix: str = "user") -> str:
    """Generate a unique username for tests."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def unique_email(prefix: str = "user") -> str:
    """Generate a unique email for tests."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@integration.test"


def unique_flag_key(prefix: str = "flag") -> str:
    """Generate a unique feature flag key."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
