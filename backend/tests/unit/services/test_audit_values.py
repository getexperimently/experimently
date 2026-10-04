"""What an audit entry may record, per entity (#221).

``AUDIT_VALUE_FIELDS`` (recorded as values) and ``AUDIT_NAME_ONLY_FIELDS``
(recorded by name when they change) name columns of the entity's model. A
field the model does not have at this base cannot be listed, and no list may
name a secret.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.models.api_key import APIKey
from backend.app.models.audit_log import EntityType
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.feature_flag import FeatureFlag
from backend.app.models.global_holdout import GlobalHoldout
from backend.app.models.mutual_exclusion_group import MutualExclusionGroup
from backend.app.models.segment import Segment
from backend.app.models.user import User, UserRole
from backend.app.services.audit_service import (
    AUDIT_NAME_ONLY_FIELDS,
    AUDIT_REASON_MAX,
    AUDIT_VALUE_FIELDS,
    AUDIT_VALUE_MAX,
    AuditService,
    audit_changes,
    audit_identity,
    audit_snapshot,
    role_value,
)

pytestmark = [pytest.mark.unit]

MODELS = {
    EntityType.FEATURE_FLAG: FeatureFlag,
    EntityType.EXPERIMENT: Experiment,
    EntityType.USER: User,
    EntityType.API_KEY: APIKey,
    EntityType.HOLDOUT: GlobalHoldout,
    EntityType.MUTUAL_EXCLUSION_GROUP: MutualExclusionGroup,
    EntityType.SEGMENT: Segment,
}

#: Columns no audit entry may hold. ``key`` is a public slug on flags and
#: experiments, but on an API key it is the key's hash.
NEVER_RECORDED = {"hashed_password", "password", "token", "secret"}
NEVER_RECORDED_FOR = {EntityType.API_KEY: {"key"}}


def test_every_entity_with_values_has_a_model():
    assert set(AUDIT_VALUE_FIELDS) == set(MODELS)
    assert set(AUDIT_NAME_ONLY_FIELDS) == set(MODELS)


@pytest.mark.parametrize("entity", sorted(MODELS, key=lambda e: e.value))
def test_every_allow_listed_field_is_a_column(entity):
    columns = {c.name for c in MODELS[entity].__table__.columns}
    listed = set(AUDIT_VALUE_FIELDS[entity]) | set(AUDIT_NAME_ONLY_FIELDS[entity])
    assert listed <= columns, sorted(listed - columns)


@pytest.mark.parametrize("entity", sorted(MODELS, key=lambda e: e.value))
def test_no_allow_list_names_a_secret(entity):
    listed = set(AUDIT_VALUE_FIELDS[entity]) | set(AUDIT_NAME_ONLY_FIELDS[entity])
    assert not (listed & (NEVER_RECORDED | NEVER_RECORDED_FOR.get(entity, set())))


def test_an_update_records_changed_values_and_names_only_fields():
    row = SimpleNamespace(
        key="k",
        name="before",
        status=ExperimentStatus.DRAFT,
        start_date=None,
        end_date=None,
        description="secret plan",
        hypothesis="h",
        targeting_rules={"a": 1},
        metrics=None,
    )
    before = audit_snapshot(EntityType.EXPERIMENT, row)
    row.name = "after"
    row.status = ExperimentStatus.ACTIVE
    row.description = "a new secret plan"
    old, new = audit_changes(before, audit_snapshot(EntityType.EXPERIMENT, row))
    assert old == {"name": "before", "status": "draft"}
    assert new == {
        "name": "after",
        "status": "active",
        "changed_fields": ["description"],
    }
    assert "secret" not in json.dumps([old, new])


def test_nothing_changed_records_no_values():
    row = SimpleNamespace(
        name="h", holdout_percentage=5, is_active=False, description=""
    )
    snap = audit_snapshot(EntityType.HOLDOUT, row)
    assert audit_changes(snap, dict(snap)) == (None, None)


def test_identity_is_the_value_fields_only():
    row = SimpleNamespace(
        name="k1", scopes="sdk:ruleset", expires_at=None, user_id=uuid4(), key="hash"
    )
    identity = audit_identity(audit_snapshot(EntityType.API_KEY, row))
    assert set(identity) == {"name", "scopes", "expires_at", "user_id"}
    assert "hash" not in json.dumps(identity)


def test_role_value_shape():
    user = SimpleNamespace(role=UserRole.ANALYST, is_superuser=True)
    assert role_value(user) == {"role": "ANALYST", "is_superuser": True}


class _Session:
    def __init__(self):
        self.added = []

    def add(self, row):
        self.added.append(row)


def test_record_caps_reason_name_and_values():
    db = _Session()
    actor = SimpleNamespace(id=None, email=None, username=None)
    row = AuditService.record(
        db,
        actor=actor,
        action="feature_flag_update",
        entity_type="feature_flag",
        entity_id=uuid4(),
        entity_name="n" * 300,
        before=None,
        after={"name": "x" * (AUDIT_VALUE_MAX + 10)},
        reason="r" * (AUDIT_REASON_MAX + 10),
    )
    assert db.added == [row]
    assert row.user_email == "system"
    assert len(row.entity_name) == 255
    assert len(row.reason) == AUDIT_REASON_MAX
    assert json.loads(row.new_value) == {"truncated": True, "changed_fields": ["name"]}
    assert row.timestamp <= datetime.now(timezone.utc)
